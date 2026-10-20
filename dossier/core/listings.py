"""Folders that are only lists of real files: every file below a folder ("flat view"), and the result of a search.

An entry of such a folder has the name it is shown under (its path relative to where the list was made) and the REAL
path of the file. Every command (copy, move, rename, delete, marking, the clipboard, the viewer) works on real paths, so
they work on these lists unchanged; the lists themselves are read-only (nothing can be created or pasted into one).

    flat://C:\\Photos         every file below C:\\Photos, however deep
    found://3                  the third stored result list (a search)

The way up (``..``) of either leads back to the real folder it was made from.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from typing import Optional

from .progress import CancelToken, check
from .vfs import Entry, FileSystem, NotWritable

FLAT_PREFIX = "flat://"
FOUND_PREFIX = "found://"
MAX_FLAT = 500_000          # more files than this are not listed as one list: the list would be unusable and slow
MAX_STORED = 20             # result lists kept; the oldest go first


def relative(root: str, path: str, sep: str) -> str:
    """``path`` below ``root``, with the file system's separator (no leading separator)."""
    trimmed = root.rstrip("\\/")
    if path[:len(trimmed)].lower() == trimmed.lower() and len(path) > len(trimmed):
        return path[len(trimmed):].lstrip("\\/").replace("\\", sep).replace("/", sep)
    return path


def walk_files(fs: FileSystem, root: str, cancel: Optional[CancelToken] = None, limit: int = MAX_FLAT,
               on_count=None) -> list:
    """Every file below ``root`` as entries named by their path relative to ``root``. Links are not followed, a folder
    that cannot be read is skipped, and more than ``limit`` files is an error rather than a freeze."""
    out: list = []
    stack = [root]
    while stack:
        check(cancel)
        here = stack.pop()
        try:
            entries = fs.list(here)
        except OSError:
            continue
        for e in entries:
            if e.is_link:
                continue
            if e.is_dir:
                stack.append(e.path)
            else:
                out.append(replace(e, name=relative(root, e.path, fs.sep)))
                if len(out) > limit:
                    raise OSError(f"more than {limit:,} files below this folder: too many for one list")
        if on_count is not None:
            on_count(len(out))
    return out


class FlatFileSystem(FileSystem):
    """``flat://<folder>``: the files below a folder as one list."""

    scheme = "flat"
    writable = False

    def __init__(self, base: FileSystem) -> None:
        self.base = base
        self.sep = base.sep
        self.case_sensitive = base.case_sensitive

    @staticmethod
    def target(path: str) -> str:
        return path[len(FLAT_PREFIX):] if path.startswith(FLAT_PREFIX) else path

    # the path functions: the list lives "inside" its folder, and its way up is that folder
    def join(self, base: str, *parts: str) -> str:
        return self.base.join(self.target(base), *parts)

    def basename(self, path: str) -> str:
        folder = self.target(path).rstrip("\\/")
        return f"{self.base.basename(folder) or folder} (all files)"

    def dirname(self, path: str) -> str:
        return self.target(path)

    def is_root(self, path: str) -> bool:
        return False

    def parent(self, path: str) -> Optional[str]:
        return self.target(path)

    def list(self, path: str) -> list:
        return walk_files(self.base, self.target(path))

    def scan(self, path: str):
        return iter(self.list(path))

    def stat(self, path: str) -> Entry:
        return Entry(name=self.basename(path), path=path, is_dir=True, kind="")

    def open_read(self, path: str):
        raise NotWritable("a list of files has no content of its own")


@dataclass
class ResultSet:
    title: str                  # what the tab and the address say: "Search: report in Photos (12 found)"
    origin: str                 # the real folder the search started in (the way up)
    entries: list = field(default_factory=list)
    criteria: object = None     # the search that made it, so it can be run again


class ResultStore:
    """The result lists of this session, by number."""

    def __init__(self, keep: int = MAX_STORED) -> None:
        self.keep = keep
        self._sets: dict = {}
        self._counter = itertools.count(1)

    def add(self, result: ResultSet) -> str:
        n = next(self._counter)
        self._sets[n] = result
        for old in sorted(self._sets)[:-self.keep]:
            del self._sets[old]
        return f"{FOUND_PREFIX}{n}"

    def get(self, path: str) -> Optional[ResultSet]:
        try:
            return self._sets.get(int(path[len(FOUND_PREFIX):]))
        except ValueError:
            return None

    def __len__(self) -> int:
        return len(self._sets)


class FoundFileSystem(FileSystem):
    """``found://<n>``: a stored result list, as a folder."""

    scheme = "found"
    writable = False

    def __init__(self, base: FileSystem, store: Optional[ResultStore] = None) -> None:
        self.base = base
        self.store = store or ResultStore()
        self.sep = base.sep
        self.case_sensitive = base.case_sensitive

    def _result(self, path: str) -> ResultSet:
        result = self.store.get(path)
        if result is None:
            raise FileNotFoundError(f"{path}: this result list is no longer kept")
        return result

    def join(self, base: str, *parts: str) -> str:
        return self.base.join(self._result(base).origin, *parts)

    def basename(self, path: str) -> str:
        result = self.store.get(path)
        return result.title if result else "Search result"

    def dirname(self, path: str) -> str:
        result = self.store.get(path)
        return result.origin if result else path

    def is_root(self, path: str) -> bool:
        return self.store.get(path) is None

    def parent(self, path: str) -> Optional[str]:
        result = self.store.get(path)
        return result.origin if result else None

    def list(self, path: str) -> list:
        """The stored entries that still exist (a refresh drops what was renamed, moved or deleted since)."""
        result = self._result(path)
        kept = []
        for e in result.entries:
            try:
                self.base.stat(e.path)
            except OSError:
                continue
            kept.append(e)
        return kept

    def scan(self, path: str):
        return iter(self.list(path))

    def stat(self, path: str) -> Entry:
        result = self._result(path)
        return Entry(name=result.title, path=path, is_dir=True, kind="")

    def open_read(self, path: str):
        raise NotWritable("a list of files has no content of its own")
