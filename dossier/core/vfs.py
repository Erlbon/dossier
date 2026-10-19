"""Virtual file system interface (spec section 5).

One small interface serves local disk now; archives, SQLite and remote sources implement
the same class later, so windows, viewers and commands do not care where items come from.
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Iterator

from .platform import decode_name, path_key


@dataclass(frozen=True)
class Entry:
    name: str            # safe to display (see platform.decode_name)
    path: str            # real path, usable to open the item
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    is_link: bool = False


class FileSystem(ABC):
    """What every source of files provides."""

    writable = False

    @abstractmethod
    def list(self, path: str) -> list[Entry]: ...

    @abstractmethod
    def stat(self, path: str) -> Entry: ...

    @abstractmethod
    def open_read(self, path: str) -> BinaryIO: ...


class LocalFileSystem(FileSystem):
    writable = True

    def list(self, path: str) -> list[Entry]:
        out: list[Entry] = []
        with os.scandir(path) as it:
            for de in it:
                out.append(self._entry(de))
        return out

    def stat(self, path: str) -> Entry:
        st = os.stat(path)
        return Entry(
            name=decode_name(os.path.basename(path) or path),
            path=path,
            is_dir=os.path.isdir(path),
            size=st.st_size,
            mtime=st.st_mtime,
            is_link=os.path.islink(path),
        )

    def open_read(self, path: str) -> BinaryIO:
        return open(path, "rb")

    @staticmethod
    def _entry(de: os.DirEntry) -> Entry:
        try:
            st = de.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:  # broken link, permission denied: still list it
            size, mtime = 0, 0.0
        try:
            is_dir = de.is_dir()
        except OSError:
            is_dir = False
        return Entry(
            name=decode_name(de.name),
            path=de.path,
            is_dir=is_dir,
            size=size,
            mtime=mtime,
            is_link=de.is_symlink(),
        )


_DIGITS = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple:
    """Sort key: 'file2' before 'file10'. Case is folded for ORDER only; the exact name
    breaks ties, so 'A.md' and 'a.md' stay two distinct items (O11)."""
    parts = [int(p) if p.isdigit() else p.casefold() for p in _DIGITS.split(name)]
    return (parts, name)


def sort_entries(entries: list[Entry]) -> list[Entry]:
    """Folders first, then natural name order."""
    return sorted(entries, key=lambda e: (not e.is_dir, natural_key(e.name)))


def walk(fs: FileSystem, path: str) -> Iterator[Entry]:
    """Every item below ``path``, depth first."""
    for e in sort_entries(fs.list(path)):
        yield e
        if e.is_dir and not e.is_link:
            yield from walk(fs, e.path)


__all__ = ["Entry", "FileSystem", "LocalFileSystem", "natural_key", "sort_entries", "walk", "path_key"]
