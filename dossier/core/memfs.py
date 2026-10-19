"""A file system that lives in memory (paths like ``mem://music/a.mp3``).

It is the stand-in for every remote or virtual source: forward-slash paths on every platform, case
sensitive, nothing from the operating system. The operation planner, the undo log, the notes finder and the
selection are tested against it as well as against the real disk, so none of them can quietly depend on
``os.path`` or on Windows rules. Also useful for a pure unit test of anything that takes a ``FileSystem``.
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator, Optional

from .vfs import Entry, FileSystem


@dataclass
class _Node:
    is_dir: bool
    data: bytes = b""
    mtime: float = field(default_factory=time.time)


class _Writer(io.BytesIO):
    """A file being written: what was written is stored when it is closed."""

    def __init__(self, fs: "MemoryFileSystem", path: str) -> None:
        super().__init__()
        self._fs, self._path = fs, path

    def close(self) -> None:
        if not self.closed:
            self._fs._store(self._path, self.getvalue())
        super().close()


class MemoryFileSystem(FileSystem):
    scheme = "mem"
    writable = True

    def __init__(self) -> None:
        self._nodes: dict = {"": _Node(True)}                 # "" is the root folder

    # helpers for building a tree in a test ------------------------------------------------------------------
    def _key(self, path: str) -> str:
        _root, rest = self._split_root(path)
        return rest.strip("/")

    def put(self, path: str, data: bytes = b"", mtime: Optional[float] = None) -> str:
        """Create a file (and the folders above it)."""
        key = self._key(path)
        self._ensure_folders(key.rsplit("/", 1)[0] if "/" in key else "")
        self._nodes[key] = _Node(False, data, time.time() if mtime is None else mtime)
        return self.root + key

    def makedirs(self, path: str) -> str:
        self._ensure_folders(self._key(path))
        return self.root + self._key(path)

    def _ensure_folders(self, key: str) -> None:
        parts = [p for p in key.split("/") if p]
        for i in range(1, len(parts) + 1):
            k = "/".join(parts[:i])
            existing = self._nodes.get(k)
            if existing is None:
                self._nodes[k] = _Node(True)
            elif not existing.is_dir:
                raise NotADirectoryError(self.root + k)

    def _store(self, path: str, data: bytes) -> None:
        key = self._key(path)
        parent = key.rsplit("/", 1)[0] if "/" in key else ""
        if parent not in self._nodes or not self._nodes[parent].is_dir:
            raise FileNotFoundError(self.root + parent)
        self._nodes[key] = _Node(False, data, time.time())

    def _get(self, path: str) -> _Node:
        node = self._nodes.get(self._key(path))
        if node is None:
            raise FileNotFoundError(path)
        return node

    def _children(self, key: str) -> Iterator[str]:
        prefix = key + "/" if key else ""
        for k in self._nodes:
            if k and k.startswith(prefix) and "/" not in k[len(prefix):]:
                yield k

    # the FileSystem contract --------------------------------------------------------------------------------------
    def stat(self, path: str) -> Entry:
        node = self._get(path)
        return Entry(name=self.basename(path) or self.root, path=self.root + self._key(path), is_dir=node.is_dir,
                     size=0 if node.is_dir else len(node.data), mtime=node.mtime)

    def list(self, path: str) -> list:
        node = self._get(path)
        if not node.is_dir:
            raise NotADirectoryError(path)
        return [self.stat(self.root + k) for k in sorted(self._children(self._key(path)))]

    def open_read(self, path: str) -> BinaryIO:
        node = self._get(path)
        if node.is_dir:
            raise IsADirectoryError(path)
        return io.BytesIO(node.data)

    def mkdir(self, path: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        key = self._key(path)
        existing = self._nodes.get(key)
        if existing is not None:
            if existing.is_dir and exist_ok:
                return
            raise FileExistsError(path)
        parent = key.rsplit("/", 1)[0] if "/" in key else ""
        if parent not in self._nodes:
            if not parents:
                raise FileNotFoundError(self.root + parent)
            self._ensure_folders(parent)
        self._nodes[key] = _Node(True)

    def rename(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        s, d = self._key(src), self._key(dst)
        node = self._get(src)
        if d in self._nodes and not overwrite:
            raise FileExistsError(dst)
        parent = d.rsplit("/", 1)[0] if "/" in d else ""
        if parent not in self._nodes:
            raise FileNotFoundError(self.root + parent)
        if node.is_dir and (d == s or d.startswith(s + "/")):
            raise OSError("a folder cannot be moved into itself")
        moved = {k: v for k, v in self._nodes.items() if k == s or k.startswith(s + "/")}
        for k in moved:
            del self._nodes[k]
        for k, v in moved.items():
            self._nodes[d + k[len(s):]] = v

    def remove(self, path: str) -> None:
        key = self._key(path)
        node = self._get(path)
        if node.is_dir and any(True for _ in self._children(key)):
            raise OSError(f"folder not empty: {path}")
        if key == "":
            raise OSError("the root cannot be removed")
        del self._nodes[key]

    def open_write(self, path: str, *, exclusive: bool = False) -> BinaryIO:
        key = self._key(path)
        if key in self._nodes and (exclusive or self._nodes[key].is_dir):
            raise FileExistsError(path)
        parent = key.rsplit("/", 1)[0] if "/" in key else ""
        if parent not in self._nodes:
            raise FileNotFoundError(self.root + parent)
        return _Writer(self, path)

    def set_mtime(self, path: str, mtime: float) -> None:
        self._get(path).mtime = mtime
