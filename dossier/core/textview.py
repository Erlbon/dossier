"""Read-only text viewing of files of any size (spec V1).

The file is read through the operating system's cache (not memory-mapped: a mapped file cannot
be truncated by another program on Windows, which would break a log being rotated). A line index
(the byte offset of every line) is built once, in the background, with progress and cancel, and
then any line is one seek and read away. Encoding is detected
(byte-order mark, UTF-8, else Windows-1252) and can be forced. UTF-16 and UTF-32 cannot be indexed
by byte, so those files are decoded whole up to a cap.
"""
from __future__ import annotations

import bisect
import codecs
import re
import threading
from array import array
from typing import Optional

from .platform import longpath
from .progress import CancelToken, ProgressFn, check

AUTO = "auto"
ENCODINGS = ("utf-8", "utf-16", "windows-1252", "iso-8859-1", "cp850", "cp437", "windows-1251", "iso-8859-2")
MAX_LINE_BYTES = 20000          # a longer line is cut when shown (a minified file is one huge line)
MAX_WIDE_BYTES = 64 * 1024 * 1024
SAMPLE = 64 * 1024
_CHUNK = 8 * 1024 * 1024
NEWLINE = bytes([10])


class TextTooLarge(Exception):
    """A UTF-16 or UTF-32 file bigger than the whole-file decode cap."""


def detect_encoding(sample: bytes) -> str:
    """BOM first; then UTF-16 by the pattern of zero bytes; then UTF-8 if the sample is valid
    UTF-8; otherwise Windows-1252, the usual meaning of 'ANSI text' on the Windows side."""
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8"
    if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    head = sample[:4096]
    if len(head) >= 4 and head.count(0) > len(head) // 4:       # lots of zeros: wide text, not binary
        even, odd = head[0::2].count(0), head[1::2].count(0)
        if odd > even * 4:
            return "utf-16-le"
        if even > odd * 4:
            return "utf-16-be"
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        decoder.decode(sample, final=False)                      # a cut at the end of the sample is fine
        return "utf-8"
    except UnicodeDecodeError:
        return "windows-1252"


def looks_binary(sample: bytes, encoding: str) -> bool:
    """Zero bytes in text that is not wide: probably not a text file at all."""
    return not encoding.startswith(("utf-16", "utf-32")) and b"\x00" in sample[:SAMPLE]


