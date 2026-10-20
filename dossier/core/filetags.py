"""Tags, a rating, a colour label and a note kept on the file itself (docs/tags-plan.md): in an NTFS alternate data stream
``file:dossier`` on Windows, in the extended attribute ``user.dossier`` on Linux (with ``user.xdg.tags`` and
``user.baloo.rating`` alongside, the names other Linux tools read). No database and no sidecar file.

The record is one small JSON document. Keys this version does not know are kept when it writes, so a newer version never
loses what an older one saved. Writing never touches the file's own content, so its checksum does not change.

Everything here touches the disk: the window calls it on a thread. A backend (``StreamBackend``, ``XattrBackend``) does the
raw read and write, so the logic is tested with a fake one and the real ones are tested where the system has them.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from typing import Optional

STREAM = "dossier"
XATTR = "user.dossier"
XDG_TAGS = "user.xdg.tags"
BALOO_RATING = "user.baloo.rating"
MAX_BYTES = 64 * 1024
MAX_TAGS = 200
MAX_TAG_LENGTH = 100
MAX_NOTE = 8000
VERSION = 1


class CannotHoldTags(OSError):
    """The drive or file system under the path has no place to keep tags (FAT, exFAT, an archive...)."""


@dataclass
class Tags:
    tags: list = field(default_factory=list)
    rating: int = 0                       # 0 = none, 1-5
    label: str = ""                       # a colour name, free text up to 20 characters
    note: str = ""
    extra: dict = field(default_factory=dict)      # keys another version wrote: kept as they were

    def is_empty(self) -> bool:
        return not (self.tags or self.rating or self.label or self.note or self.extra)

    def has(self, tag: str) -> bool:
        return tag.casefold() in (t.casefold() for t in self.tags)


def clean_tags(tags) -> list:
    """Trimmed, no empties, no duplicates (case does not count; the first spelling stays), commas become spaces."""
    seen, out = set(), []
    for raw in tags or []:
        t = " ".join(str(raw).replace(",", " ").split())[:MAX_TAG_LENGTH]
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out[:MAX_TAGS]


def normalise(t: Tags) -> Tags:
    t.tags = clean_tags(t.tags)
    t.rating = max(0, min(5, int(t.rating or 0)))
    t.label = " ".join(str(t.label or "").split())[:20]
    t.note = str(t.note or "")[:MAX_NOTE]
    return t


def to_bytes(t: Tags) -> bytes:
    normalise(t)
    doc = dict(t.extra)
    doc["v"] = VERSION
    doc["tags"] = t.tags
    if t.rating:
        doc["rating"] = t.rating
    if t.label:
        doc["label"] = t.label
    if t.note:
        doc["note"] = t.note
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def from_bytes(data: bytes) -> Tags:
    """The record in ``data``; a damaged or foreign document gives empty tags, never an error."""
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return Tags()
    if not isinstance(doc, dict):
        return Tags()
    known = {"v", "tags", "rating", "label", "note"}
    tags = doc.get("tags")
    rating = doc.get("rating")
    return normalise(Tags(tags=tags if isinstance(tags, list) else [],
                          rating=rating if isinstance(rating, int) and not isinstance(rating, bool) else 0,
                          label=doc.get("label") if isinstance(doc.get("label"), str) else "",
                          note=doc.get("note") if isinstance(doc.get("note"), str) else "",
                          extra={k: v for k, v in doc.items() if k not in known}))


# backends --------------------------------------------------------------------------------------------------------
class StreamBackend:
    """NTFS alternate data streams (Windows)."""

    def can_hold(self, path: str) -> bool:
        """Whether the volume has named streams (a flag the file system reports): NTFS and ReFS yes, FAT and exFAT no."""
        import ctypes
        root = os.path.splitdrive(os.path.abspath(path))[0]
        if not root:
            return False
        flags = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root + chr(92), None, 0, None, None, ctypes.byref(flags), None, 0)
        return bool(ok) and bool(flags.value & 0x00040000)               # FILE_NAMED_STREAMS

    def read(self, path: str) -> Optional[bytes]:
        try:
            with open(f"{path}:{STREAM}", "rb") as f:
                return f.read(MAX_BYTES)
        except (FileNotFoundError, PermissionError, OSError):
            return None

    def write(self, path: str, data: bytes) -> None:
        with open(f"{path}:{STREAM}", "wb") as f:
            f.write(data)

    def remove(self, path: str) -> None:
        try:
            os.remove(f"{path}:{STREAM}")
        except FileNotFoundError:
            pass


class XattrBackend:
    """Extended attributes (Linux, and macOS where Python has them)."""

    def can_hold(self, path: str) -> bool:
        try:
            os.listxattr(path)
            return True
        except OSError:
            return False

    def read(self, path: str) -> Optional[bytes]:
        try:
            return os.getxattr(path, XATTR)[:MAX_BYTES]
        except OSError:
            return None

    def write(self, path: str, data: bytes) -> None:
        os.setxattr(path, XATTR, data)

    def remove(self, path: str) -> None:
        try:
            os.removexattr(path, XATTR)
        except OSError:
            pass

    # the names other tools read
    def read_xdg(self, path: str) -> list:
        try:
            raw = os.getxattr(path, XDG_TAGS).decode("utf-8", errors="replace")
        except OSError:
            return []
        return [p for p in raw.split(",") if p.strip()]

    def write_mirror(self, path: str, t: Tags) -> None:
        for name, value in ((XDG_TAGS, ",".join(t.tags).encode("utf-8")), (BALOO_RATING, str(t.rating * 2).encode())):
            try:
                if value and value != b"0":
                    os.setxattr(path, name, value)
                else:
                    os.removexattr(path, name)
            except OSError:
                pass


def default_backend():
    if sys.platform == "win32":
        return StreamBackend()
    return XattrBackend() if hasattr(os, "getxattr") else None


# operations ------------------------------------------------------------------------------------------------------
def can_hold_tags(path: str, backend=None) -> bool:
    backend = backend if backend is not None else default_backend()
    return backend is not None and backend.can_hold(path)


def read_tags(path: str, backend=None) -> Tags:
    """The tags of ``path`` (empty when there are none or it cannot hold any). Never raises."""
    backend = backend if backend is not None else default_backend()
    if backend is None:
        return Tags()
    try:
        data = backend.read(path)
        if data:
            return from_bytes(data)
        if hasattr(backend, "read_xdg"):                      # tags another Linux tool made
            return Tags(tags=clean_tags(backend.read_xdg(path)))
    except OSError:
        pass
    return Tags()


def write_tags(path: str, t: Tags, backend=None) -> None:
    """Save ``t`` on ``path``; an empty record removes the stream. Raises ``CannotHoldTags`` when the file system has no
    place for it, otherwise OSError (a file in use, denied). A read-only file is made writable for the moment of the write
    and put back, and the file's modified time is left exactly as it was."""
    backend = backend if backend is not None else default_backend()
    if backend is None or not backend.can_hold(path):
        raise CannotHoldTags(f"this drive cannot store tags: {path}")
    st = os.stat(path)
    readonly = not (st.st_mode & stat.S_IWRITE) and not os.path.isdir(path)
    if readonly:
        os.chmod(path, st.st_mode | stat.S_IWRITE)
    try:
        if t.is_empty():
            backend.remove(path)
        else:
            backend.write(path, to_bytes(t))
        if hasattr(backend, "write_mirror"):
            backend.write_mirror(path, normalise(t))
    finally:
        if readonly:
            os.chmod(path, st.st_mode)
        try:
            now = os.stat(path)
            if now.st_mtime_ns != st.st_mtime_ns:
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass


def edit_tags(path: str, add=(), remove=(), backend=None) -> Tags:
    """Add and remove tags on ``path``, leaving the rest of the record alone. Returns what was saved."""
    current = read_tags(path, backend)
    gone = {r.casefold() for r in remove}
    current.tags = clean_tags([t for t in current.tags if t.casefold() not in gone] + list(add))
    write_tags(path, current, backend)
    return current


def copy_tags(src: str, dst: str, source_backend=None, target_backend=None) -> str:
    """Carry the tags of ``src`` over to the copy ``dst`` (each side in the form its own drive holds). Returns ``"none"`` when
    the source has no tags, ``"copied"``, or ``"lost"`` when the destination cannot hold them or refuses. Never raises: a
    copy must not fail because its tags could not follow."""
    t = read_tags(src, source_backend)
    if t.is_empty():
        return "none"
    try:
        write_tags(dst, t, target_backend if target_backend is not None else source_backend)
    except OSError:
        return "lost"
    return "copied"
