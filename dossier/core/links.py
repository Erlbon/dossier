"""Symbolic links, junctions and hard links: what a path is, where it points, and making new ones. Qt-free; local disks only.

Three kinds, and they are not the same:

* **symlink**: a small file that holds a path. It can point at a file or a folder, anywhere, even at something that is not there
  (then it is *broken*). On Windows making one needs Developer Mode or an administrator.
* **junction** (Windows only): a folder that shows another folder of the same computer. Needs no special right. Deleting it
  removes only the junction, never what it shows (Dossier's delete already works like that).
* **hard link**: a second name for the *same file* on the *same drive*. Both names are equal; the data goes when the last name does.
  It cannot be made for a folder.

Nothing here deletes or overwrites: a link is only made where nothing exists.
"""
from __future__ import annotations

import ctypes
import errno
import os
import stat
from dataclasses import dataclass, field
from typing import Optional

from .platform import IS_WINDOWS, strip_longpath

SYMLINK, JUNCTION, HARDLINK = "symlink", "junction", "hardlink"
KINDS = (SYMLINK, JUNCTION, HARDLINK)
KIND_NAMES = {SYMLINK: "Symbolic link", JUNCTION: "Junction", HARDLINK: "Hard link"}
MAX_NAMES = 50
_ERROR_PRIVILEGE_NOT_HELD = 1314


class LinkError(Exception):
    """A link that cannot be made, or read, with a reason in plain words."""


@dataclass
class LinkInfo:
    kind: str = ""                 # symlink | junction | "" (an ordinary file or folder)
    target: str = ""               # what a symlink or junction points at, as stored
    broken: bool = False           # the target is not there
    hardlinks: int = 1             # names this file has (1 = only this one); files only
    other_names: list = field(default_factory=list)   # the other names of a hard-linked file, where the system can tell (Windows)

    @property
    def is_link(self) -> bool:
        return bool(self.kind)


def _is_junction(path: str, st) -> bool:
    check = getattr(os.path, "isjunction", None)
    if check is not None:
        return check(path)
    return IS_WINDOWS and bool(getattr(st, "st_file_attributes", 0) & 0x400) and not stat.S_ISLNK(st.st_mode)


def inspect(path: str) -> LinkInfo:
    """What ``path`` is. Never raises: a path that cannot be read is an ordinary item."""
    try:
        st = os.lstat(path)
    except OSError:
        return LinkInfo()
    info = LinkInfo()
    if stat.S_ISLNK(st.st_mode) or _is_junction(path, st):
        info.kind = SYMLINK if stat.S_ISLNK(st.st_mode) else JUNCTION
        try:
            info.target = strip_longpath(os.readlink(path))
        except OSError:
            info.target = ""
        shown = info.target if os.path.isabs(info.target) else os.path.join(os.path.dirname(path), info.target)
        info.broken = not os.path.exists(path) or (bool(info.target) and not os.path.lexists(shown))
    elif stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
        info.hardlinks = st.st_nlink
        info.other_names = _other_names(path)
    return info


def _other_names(path: str) -> list:
    """The other names of a hard-linked file. Windows can list them; elsewhere finding them means searching the whole drive, so no."""
    if not IS_WINDOWS:
        return []
    kernel = ctypes.windll.kernel32                                    # type: ignore[attr-defined]
    kernel.FindFirstFileNameW.restype = ctypes.c_void_p
    names: list = []
    length = ctypes.c_ulong(1024)
    buf = ctypes.create_unicode_buffer(1024)
    handle = kernel.FindFirstFileNameW(ctypes.c_wchar_p(path), 0, ctypes.byref(length), buf)
    if handle in (None, ctypes.c_void_p(-1).value):
        return []
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        while True:
            names.append(drive + buf.value)
            length = ctypes.c_ulong(1024)
            if len(names) >= MAX_NAMES or not kernel.FindNextFileNameW(ctypes.c_void_p(handle), ctypes.byref(length), buf):
                break
    finally:
        kernel.FindClose(ctypes.c_void_p(handle))
    me = os.path.normcase(os.path.abspath(path))
    return [n for n in names if os.path.normcase(os.path.abspath(n)) != me]


