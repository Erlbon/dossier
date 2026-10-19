"""An archive (zip, 7z, RAR and more, see ``archives.py``) as a read-only folder tree.

A path is ``zip://<path of the archive>!/<path inside>``, for example ``zip://C:\\Data\\a.zip!/docs/x.txt``.
The archive root is ``zip://C:\\Data\\a.zip!/``; the folder above it is the folder holding the archive, so
the ``..`` row of a panel leads out of the archive.

The listing is read once per archive and kept until the archive changes on disk. No file handle is kept
open between reads, so the archive can be replaced or deleted while it is shown. Safety: entry names that
would climb out (``..``, absolute paths, drive letters) are left out, the number of entries is capped,
and an encrypted entry is reported, not guessed at.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from typing import BinaryIO, Iterator, Optional

from . import archives
from .vfs import Entry, FileSystem

MAX_ENTRIES = 1_000_000
CACHE_ARCHIVES = 8
SEP = "!/"


def is_archive(path: str) -> bool:
    """A local file that some reader can open as a folder (checked by content, not only by the name)."""
    try:
        return archives.backend_for(path) is not None
    except OSError:
        return False


def archive_root(path: str) -> str:
    return "zip://" + path + SEP


def _safe_parts(name: str) -> Optional[list]:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if ":" in parts[0] or name.startswith(("/", "\\")):
        return None
    return parts


class _Index:
    def __init__(self, stamp: tuple) -> None:
        self.stamp = stamp
        self.children: dict = {"": {}}          # folder -> {name: Entry}
        self.infos: dict = {}                   # inside path -> Member (files only)
        self.backend = None


class ZipFileSystem(FileSystem):
    writable = False
    scheme = "zip"
    case_sensitive = True

    def __init__(self) -> None:
        self._cache: dict = {}
        self._lock = threading.Lock()

    # paths ---------------------------------------------------------------------------------
    def split(self, path: str) -> tuple:
        """(archive, inside) where inside has no leading or trailing slash."""
        rest = path[len("zip://"):] if path.startswith("zip://") else path
        start = 0
        while True:
            at = rest.find(SEP, start)
            end_marker = at < 0 and rest.endswith("!")
            if at < 0 and not end_marker:
                break
            archive = rest[:at] if not end_marker else rest[:-1]
            if os.path.isfile(archive):
                inside = "" if end_marker else rest[at + len(SEP):]
                return archive, inside.strip("/")
            if end_marker:
                break
            start = at + 1
        raise FileNotFoundError(path)

    def _base(self, archive: str) -> str:
        return archive_root(archive)

    def join(self, base: str, *parts: str) -> str:
        out = base.rstrip("/")
        for part in parts:
            part = part.strip("/")
            if part:
                out = out + "/" + part
        return out

    def basename(self, path: str) -> str:
        archive, inside = self.split(path)
        return inside.rsplit("/", 1)[-1] if inside else os.path.basename(archive)

    def dirname(self, path: str) -> str:
        archive, inside = self.split(path)
        if "/" in inside:
            return self._base(archive) + inside.rsplit("/", 1)[0]
        return self._base(archive)

    def is_root(self, path: str) -> bool:
        return not self.split(path)[1]

    def parent(self, path: str) -> Optional[str]:
        archive, inside = self.split(path)
        if inside:
            return self.dirname(path)
        return os.path.dirname(archive) or None            # out of the archive, into its folder

    # reading -------------------------------------------------------------------------------
    def _index(self, archive: str) -> _Index:
        st = os.stat(archive)
        stamp = (st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._cache.get(archive)
            if hit is not None and hit.stamp == stamp:
                return hit
        backend = archives.backend_for(archive)
        if backend is None:
            raise OSError(archives.missing_reader(archive) or f"not a readable archive: {archive}")
        members = backend.members(archive)
        if len(members) > MAX_ENTRIES:
            raise OSError(f"the archive holds {len(members):,} entries; the limit is {MAX_ENTRIES:,}")
        index = _Index(stamp)
        index.backend = backend
        for member in members:
            self._add(index, archive, member)
        with self._lock:
            if len(self._cache) >= CACHE_ARCHIVES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[archive] = index
        return index

    def _add(self, index: _Index, archive: str, member) -> None:
        parts = _safe_parts(member.name)
        if parts is None:
            return
        is_dir = member.is_dir
        folder = ""
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            here = f"{folder}/{part}" if folder else part
            kids = index.children.setdefault(folder, {})
            if last and not is_dir:
                kids[part] = Entry(part, self._base(archive) + here, False, member.size, member.mtime)
                index.infos[here] = member
            else:
                if part not in kids or not kids[part].is_dir:
                    kids[part] = Entry(part, self._base(archive) + here, True)
                index.children.setdefault(here, {})
            folder = here

    def list(self, path: str) -> list:
        archive, inside = self.split(path)
        index = self._index(archive)
        kids = index.children.get(inside)
        if kids is None:
            raise NotADirectoryError(path) if inside in index.infos else FileNotFoundError(path)
        return list(kids.values())

    def scan(self, path: str) -> Iterator[Entry]:
        return iter(self.list(path))

    def stat(self, path: str) -> Entry:
        archive, inside = self.split(path)
        if not inside:
            return Entry(os.path.basename(archive), self._base(archive), True)
        index = self._index(archive)
        parent, _s, name = inside.rpartition("/")
        entry = index.children.get(parent, {}).get(name)
        if entry is None:
            raise FileNotFoundError(path)
        return entry

    def open_read(self, path: str) -> BinaryIO:
        archive, inside = self.split(path)
        index = self._index(archive)
        member = index.infos.get(inside)
        if member is None:
            raise IsADirectoryError(path) if inside in index.children else FileNotFoundError(path)
        if member.encrypted:
            raise PermissionError(f"{os.path.basename(inside)} is encrypted")
        return index.backend.open(archive, member)


# a local copy of one entry, for a program that needs a real file ---------------------------------
_temp_root: Optional[str] = None


def local_copy(fs: FileSystem, path: str) -> str:
    """Extract one item to a temporary folder and return its path. Cleaned up when the program ends."""
    global _temp_root
    if _temp_root is None:
        _temp_root = tempfile.mkdtemp(prefix="dossier-")
    folder = tempfile.mkdtemp(dir=_temp_root)
    target = os.path.join(folder, fs.basename(path))
    with fs.open_read(path) as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    return target


def clean_temp() -> None:
    global _temp_root
    if _temp_root:
        shutil.rmtree(_temp_root, ignore_errors=True)
        _temp_root = None


import atexit  # noqa: E402

atexit.register(clean_temp)
