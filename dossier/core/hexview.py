"""Reading and searching a file of any size for the hex viewer, one block at a time. Read-only; Qt-free.

``HexFile`` reads rows on demand (nothing is loaded whole), so a file of many gigabytes opens at once. ``find`` looks for a byte string
in chunks, forward or back, and can wrap around; it stops at a ``CancelToken``. ``parse_hex`` turns what a person types ("DE AD be ef",
"0xDEADBEEF") into bytes, and ``inspect`` says what a few bytes mean as numbers.
"""
from __future__ import annotations

import re
import struct
import threading
from typing import Optional

from .platform import longpath
from .progress import CancelToken, check

WIDTH = 16
CHUNK = 4 * 1024 * 1024
PRINTABLE = {i: chr(i) for i in range(0x20, 0x7F)}
_HEX = re.compile(r"^(0x)?([0-9a-fA-F]{2}[\s,]*)+$")


class HexFile:
    def __init__(self, path: str) -> None:
        self.path = path
        self._file = open(longpath(path), "rb")
        self._lock = threading.Lock()                 # the window paints rows while a search reads blocks
        self._file.seek(0, 2)
        self.size = self._file.tell()

    def close(self) -> None:
        self._file.close()

    def read(self, offset: int, n: int) -> bytes:
        if offset < 0 or offset >= self.size or n <= 0:
            return b""
        with self._lock:
            self._file.seek(offset)
            return self._file.read(min(n, self.size - offset))

    def refresh(self) -> bool:
        """Pick up a file that grew or shrank; True when the size changed."""
        with self._lock:
            self._file.seek(0, 2)
            size = self._file.tell()
        changed = size != self.size
        self.size = size
        return changed

    @property
    def rows(self) -> int:
        return (self.size + WIDTH - 1) // WIDTH

    def row(self, index: int) -> bytes:
        return self.read(index * WIDTH, WIDTH)

    def find(self, pattern: bytes, start: int, *, forward: bool = True, wrap: bool = True, cancel: Optional[CancelToken] = None,
             ignore_case: bool = False) -> int:
        """The offset of the next match that begins at or after ``start`` (forward), or the last one that begins before it (backward);
        -1 when there is none. ``wrap`` goes on from the other end of the file."""
        if not pattern or self.size == 0:
            return -1
        needle = pattern.lower() if ignore_case else pattern
        start = max(0, min(start, self.size))
        if forward:
            hit = self._first(needle, start, self.size, cancel, ignore_case)
            return hit if hit >= 0 or not wrap else self._first(needle, 0, start, cancel, ignore_case)
        hit = self._last(needle, 0, start, cancel, ignore_case)
        return hit if hit >= 0 or not wrap else self._last(needle, start, self.size, cancel, ignore_case)

    def _blocks(self, lo: int, hi: int, overlap: int) -> list:
        """``(position, bytes)`` blocks that cover every match beginning in ``[lo, hi)``: each reaches ``overlap`` bytes into the next."""
        out = []
        pos = lo
        while pos < hi:
            out.append((pos, self.read(pos, min(CHUNK, hi - pos) + overlap)))
            pos += CHUNK
        return out

    def _first(self, needle: bytes, lo: int, hi: int, cancel, ignore_case: bool) -> int:
        """The lowest match beginning in ``[lo, hi)``."""
        for pos, data in self._blocks(lo, hi, len(needle) - 1):
            check(cancel)
            i = (data.lower() if ignore_case else data).find(needle)
            if i >= 0 and pos + i < hi:
                return pos + i
        return -1

    def _last(self, needle: bytes, lo: int, hi: int, cancel, ignore_case: bool) -> int:
        """The highest match beginning in ``[lo, hi)``."""
        for pos, data in reversed(self._blocks(lo, hi, len(needle) - 1)):
            check(cancel)
            haystack = data.lower() if ignore_case else data
            i = haystack.rfind(needle, 0, min(len(haystack), hi - pos + len(needle) - 1))
            if i >= 0:
                return pos + i
        return -1


def format_row(offset: int, data: bytes, offset_digits: int = 8) -> tuple:
    """``(offset text, hex text, ascii text)`` of one row; missing bytes of a short last row are blank."""
    hexes = [f"{b:02X}" for b in data] + ["  "] * (WIDTH - len(data))
    left, right = " ".join(hexes[:8]), " ".join(hexes[8:])
    return f"{offset:0{offset_digits}X}", f"{left}  {right}", "".join(PRINTABLE.get(b, ".") for b in data)


def offset_digits(size: int) -> int:
    return max(8, len(f"{max(size - 1, 0):X}"))


def parse_hex(text: str) -> Optional[bytes]:
    """Bytes from ``DE AD be ef``, ``0xDEADBEEF`` or ``de,ad``; None when it is not an even run of hex digits."""
    text = text.strip()
    if not text or not _HEX.match(text):
        return None
    digits = re.sub(r"[^0-9a-fA-F]", "", text[2:] if text.lower().startswith("0x") else text)
    return bytes.fromhex(digits) if len(digits) % 2 == 0 else None


def inspect(data: bytes) -> list:
    """What the bytes at the cursor are as numbers: ``[(label, text)]`` (little endian, then big endian for 16 and 32 bits)."""
    out = []
    if len(data) >= 1:
        out.append(("8-bit", f"{data[0]}  (signed {struct.unpack('b', data[:1])[0]})"))
    if len(data) >= 2:
        out.append(("16-bit", f"{struct.unpack('<H', data[:2])[0]}  /  big endian {struct.unpack('>H', data[:2])[0]}"))
    if len(data) >= 4:
        out.append(("32-bit", f"{struct.unpack('<I', data[:4])[0]}  /  big endian {struct.unpack('>I', data[:4])[0]}"))
        out.append(("Float", f"{struct.unpack('<f', data[:4])[0]:.6g}"))
    if len(data) >= 8:
        out.append(("64-bit", f"{struct.unpack('<Q', data[:8])[0]}"))
    return out