def default_link_name(target: str, kind: str, is_dir: Optional[bool] = None) -> str:
    """A name for a new link to ``target``: ``name - link`` (a hard link keeps the extension). ``is_dir`` spares a look at the disk."""
    base = os.path.basename(target.rstrip("/\\")) or "link"
    if is_dir is None:
        is_dir = os.path.isdir(target)
    stem, ext = os.path.splitext(base) if kind == HARDLINK and not is_dir else (base, "")
    return f"{stem} - link{ext}"


def check(kind: str, target: str, link: str) -> None:
    """Raise ``LinkError`` with the reason if ``link`` cannot be made as ``kind`` pointing at ``target``."""
    if kind not in KINDS:
        raise LinkError(f"unknown kind of link: {kind}")
    if not os.path.lexists(target):
        raise LinkError("the item to link to does not exist")
    if os.path.lexists(link):
        raise LinkError("something with that name is already there; nothing is replaced")
    parent = os.path.dirname(os.path.abspath(link))
    if not os.path.isdir(parent):
        raise LinkError("the folder for the link does not exist")
    same = os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(link))
    if same:
        raise LinkError("a link cannot point at itself")
    if kind == JUNCTION:
        if not IS_WINDOWS:
            raise LinkError("junctions exist only on Windows; use a symbolic link")
        if not os.path.isdir(target):
            raise LinkError("a junction can only show a folder; use a symbolic link or a hard link for a file")
    if kind == HARDLINK:
        if os.path.isdir(target):
            raise LinkError("a hard link cannot be made for a folder; use a junction or a symbolic link")
        if os.path.islink(target):
            raise LinkError("a hard link to a symbolic link is not supported; link the file it points at")
        if _drive(target) != _drive(parent):
            raise LinkError("a hard link must be on the same drive as the file; use a symbolic link instead")


def _drive(path: str) -> str:
    drive = os.path.splitdrive(os.path.abspath(path))[0].lower()
    if drive:
        return drive
    try:
        return str(os.stat(path).st_dev)
    except OSError:
        return ""


def create(kind: str, target: str, link: str, *, relative: bool = False) -> None:
    """Make ``link`` as a ``kind`` of link to ``target``. ``relative``: a symbolic link stores the path from its own folder, so it keeps
    working when both are moved together. Raises ``LinkError``; nothing exists afterwards if it fails."""
    check(kind, target, link)
    try:
        if kind == SYMLINK:
            stored = os.path.relpath(target, os.path.dirname(os.path.abspath(link))) if relative else os.path.abspath(target)
            os.symlink(stored, link, target_is_directory=os.path.isdir(target))
        elif kind == JUNCTION:
            import _winapi                                                  # Windows only: checked above
            _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))
        else:
            os.link(target, link)
    except OSError as e:
        if getattr(e, "winerror", 0) == _ERROR_PRIVILEGE_NOT_HELD:
            raise LinkError("Windows lets only an administrator make symbolic links unless Developer Mode is on "
                            "(Settings > System > For developers). A junction (folders) or a hard link (files) needs no special right.") from e
        if e.errno == errno.EXDEV:
            raise LinkError("a hard link must be on the same drive as the file") from e
        if e.errno in (errno.EPERM, errno.EACCES):
            raise LinkError("this drive or folder does not allow that kind of link (FAT, exFAT and many network drives cannot)") from e
        raise LinkError(str(e.strerror or e)) from e
    except ValueError as e:                                                 # relpath across drives on Windows
        raise LinkError("a relative link cannot reach another drive; make an absolute one") from e


def what_is(info: LinkInfo) -> str:
    """One line for a window or a command: what the item is and, for a link, where it goes."""
    if info.kind:
        text = f"{KIND_NAMES[info.kind]} to {info.target}" if info.target else KIND_NAMES[info.kind]
        return text + (" (broken: the target is not there)" if info.broken else "")
    if info.hardlinks > 1:
        return f"Hard link: this file has {info.hardlinks} names" + (f" (also {', '.join(info.other_names)})" if info.other_names else "")
    return ""
