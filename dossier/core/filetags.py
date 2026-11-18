"""Tags, a rating, a colour label and a note kept on the file itself (docs/tags-plan.md): in an NTFS alternate data stream
``file:dossier`` on Windows, in the extended attribute ``user.dossier`` on Linux (with ``user.xdg.tags`` and
``user.baloo.rating`` alongside, the names other Linux tools read), and on macOS in the same attribute with the tags
mirrored into Finder's own (``com.apple.metadata:_kMDItemUserTags``). No database and no sidecar file.

The record is one small JSON document. Keys this version does not know are kept when it writes, so a newer version never
loses what an older one saved. Writing never touches the file's own content, so its checksum does not change.

Everything here touches the disk: the window calls it on a thread. A backend (``StreamBackend``, ``XattrBackend``) does the
raw read and write, so the logic is tested with a fake one and the real ones are tested where the system has them.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from typing import Optional

from .platform import IS_MACOS, IS_WINDOWS

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
    """Extended attributes (Linux). The four raw calls are methods, so the Mac's backend can make them through the system
    library instead (Python on macOS has no ``os.getxattr``)."""

    def _get(self, path: str, name: str) -> bytes:
        return os.getxattr(path, name)

    def _set(self, path: str, name: str, value: bytes) -> None:
        os.setxattr(path, name, value)

    def _remove(self, path: str, name: str) -> None:
        os.removexattr(path, name)

    def _list(self, path: str) -> list:
        return os.listxattr(path)

    def can_hold(self, path: str) -> bool:
        try:
            self._list(path)
            return True
        except OSError:
            return False

    def read(self, path: str) -> Optional[bytes]:
        try:
            return self._get(path, XATTR)[:MAX_BYTES]
        except OSError:
            return None

    def write(self, path: str, data: bytes) -> None:
        self._set(path, XATTR, data)

    def remove(self, path: str) -> None:
        try:
            self._remove(path, XATTR)
        except OSError:
            pass

    def _put_or_drop(self, path: str, name: str, value: bytes) -> None:
        try:
            if value:
                self._set(path, name, value)
            else:
                self._remove(path, name)
        except OSError:
            pass

    # the names other tools read
    def read_xdg(self, path: str) -> list:
        try:
            raw = self._get(path, XDG_TAGS).decode("utf-8", errors="replace")
        except OSError:
            return []
        return [p for p in raw.split(",") if p.strip()]

    def write_mirror(self, path: str, t: Tags) -> None:
        self._put_or_drop(path, XDG_TAGS, ",".join(t.tags).encode("utf-8"))
        self._put_or_drop(path, BALOO_RATING, str(t.rating * 2).encode() if t.rating else b"")


FINDER_TAGS = "com.apple.metadata:_kMDItemUserTags"
# Finder's colours, by the number it stores after the tag's name ("Work\n4" is a blue tag named Work).
FINDER_COLOURS = {"gray": 1, "grey": 1, "green": 2, "purple": 3, "blue": 4, "yellow": 5, "red": 6, "orange": 7}


def finder_tags_from(data: bytes) -> list:
    """The tag names in Finder's attribute (a binary property list of ``"name\\ncolour"`` strings); bad data gives none."""
    import plistlib
    try:
        items = plistlib.loads(data)
    except Exception:                                 # plistlib raises several kinds on damaged data
        return []
    return [str(i).split("\n")[0] for i in items if isinstance(i, str) and i.split("\n")[0].strip()] if isinstance(items, list) else []


def finder_tags_bytes(t: Tags) -> bytes:
    """``t`` as Finder's attribute: each tag without a colour, and the colour label as Finder's own colour tag when it is one
    of Finder's seven ("Red", "Blue"...). Empty when there is nothing to show."""
    import plistlib
    items = [f"{tag}\n0" for tag in t.tags if tag.casefold() not in FINDER_COLOURS]
    colour = FINDER_COLOURS.get(t.label.casefold())
    if colour:
        items.append(f"{t.label.capitalize()}\n{colour}")
    return plistlib.dumps(items, fmt=plistlib.FMT_BINARY) if items else b""


