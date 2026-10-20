"""Search for files by name, size, date and content (the engine; the dialog and the result list are in the window).

A search walks a folder tree once. Names are tested first (cheap), then size and dates, and only files that pass all of
those are opened for the text (expensive). It runs on a thread: ``progress(scanned, found)`` is called now and then and
the ``CancelToken`` stops it between items. Links are not followed; a folder that cannot be read is counted and skipped.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, replace
from typing import Optional

from .listings import relative
from .progress import CancelToken, check
from .vfs import Entry, FileSystem

SNIFF = 8192                 # bytes looked at to tell text from a binary file
MAX_TEXT_FILE = 100 * 1024 * 1024   # larger files are not opened for their text
SNIPPET = 140


@dataclass
class Criteria:
    root: str
    name: str = ""                   # "*.jpg;*.png", "report" (a part of the name), "!*.tmp" excludes
    case_sensitive: bool = False
    kinds: str = "files"             # files | folders | both
    subfolders: bool = True
    min_size: Optional[int] = None   # bytes
    max_size: Optional[int] = None
    newer_than: Optional[float] = None   # modified at or after this time (epoch seconds)
    older_than: Optional[float] = None   # modified at or before this time
    text: str = ""                   # what the file must contain
    text_regex: bool = False
    text_case: bool = False
    max_results: int = 100_000

    def describe(self) -> str:
        """A short text for the title of the result list."""
        parts = []
        if self.name:
            parts.append(self.name)
        if self.text:
            parts.append(f'containing "{self.text}"')
        if self.min_size is not None or self.max_size is not None:
            parts.append("by size")
        if self.newer_than is not None or self.older_than is not None:
            parts.append("by date")
        return " ".join(parts) or "everything"


@dataclass
class SearchResult:
    entries: list
    scanned: int = 0                 # files and folders looked at
    unreadable: int = 0              # folders that could not be read
    truncated: bool = False          # stopped at ``max_results``


class BadCriteria(ValueError):
    """The criteria cannot be used (an invalid pattern, a size or date range that is empty)."""


def _name_test(text: str, case_sensitive: bool):
    """A function name -> bool for ``text``: ``;`` separates alternatives, a part with ``*`` ``?`` or ``[`` must match the
    whole name, a plain part is found anywhere in the name, ``!`` in front excludes. No text: everything fits."""
    wanted, unwanted = [], []
    for raw in (p.strip() for p in text.split(";")):
        if not raw:
            continue
        negative = raw.startswith("!") and len(raw) > 1
        part = raw[1:] if negative else raw
        if any(ch in part for ch in "*?["):
            rx = re.compile(fnmatch.translate(part), 0 if case_sensitive else re.IGNORECASE)
            test = rx.fullmatch
        else:
            needle = part if case_sensitive else part.casefold()
            test = (lambda n, needle=needle: needle in n) if case_sensitive else \
                   (lambda n, needle=needle: needle in n.casefold())
        (unwanted if negative else wanted).append(test)
    if not wanted and not unwanted:
        return lambda name: True
    return lambda name: (not wanted or any(t(name) for t in wanted)) and not any(t(name) for t in unwanted)


def _text_test(c: Criteria):
    if not c.text:
        return None
    flags = 0 if c.text_case else re.IGNORECASE
    try:
        rx = re.compile(c.text if c.text_regex else re.escape(c.text), flags)
    except re.error as e:
        raise BadCriteria(f"the text is not a valid pattern: {e}") from e
    return rx


def validate(c: Criteria) -> None:
    if c.min_size is not None and c.max_size is not None and c.min_size > c.max_size:
        raise BadCriteria("the smallest size is larger than the largest")
    if c.newer_than is not None and c.older_than is not None and c.newer_than > c.older_than:
        raise BadCriteria("the earliest date is after the latest")
    if c.kinds not in ("files", "folders", "both"):
        raise BadCriteria("kinds must be files, folders or both")
    if c.text and c.kinds == "folders":
        raise BadCriteria("a folder has no text to search")
    _text_test(c)


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def find_text(fs: FileSystem, path: str, size: int, rx, cancel: Optional[CancelToken] = None) -> Optional[str]:
    """``"line 12: the line"`` for the first line of the file that matches, or None. Binary and huge files give None."""
    if size > MAX_TEXT_FILE:
        return None
    try:
        with fs.open_read(path) as f:
            head = f.read(SNIFF)
            if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
                return None                              # a binary file
            wide = head.startswith((b"\xff\xfe", b"\xfe\xff"))
            rest = head + f.read() if size <= 16 * 1024 * 1024 else None
            if rest is not None:
                lines = _decode(rest).splitlines()
            else:                                         # a big text file: line by line, never all in memory
                f.seek(0) if hasattr(f, "seek") else None
                lines = (_decode(raw) for raw in _iter_lines(f, head, wide))
            for number, line in enumerate(lines, start=1):
                if number % 2000 == 0:
                    check(cancel)
                if rx.search(line):
                    return f"line {number}: {line.strip()[:SNIPPET]}"
    except OSError:
        return None
    return None


def _iter_lines(f, head: bytes, wide: bool):
    buffer = head
    while True:
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line
        chunk = f.read(1 << 20)
        if not chunk:
            if buffer:
                yield buffer
            return
        buffer += chunk


def search(fs: FileSystem, c: Criteria, cancel: Optional[CancelToken] = None, progress=None) -> SearchResult:
    """Run the search. Raises ``BadCriteria`` for criteria that cannot work, ``Cancelled`` when cancelled."""
    validate(c)
    name_ok = _name_test(c.name, c.case_sensitive)
    rx = _text_test(c)
    out = SearchResult(entries=[])
    want_files, want_folders = c.kinds in ("files", "both"), c.kinds in ("folders", "both")
    stack = [c.root]
    last_report = 0
    while stack:
        check(cancel)
        here = stack.pop()
        try:
            entries = fs.list(here)
        except OSError:
            out.unreadable += 1
            continue
        for e in entries:
            if e.is_link:
                continue
            out.scanned += 1
            if e.is_dir and c.subfolders:
                stack.append(e.path)
            if e.is_dir and not want_folders or not e.is_dir and not want_files:
                continue
            if not name_ok(e.name):
                continue
            if not e.is_dir:
                if c.min_size is not None and e.size < c.min_size or c.max_size is not None and e.size > c.max_size:
                    continue
            if c.newer_than is not None and e.mtime < c.newer_than or c.older_than is not None and e.mtime > c.older_than:
                continue
            detail = ""
            if rx is not None and not e.is_dir:
                detail = find_text(fs, e.path, e.size, rx, cancel)
                if detail is None:
                    continue
            out.entries.append(replace(e, name=relative(c.root, e.path, fs.sep), detail=detail or ""))
            if len(out.entries) >= c.max_results:
                out.truncated = True
                return out
        if progress is not None and out.scanned - last_report >= 200:
            last_report = out.scanned
            progress(out.scanned, len(out.entries))
    if progress is not None:
        progress(out.scanned, len(out.entries))
    return out
