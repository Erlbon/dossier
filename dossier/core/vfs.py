"""Virtual file system interface (spec section 5).

One small interface serves local disk now; archives, SQLite and remote sources implement
the same class later, so windows, viewers and commands do not care where items come from.
"""
from __future__ import annotations

import os
import re
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Iterator

from .platform import decode_name, is_link_like, longpath, path_key, strip_longpath


class NotWritable(OSError):
    """The file system (or this connection) is read-only (spec principle 2)."""


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

    def scan(self, path: str) -> Iterator[Entry]:
        """Entries one by one, so a window can show the first rows of a huge folder at once."""
        return iter(self.list(path))

    # Writing. Read-only sources keep these defaults and raise NotWritable. -------------
    def mkdir(self, path: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        raise NotWritable(path)

    def rename(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        """Move within this file system. Refuses an existing target unless ``overwrite``."""
        raise NotWritable(src)

    def remove(self, path: str) -> None:
        """Delete one file, link or EMPTY folder. Recursion belongs to the operations layer."""
        raise NotWritable(path)

    def open_write(self, path: str, *, exclusive: bool = False) -> BinaryIO:
        """Create or truncate a file. ``exclusive`` fails if it already exists."""
        raise NotWritable(path)

    def set_mtime(self, path: str, mtime: float) -> None:
        raise NotWritable(path)


class LocalFileSystem(FileSystem):
    writable = True

    def list(self, path: str) -> list[Entry]:
        return list(self.scan(path))

    def scan(self, path: str) -> Iterator[Entry]:
        with os.scandir(longpath(path)) as it:
            for de in it:
                yield self._entry(de)

    def mkdir(self, path: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        p = longpath(path)
        if parents:
            os.makedirs(p, exist_ok=exist_ok)
        elif exist_ok and os.path.isdir(p):
            return
        else:
            os.mkdir(p)

    def rename(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        s, d = longpath(src), longpath(dst)
        if not overwrite and os.path.lexists(d):
            # A change of case only ('a.md' -> 'A.md') names the same file on a case-insensitive system.
            case_only = src != dst and os.path.normcase(src) == os.path.normcase(dst)
            if not case_only:
                raise FileExistsError(dst)
        os.replace(s, d)

    def remove(self, path: str) -> None:
        p = longpath(path)
        if os.path.islink(p):
            try:
                os.remove(p)
            except OSError:      # a Windows link to a folder is removed like a folder
                os.rmdir(p)
        elif os.path.isdir(p):
            os.rmdir(p)          # junctions too: removes the junction, never its target
        else:
            os.remove(p)

    def open_write(self, path: str, *, exclusive: bool = False) -> BinaryIO:
        return open(longpath(path), "xb" if exclusive else "wb")

    def set_mtime(self, path: str, mtime: float) -> None:
        os.utime(longpath(path), (mtime, mtime))

    def stat(self, path: str) -> Entry:
        p = longpath(path)
        lst = os.lstat(p)
        is_link = is_link_like(stat.S_ISLNK(lst.st_mode), getattr(lst, "st_file_attributes", None))
        try:
            st = os.stat(p) if is_link else lst   # a link shows what it points at
        except OSError:                              # broken link
            st = lst
        is_dir = stat.S_ISDIR(st.st_mode)
        return Entry(
            name=decode_name(os.path.basename(path) or path),
            path=path,
            is_dir=is_dir,
            size=0 if is_dir else st.st_size,
            mtime=st.st_mtime,
            is_link=is_link,
        )

    def open_read(self, path: str) -> BinaryIO:
        return open(longpath(path), "rb")

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
        try:
            attrs = getattr(de.stat(follow_symlinks=False), "st_file_attributes", None)
        except OSError:
            attrs = None
        return Entry(
            name=decode_name(de.name),
            path=strip_longpath(de.path),
            is_dir=is_dir,
            size=0 if is_dir else size,
            mtime=mtime,
            is_link=is_link_like(de.is_symlink(), attrs),
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
    """Every item below ``path``, depth first.

    Links and junctions are listed but not entered. A subfolder that cannot be read is
    skipped (its own entry is still yielded); a root that cannot be read raises.
    """
    yield from _walk(fs, path, root=True)


def _walk(fs: FileSystem, path: str, root: bool) -> Iterator[Entry]:
    try:
        entries = sort_entries(fs.list(path))
    except OSError:
        if root:
            raise
        return
    for e in entries:
        yield e
        if e.is_dir and not e.is_link:
            yield from _walk(fs, e.path, root=False)


__all__ = ["Entry", "FileSystem", "LocalFileSystem", "NotWritable", "natural_key", "sort_entries", "walk", "path_key"]
