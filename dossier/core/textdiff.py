"""Compare Two Files for text: the two files side by side, line against line (Qt-free).

``read_lines`` reads a file as text when it is one (small enough, no NUL bytes, UTF-8 or UTF-16 or a single-byte code page);
``side_by_side`` pairs the lines with ``difflib`` into rows the window shows. Binary or large files keep the byte answer.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Optional

from .vfs import FileSystem

MAX_BYTES = 4 * 1024 * 1024        # larger files are compared by bytes only
SNIFF = 8192
SAME, CHANGED, LEFT_ONLY, RIGHT_ONLY = "same", "changed", "left", "right"


@dataclass
class Row:
    kind: str                       # same | changed | left (only in the left file) | right (only in the right one)
    left_no: int = 0                # line numbers from 1; 0 = no line on that side
    left: str = ""
    right_no: int = 0
    right: str = ""


def _decode(raw: bytes) -> Optional[str]:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in raw[:SNIFF]:
        return None                                     # a binary file
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")   # an old single-byte text file


def read_lines(fs: FileSystem, path: str, size: int) -> Optional[list]:
    """The lines of ``path`` without their line ends, or None when it is too large or not text."""
    if size > MAX_BYTES:
        return None
    with fs.open_read(path) as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return None
    text = _decode(raw)
    return None if text is None else text.splitlines()


def side_by_side(a: list, b: list) -> list:
    """Rows pairing the lines of ``a`` (left) and ``b`` (right): equal runs, changed lines opposite each other, lines only on
    one side opposite a gap."""
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [Row(SAME, i1 + k + 1, a[i1 + k], j1 + k + 1, b[j1 + k]) for k in range(i2 - i1)]
        elif tag == "delete":
            rows += [Row(LEFT_ONLY, i + 1, a[i]) for i in range(i1, i2)]
        elif tag == "insert":
            rows += [Row(RIGHT_ONLY, 0, "", j + 1, b[j]) for j in range(j1, j2)]
        else:                                           # replace: pair what can be paired, the rest against a gap
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                li, rj = i1 + k, j1 + k
                left = (li + 1, a[li]) if li < i2 else (0, "")
                right = (rj + 1, b[rj]) if rj < j2 else (0, "")
                kind = CHANGED if left[0] and right[0] else LEFT_ONLY if left[0] else RIGHT_ONLY
                rows.append(Row(kind, left[0], left[1], right[0], right[1]))
    return rows


def summary(rows: list) -> str:
    changed = sum(1 for r in rows if r.kind == CHANGED)
    left = sum(1 for r in rows if r.kind == LEFT_ONLY)
    right = sum(1 for r in rows if r.kind == RIGHT_ONLY)
    if not (changed or left or right):
        return "The texts are the same (the files differ only in line ends or encoding)."
    return f"{changed} line{'s' if changed != 1 else ''} changed, {left} only on the left, {right} only on the right."