class TextSource:
    def __init__(self, path: str, encoding: str = AUTO) -> None:
        self.path = path
        self._file = open(longpath(path), "rb")
        self._lock = threading.Lock()      # the index job and the window both read through one file object
        self.size = 0
        self._wide_lines: Optional[list] = None
        self._starts = array("Q")
        self._indexed = 0           # bytes scanned so far
        self.complete = False       # the whole file is indexed
        self.binary = False
        self._requested = encoding
        self.encoding = "utf-8"
        self._bom = 0
        self._measure()
        self.set_encoding(encoding)

    # file ---------------------------------------------------------------------------------
    def _measure(self) -> None:
        with self._lock:
            self._file.seek(0, 2)
            self.size = self._file.tell()

    def close(self) -> None:
        with self._lock:
            self._file.close()

    def _bytes(self, start: int, end: int) -> bytes:
        with self._lock:
            self._file.seek(start)
            return self._file.read(max(0, end - start))

    # encoding ------------------------------------------------------------------------------
    def set_encoding(self, encoding: str) -> None:
        """Choose an encoding (or ``auto``) and start the index again."""
        self._requested = encoding
        sample = self._bytes(0, SAMPLE)
        self.encoding = detect_encoding(sample) if encoding == AUTO else encoding
        self.binary = looks_binary(sample, self.encoding)
        self._bom = len(codecs.BOM_UTF8) if self.encoding == "utf-8" and sample.startswith(codecs.BOM_UTF8) else 0
        self._wide_lines = None
        self._starts = array("Q", [self._bom])
        self._indexed = self._bom
        self.complete = False

    @property
    def is_wide(self) -> bool:
        return self.encoding.startswith(("utf-16", "utf-32"))

    # index ---------------------------------------------------------------------------------
    def build_index(self, cancel: Optional[CancelToken] = None, progress: Optional[ProgressFn] = None) -> None:
        """Scan for line starts. Cheap for normal files; progress and cancel matter for gigabytes."""
        if self.is_wide:
            self._index_wide(cancel, progress)
            return
        pos = self._indexed
        starts = self._starts
        while pos < self.size:
            check(cancel)
            chunk = self._bytes(pos, min(self.size, pos + _CHUNK))
            if not chunk:
                break
            at = 0
            while True:
                i = chunk.find(NEWLINE, at)
                if i < 0:
                    break
                starts.append(pos + i + 1)
                at = i + 1
            pos += len(chunk)
            self._indexed = pos
            if progress:
                progress(pos, self.size)
        self._indexed = self.size
        self.complete = True
        if progress:
            progress(self.size, self.size)

    def _index_wide(self, cancel, progress) -> None:
        if self.size > MAX_WIDE_BYTES:
            raise TextTooLarge(f"{self.encoding} files over {MAX_WIDE_BYTES // (1024 * 1024)} MB cannot be viewed")
        check(cancel)
        text = self._bytes(0, self.size).decode(self.encoding, errors="replace").lstrip("﻿")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        self._wide_lines = [ln.rstrip("\r") for ln in lines]
        self._indexed = self.size
        self.complete = True
        if progress:
            progress(self.size, self.size)

    def refresh(self) -> bool:
        """The file grew (a log being written): map the new end and index the added part. Returns True
        when something was added; a file that shrank is reindexed from the start."""
        old = self.size
        self._measure()
        if self.size < old:
            self.set_encoding(self._requested)
            self.build_index()
            return True
        if self.size == old:
            return False
        if self.is_wide:
            self.build_index()
        else:
            self.complete = False
            self.build_index()
        return True

    # lines ---------------------------------------------------------------------------------
    @property
    def line_count(self) -> int:
        if self._wide_lines is not None:
            return len(self._wide_lines)
        n = len(self._starts)
        if n and self._starts[-1] >= self.size:
            n -= 1                                   # the file ends with a newline: no extra empty line
        return max(n, 0) if self.size else 0

    def line(self, n: int) -> str:
        if n < 0 or n >= self.line_count:
            return ""
        if self._wide_lines is not None:
            text = self._wide_lines[n]
            return text if len(text) <= MAX_LINE_BYTES else text[:MAX_LINE_BYTES] + " ..."
        s = self._starts[n]
        e = self._starts[n + 1] if n + 1 < len(self._starts) else self.size
        raw = self._bytes(s, min(e, s + MAX_LINE_BYTES + 2))
        cut = e - s > MAX_LINE_BYTES + 2
        text = raw.rstrip(b"\r\n").decode(self.encoding, errors="replace")
        return text + " ..." if cut else text

    def lines(self, start: int, count: int) -> list:
        return [self.line(i) for i in range(start, min(start + count, self.line_count))]

    # search --------------------------------------------------------------------------------
    def find(self, needle: str, line: int = 0, col: int = 0, *, forward: bool = True, case_sensitive: bool = False,
             cancel: Optional[CancelToken] = None, progress: Optional[ProgressFn] = None) -> Optional[tuple]:
        """The next match at or after (line, col), or the previous one before it. Returns
        ``(line, col)`` in characters, or None. Needs a finished index."""
        if not needle or self.line_count == 0:
            return None
        if forward and not self.is_wide and (case_sensitive or needle.isascii()):
            return self._find_fast(needle, line, col, case_sensitive, cancel)
        return self._find_scan(needle, line, col, forward, case_sensitive, cancel, progress)

    def _find_fast(self, needle: str, line: int, col: int, case_sensitive: bool, cancel) -> Optional[tuple]:
        try:
            raw_needle = needle.encode(self.encoding)
        except (UnicodeEncodeError, LookupError):
            return self._find_scan(needle, line, col, True, case_sensitive, cancel, None)
        start = self._starts[min(line, len(self._starts) - 1)] + len(self.line(line)[:col].encode(self.encoding, "replace"))
        pattern = re.compile(re.escape(raw_needle), 0 if case_sensitive else re.IGNORECASE)
        overlap = len(raw_needle) - 1
        pos = start
        while pos < self.size:
            check(cancel)
            chunk = self._bytes(pos, min(self.size, pos + _CHUNK + overlap))
            m = pattern.search(chunk)
            if m:
                return self._locate(pos + m.start())
            if pos + len(chunk) >= self.size:
                return None
            pos += max(1, _CHUNK)
        return None

    def _locate(self, offset: int) -> Optional[tuple]:
        n = bisect.bisect_right(self._starts, offset) - 1
        if n >= self.line_count:
            return None
        prefix = self._bytes(self._starts[n], offset)
        return n, len(prefix.decode(self.encoding, errors="replace"))

    def _find_scan(self, needle, line, col, forward, case_sensitive, cancel, progress) -> Optional[tuple]:
        key = needle if case_sensitive else needle.lower()
        total = self.line_count
        line = min(max(line, 0), total - 1)
        rng = range(line, total) if forward else range(line, -1, -1)
        for i in rng:
            if (i - line) % 2000 == 0:
                check(cancel)
                if progress:
                    progress(abs(i - line), total)
            text = self.line(i)
            hay = text if case_sensitive else text.lower()
            if forward:
                j = hay.find(key, col if i == line else 0)
            else:                       # a match must start before the cursor on the first line
                j = hay.rfind(key, 0, col + len(key) - 1) if i == line else hay.rfind(key)
            if j >= 0:
                return i, j
        return None
