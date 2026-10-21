"""A catalogue on the web (OPDS book catalogue, Subsonic music server) shown as folders and files. Standard library only.

Both services give lists of things (feeds, artists, albums) and a download address for each file. ``CatalogClient`` turns that into the
calls ``SftpFileSystem`` already knows (``listdir``, ``stat``, ``open``, ``read_blocks``...), so the panels, the viewer, copy and search work
on a catalogue like on any folder. It is always read-only: every write is refused here whatever a command asks.

The web side (the connection, TLS with a pinned certificate, HTTP login, redirects, size limits) is ``DavClient``'s. A subclass says what the
top of the catalogue is (``_root``), what is inside a folder (``_children``) and where a file's bytes are (``_target``).

Names are made from titles: characters a file name cannot hold become ``_``, and two things with the same name get `` (2)``, `` (3)``.
"""
from __future__ import annotations

import errno
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .davclient import DavClient
from .sftp_proto import FAILURE, NO_SUCH_FILE, PERMISSION_DENIED, S_IFDIR, S_IFREG, WRITE_FLAG, Attrs, Name, SftpError, error_for

CACHE_SECONDS = 120
MAX_NAME = 120
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Node:
    kind: str                      # "dir" or "file"
    key: str                       # what the service needs to get it: a feed address, an id
    size: int = 0
    mtime: float = 0.0
    mime: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_dir(self) -> bool:
        return self.kind == "dir"


def safe_name(text: str, fallback: str = "untitled") -> str:
    """A title as a name a file or a folder can have."""
    name = BAD_CHARS.sub("_", " ".join(str(text or "").split())).strip(" .")
    return (name[:MAX_NAME].rstrip(" .") or fallback)


def unique_names(pairs: list) -> dict:
    """``{name: node}`` of ``[(wanted name, node)]``; the second of two equal names becomes ``name (2)`` (before the extension of a file)."""
    out: dict = {}
    for wanted, node in pairs:
        name, n = wanted, 1
        while name.lower() in {k.lower() for k in out}:
            n += 1
            stem, dot, ext = wanted.rpartition(".") if node.kind == "file" and "." in wanted else (wanted, "", "")
            name = f"{stem} ({n}){dot}{ext}"
        out[name] = node
    return out


class CatalogClient(DavClient):
    read_only = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.start = ""
        self._listings: dict = {}          # folder path -> (time, {name: Node})

    def set_start(self, start: str) -> None:
        """The path on the server where the catalogue begins (``/opds``, or the folder a music server lives in)."""
        start = (start or "").strip()
        self.start = "/" + start.strip("/") if start.strip("/") else ""

    # what a service says -------------------------------------------------------------------------------------------------------------
    def _root(self) -> Node:
        raise NotImplementedError

    def _children(self, node: Node) -> list:
        """``[(wanted name, Node)]`` inside a folder node."""
        raise NotImplementedError

    def _target(self, node: Node) -> str:
        """The request target (path and query) of a file's bytes."""
        raise NotImplementedError

    # the tree ---------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _clean(path: str) -> str:
        parts = [p for p in path.replace("\\", "/").split("/") if p and p != "."]
        return "/" + "/".join(parts)

    def _node(self, path: str) -> Node:
        path = self._clean(path)
        if path == "/":
            return self._root()
        parent, _slash, name = path.rpartition("/")
        kids = self._listing(parent or "/")
        node = kids.get(name)
        if node is None:                                          # file systems here are case-sensitive, a person's typing is not
            node = next((n for k, n in kids.items() if k.lower() == name.lower()), None)
        if node is None:
            raise error_for(NO_SUCH_FILE, "no such file", path)
        return node

    def _listing(self, path: str) -> dict:
        path = self._clean(path)
        cached = self._listings.get(path)
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        node = self._node(path)
        if not node.is_dir:
            raise error_for(NO_SUCH_FILE, "it is not a folder", path)
        kids = unique_names(self._children(node))
        self._listings[path] = (time.monotonic(), kids)
        return kids

    @staticmethod
    def _attrs(node: Node) -> Attrs:
        perm = (S_IFDIR | 0o555) if node.is_dir else (S_IFREG | 0o444)
        return Attrs(size=0 if node.is_dir else node.size, perm=perm, atime=int(node.mtime), mtime=int(node.mtime), flags=1 | 4 | 8)

    def connect(self) -> None:
        self._listings.clear()
        self._listing("/")

    def realpath(self, path: str) -> str:
        return "/" if path in (".", "") else self._clean(path)

    def stat(self, path: str, follow: bool = True) -> Attrs:
        node = self._node(path)
        if not node.is_dir and node.size <= 0:
            node.size = self._size_of(node)
        return self._attrs(node)

    def listdir(self, path: str) -> list:
        return [Name(name, "", self._attrs(node)) for name, node in self._listing(path).items()]

    def _size_of(self, node: Node) -> int:
        """A file whose size the catalogue did not give: ask the server (HEAD)."""
        try:
            reply = self.request("HEAD", self._target(node), quoted=True)
            length = reply.header("content-length")
            return int(length) if length.isdigit() else 0
        except (OSError, SftpError):
            return 0

    # nothing can be changed -----------------------------------------------------------------------------------------------------
    def _refuse(self, path: str):
        raise error_for(PERMISSION_DENIED, "a catalogue is read-only", path)

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        self._refuse(path)

    def rmdir(self, path: str) -> None:
        self._refuse(path)

    def remove(self, path: str) -> None:
        self._refuse(path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        self._refuse(old)

    def set_mtime(self, path: str, mtime: float) -> None:
        self._refuse(path)

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        self._refuse(path)

    def readlink(self, path: str) -> str:
        raise OSError(errno.EINVAL, "a catalogue has no links", path)

    # contents ---------------------------------------------------------------------------------------------------------------------
    def open(self, path: str, flags: int) -> bytes:
        if flags & WRITE_FLAG:
            self._refuse(path)
        node = self._node(path)
        if node.is_dir:
            raise error_for(NO_SUCH_FILE, "it is a folder", path)
        if node.size <= 0:
            node.size = self._size_of(node)
        with self._lock:
            self._next += 1
            handle = str(self._next).encode()
            self._handles[handle] = {"path": path, "temp": None, "size": node.size, "target": self._target(node), "whole": None}
        return handle

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        state = self._handles.get(handle)
        if state is None:
            raise error_for(FAILURE, "the file is not open", path)
        if state["whole"] is not None:                                 # the server sent everything at once the first time
            return state["whole"][offset:offset + count]
        size = state["size"]
        if size and offset >= size:
            return b""
        last = offset + count - 1 if not size else min(offset + count, size) - 1
        reply = self.request("GET", state["target"], headers={"Range": f"bytes={offset}-{last}"}, want=(200, 206, 416), quoted=True)
        if reply.status == 416:
            return b""
        if reply.status == 206:
            return reply.body
        state["whole"] = reply.body                                    # the server ignored the range: keep what it sent
        return reply.body[offset:offset + count]

    def close_handle(self, handle: bytes) -> None:
        self._handles.pop(handle, None)