class MacXattrBackend(XattrBackend):
    """Extended attributes on macOS, through the system library. The record lives in ``user.dossier`` as on Linux; the tags
    are mirrored into Finder's own tags, so they show (and can be searched) in Finder, and Finder's tags are read when a
    file has no record of Dossier's."""

    def __init__(self) -> None:
        import ctypes
        import ctypes.util
        self._ct = ctypes
        lib = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self._getxattr = lib.getxattr
        self._getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        self._getxattr.restype = ctypes.c_ssize_t
        self._setxattr = lib.setxattr
        self._setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        self._setxattr.restype = ctypes.c_int
        self._removexattr = lib.removexattr
        self._removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._removexattr.restype = ctypes.c_int
        self._listxattr = lib.listxattr
        self._listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self._listxattr.restype = ctypes.c_ssize_t

    def _fail(self, path: str):
        err = self._ct.get_errno()
        return OSError(err, os.strerror(err), path)

    def _get(self, path: str, name: str) -> bytes:
        p, n = os.fsencode(path), name.encode("utf-8")
        size = self._getxattr(p, n, None, 0, 0, 0)
        if size < 0:
            raise self._fail(path)
        buf = self._ct.create_string_buffer(max(size, 1))
        got = self._getxattr(p, n, buf, size, 0, 0)
        if got < 0:
            raise self._fail(path)
        return buf.raw[:got]

    def _set(self, path: str, name: str, value: bytes) -> None:
        if self._setxattr(os.fsencode(path), name.encode("utf-8"), value, len(value), 0, 0) != 0:
            raise self._fail(path)

    def _remove(self, path: str, name: str) -> None:
        if self._removexattr(os.fsencode(path), name.encode("utf-8"), 0) != 0:
            raise self._fail(path)

    def _list(self, path: str) -> list:
        size = self._listxattr(os.fsencode(path), None, 0, 0)
        if size < 0:
            raise self._fail(path)
        buf = self._ct.create_string_buffer(max(size, 1))
        got = self._listxattr(os.fsencode(path), buf, size, 0)
        if got < 0:
            raise self._fail(path)
        return [n.decode("utf-8", "replace") for n in buf.raw[:got].split(b"\0") if n]

    def read_xdg(self, path: str) -> list:
        try:
            return finder_tags_from(self._get(path, FINDER_TAGS))
        except OSError:
            return []

    def write_mirror(self, path: str, t: Tags) -> None:
        self._put_or_drop(path, FINDER_TAGS, finder_tags_bytes(t))


def default_backend():
    if IS_WINDOWS:
        return StreamBackend()
    if IS_MACOS:
        try:
            return MacXattrBackend()
        except (OSError, AttributeError, TypeError):
            return None
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


_SYSTEM_ATTRIBUTES = ("system.", "security.", "trusted.", "com.apple.rootless")


def copy_attributes(src: str, dst: str, backend) -> bool:
    """Copy every extended attribute of ``src`` onto ``dst`` as it is (the system's own, such as access lists and SELinux labels,
    are left to the system). True when each one was copied, False when one could not be (the destination cannot hold them)."""
    try:
        names = backend._list(src)
    except OSError:
        return False
    whole = True
    for name in names:
        if name.startswith(_SYSTEM_ATTRIBUTES):
            continue
        try:
            backend._set(dst, name, backend._get(src, name))
        except OSError:
            whole = False
    return whole


def copy_tags(src: str, dst: str, source_backend=None, target_backend=None) -> str:
    """Carry the tags of ``src`` over to the copy ``dst`` (each side in the form its own drive holds). Returns ``"none"`` when
    the source has no tags, ``"copied"``, or ``"lost"`` when the destination cannot hold them or refuses. Never raises: a
    copy must not fail because its tags could not follow.

    Off Windows, with the system's own backend, every extended attribute of the file is copied as it is first (the copy itself
    carries none on the Mac or Linux): Finder's tags with their colours, "where from", the desktop's own tags. Only when that
    fails is the record rewritten from what was read."""
    if source_backend is None and target_backend is None:
        backend = default_backend()
        if isinstance(backend, XattrBackend) and copy_attributes(src, dst, backend):
            return "copied" if not read_tags(src, backend).is_empty() else "none"
    t = read_tags(src, source_backend)
    if t.is_empty():
        return "none"
    try:
        write_tags(dst, t, target_backend if target_backend is not None else source_backend)
    except OSError:
        return "lost"
    return "copied"


@dataclass
class TagChange:
    """What the Properties dialog asks to change. ``None`` means "leave as it is" (so several files can be edited at once
    without touching a field nobody changed)."""
    replace: Optional[list] = None        # the full list of tags (one file)
    add: list = field(default_factory=list)
    remove: list = field(default_factory=list)
    rating: Optional[int] = None
    label: Optional[str] = None
    note: Optional[str] = None

    def is_empty(self) -> bool:
        return (self.replace is None and not self.add and not self.remove and self.rating is None and self.label is None
                and self.note is None)


def apply_change(path: str, change: TagChange, backend=None) -> Tags:
    """Apply ``change`` to the tags of ``path`` and save them. Raises ``CannotHoldTags`` or OSError like ``write_tags``."""
    t = read_tags(path, backend)
    if change.replace is not None:
        t.tags = clean_tags(change.replace)
    if change.remove:
        gone = {r.casefold() for r in change.remove}
        t.tags = [x for x in t.tags if x.casefold() not in gone]
    if change.add:
        t.tags = clean_tags(list(t.tags) + list(change.add))
    if change.rating is not None:
        t.rating = change.rating
    if change.label is not None:
        t.label = change.label
    if change.note is not None:
        t.note = change.note
    write_tags(path, t, backend)
    return normalise(t)
