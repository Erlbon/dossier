"""The Trash (the Recycle Bin on Windows) as a place: what is in it, Put Back, and Empty (card 46B, 2026-11-18).

Both systems keep a record beside each deleted item that says where it came from and when it was deleted, in a published or
well-known form that Dossier reads directly:
- **Linux** (the freedesktop Trash standard): ``~/.local/share/Trash`` for the home drive and ``<drive>/.Trash-<uid>`` (or
  ``<drive>/.Trash/<uid>``) for other drives; each has ``files/<name>`` and ``info/<name>.trashinfo`` with ``Path=`` (percent-encoded,
  relative to the drive for a drive's own trash) and ``DeletionDate=``.
- **Windows**: ``<drive>:\\$Recycle.Bin\\<the user's SID>\\``, with ``$I<id><ext>`` (version, size, deletion time, original path) beside
  ``$R<id><ext>``, the deleted item itself (``core/forensic.py`` shows the same records as a document).
- **The Mac** keeps the original place in Finder's own private records, and reading ``~/.Trash`` needs Full Disk Access, so the
  Trash place there opens Finder's Trash instead (``mac_open_command``), where Put Back works for everything.

Put Back is a plan of moves (made by the caller with ``put_back_plan``); afterwards ``forget_restored`` drops the records of what
moved. Emptying is permanent and asked about first by the window. Reading the bins touches the disk: call ``list_items`` on a thread.
"""
from __future__ import annotations

import os
import shutil
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import quote, unquote

from .platform import IS_MACOS, IS_WINDOWS, path_key

TRASH_URL = "trash://"
INFO_SUFFIX = ".trashinfo"
TITLE = "Recycle Bin" if IS_WINDOWS else "Trash"


def is_trash(path: str) -> bool:
    return path.rstrip("/") == "trash:"


@dataclass
class TrashItem:
    name: str              # the original name
    path: str              # the item as it is kept in the bin
    original: str          # where it came from (full path)
    deleted: float         # when, seconds since 1970 (0: unknown)
    size: int
    is_dir: bool
    record: str            # the record beside it (.trashinfo or $I)


@dataclass(frozen=True)
class Bin:
    folder: str            # Linux: the folder holding files/ and info/; Windows: the user's $Recycle.Bin folder
    top: str = ""          # Linux: the drive a drive's own trash belongs to (paths in it are relative to that); "" for the home trash
    kind: str = "xdg"      # xdg | windows


# finding the bins --------------------------------------------------------------------------------------------------------------
def xdg_bins(home: str, volumes: list, uid: int, environ: Optional[dict] = None, isdir: Callable = os.path.isdir,
             islink: Callable = os.path.islink) -> list:
    """The trash folders of the freedesktop standard that exist: the home trash, then each mounted drive's own."""
    env = os.environ if environ is None else environ
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    out = [Bin(os.path.join(data, "Trash"))] if isdir(os.path.join(data, "Trash")) else []
    for root, _label, kind in volumes:
        if root == "/" or kind == "network":
            continue
        shared = os.path.join(root, ".Trash")
        for folder, own in ((os.path.join(shared, str(uid)), False), (os.path.join(root, f".Trash-{uid}"), True)):
            if not own and islink(shared):
                continue                                      # the standard: a .Trash that is a link is not used
            if isdir(os.path.join(folder, "info")):
                out.append(Bin(folder, root))
    return out


def windows_bins(volumes: list, sid: str, isdir: Callable = os.path.isdir) -> list:
    """Each local drive's Recycle Bin folder of this user (network drives have none)."""
    out = []
    for root, _label, kind in volumes:
        if kind in ("fixed", "removable") and sid:
            folder = os.path.join(root, "$Recycle.Bin", sid)
            if isdir(folder):
                out.append(Bin(folder, root, "windows"))
    return out


def current_sid() -> str:
    """The Windows user's security id (``S-1-5-21-...``), which names their own folder in each Recycle Bin. Empty when it cannot
    be read."""
    if not IS_WINDOWS:
        return ""
    import ctypes
    from ctypes import wintypes
    try:
        advapi32, kernel32 = ctypes.WinDLL("advapi32"), ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):     # TOKEN_QUERY
            return ""
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))                      # TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                return ""
            sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
                return ""
            value = text.value
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            return value or ""
        finally:
            kernel32.CloseHandle(token)
    except (AttributeError, OSError, ctypes.ArgumentError):
        return ""


def system_bins() -> list:
    """This user's bins on this computer (none on the Mac, whose Trash belongs to Finder)."""
    from .platform import home_dir, list_volumes
    if IS_MACOS:
        return []
    if IS_WINDOWS:
        return windows_bins(list_volumes(), current_sid())
    return xdg_bins(home_dir(), list_volumes(), os.getuid())


def mac_open_command() -> list:
    """Opens the Trash in Finder, where Put Back works for everything (Dossier cannot read the Mac's records)."""
    return ["open", os.path.join(os.path.expanduser("~"), ".Trash")]


# reading them ------------------------------------------------------------------------------------------------------------------
def parse_trashinfo(text: str) -> tuple:
    """``(path, deletion time)`` from a ``.trashinfo`` record (path still as written: percent-encoded, maybe relative)."""
    path, when = "", 0.0
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            inside = line == "[Trash Info]"
            continue
        if not inside or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "Path" and not path:
            path = value.strip()
        elif key.strip() == "DeletionDate" and not when:
            try:
                when = datetime.strptime(value.strip()[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
            except ValueError:
                when = 0.0
    return path, when


def parse_recycle_record(data: bytes) -> tuple:
    """``(original path, size, deletion time)`` from a Windows ``$I`` record; raises ValueError when it is not one."""
    if len(data) < 28:
        raise ValueError("cut short")
    version, size, filetime = struct.unpack_from("<QQQ", data, 0)
    if version == 1:
        raw = data[24:24 + 520]
        original = raw.decode("utf-16-le", "replace").split(chr(0))[0]
    elif version == 2:
        count, = struct.unpack_from("<I", data, 24)
        original = data[28:28 + 2 * count].decode("utf-16-le", "replace").rstrip(chr(0))
    else:
        raise ValueError("not a Recycle Bin record")
    when = (filetime - 116444736000000000) / 10_000_000 if filetime else 0.0
    return original, size, max(when, 0.0)


def _size_of(path: str) -> int:
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def _xdg_items(b: Bin, cancel=None) -> list:
    info, files = os.path.join(b.folder, "info"), os.path.join(b.folder, "files")
    try:
        names = os.listdir(info)
    except OSError:
        return []
    out = []
    for record_name in names:
        if cancel is not None:
            cancel()
        if not record_name.endswith(INFO_SUFFIX):
            continue
        record = os.path.join(info, record_name)
        try:
            with open(record, encoding="utf-8", errors="replace") as f:
                written, when = parse_trashinfo(f.read(64 * 1024))
        except OSError:
            continue
        item = os.path.join(files, record_name[:-len(INFO_SUFFIX)])
        if not written or not os.path.lexists(item):
            continue
        original = unquote(written)
        if not original.startswith("/"):
            original = os.path.join(b.top or "/", original)
        is_dir = os.path.isdir(item) and not os.path.islink(item)
        out.append(TrashItem(os.path.basename(original.rstrip("/")) or original, item, original, when,
                             0 if is_dir else _size_of(item), is_dir, record))
    return out


def _windows_items(b: Bin, cancel=None) -> list:
    try:
        names = os.listdir(b.folder)
    except OSError:
        return []
    out = []
    for name in names:
        if cancel is not None:
            cancel()
        if not name.startswith("$I"):
            continue
        record = os.path.join(b.folder, name)
        item = os.path.join(b.folder, "$R" + name[2:])
        try:
            with open(record, "rb") as f:
                original, size, when = parse_recycle_record(f.read(64 * 1024))
        except (OSError, ValueError):
            continue
        if not os.path.lexists(item):
            continue
        is_dir = os.path.isdir(item)
        name_only = original.replace("/", chr(92)).rstrip(chr(92)).rsplit(chr(92), 1)[-1]
        out.append(TrashItem(name_only, item, original, when, size, is_dir, record))
    return out


def list_items(bins: list, cancel=None) -> list:
    """Everything in ``bins``, the most recently deleted first."""
    out = []
    for b in bins:
        out += _windows_items(b, cancel) if b.kind == "windows" else _xdg_items(b, cancel)
    out.sort(key=lambda i: -i.deleted)
    return out


def item_of(path: str, items: list) -> Optional[TrashItem]:
    key = path_key(path)
    return next((i for i in items if path_key(i.path) == key), None)


def in_a_bin(path: str) -> bool:
    """Whether ``path`` is kept in a bin (so deleting it there is for good)."""
    parts = path.replace(chr(92), "/").split("/")
    return "$Recycle.Bin" in parts or any(p == "Trash" and i + 1 < len(parts) and parts[i + 1] == "files" for i, p in enumerate(parts)) \
        or any(p.startswith(".Trash") for p in parts)


# putting back and emptying -------------------------------------------------------------------------------------------------------
def put_back_plan(fs, items: list):
    """One plan that moves each item back where it came from, making its folder again when it is gone. A place that is taken now
    is a conflict, asked about as in every plan."""
    from .ops import Kind, Plan, plan_move
    ops, warnings, blocking, skipped, made = [], [], [], [], set()
    for item in items:
        folder, name = os.path.split(item.original.rstrip("/" + chr(92)))
        part = plan_move(fs, [item.path], folder, make_dest=True, new_name=name)
        for op in part.ops:
            if op.kind is Kind.MKDIR:
                key = path_key(op.dst)
                if key in made:
                    continue
                made.add(key)
            ops.append(op)
        warnings += [w.replace(item.path, item.name) for w in part.warnings]
        blocking += [w.replace(item.path, item.name) for w in part.blocking]
        skipped += list(part.skipped)
    return Plan("Put back", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def forget_restored(items: list) -> int:
    """Drop the record of each item that is no longer in the bin (put back); returns how many."""
    count = 0
    for item in items:
        if not os.path.lexists(item.path):
            try:
                os.remove(item.record)
                count += 1
            except OSError:
                pass
    return count


def remove_for_good(items: list, cancel=None) -> tuple:
    """Delete ``items`` from the bin permanently, each with its record. Returns ``(removed, failed)``, ``failed`` as
    ``[(name, reason)]``."""
    removed, failed = 0, []
    for item in items:
        if cancel is not None:
            cancel()
        try:
            if item.is_dir:
                shutil.rmtree(item.path)
            elif os.path.lexists(item.path):
                os.remove(item.path)
            if os.path.lexists(item.record):
                os.remove(item.record)
            removed += 1
        except OSError as e:
            failed.append((item.name, e.strerror or str(e)))
    return removed, failed


def record_text(original: str, when: float, top: str = "") -> str:
    """A ``.trashinfo`` record (for tests and for the day Dossier writes its own)."""
    path = os.path.relpath(original, top) if top else original
    stamp = datetime.fromtimestamp(when).strftime("%Y-%m-%dT%H:%M:%S")
    return f"[Trash Info]\nPath={quote(path)}\nDeletionDate={stamp}\n"


# the place ---------------------------------------------------------------------------------------------------------------------
from .vfs import Entry, FileSystem, NotWritable          # noqa: E402 -- kept below: the record code above needs no file system


class TrashFileSystem(FileSystem):
    """``trash://`` as a read-only folder: each item by its original name, with the folder it came from (the Location column) and
    when it was deleted (the Date column). An item's path is where the bin keeps it, so viewing and copying out work as anywhere."""

    scheme = "trash"
    writable = False

    def __init__(self, base: FileSystem, bins: Optional[Callable[[], list]] = None) -> None:
        self.base = base
        self.bins = bins or system_bins
        self.sep = base.sep
        self.case_sensitive = base.case_sensitive
        self._items: list = []

    def items(self, fresh: bool = False) -> list:
        """What the last listing found (read again when ``fresh`` or not read yet)."""
        if fresh or not self._items:
            self._items = list_items(self.bins())
        return list(self._items)

    def is_root(self, path: str) -> bool:
        return True

    def parent(self, path: str) -> Optional[str]:
        return "home://"

    def basename(self, path: str) -> str:
        return TITLE

    def dirname(self, path: str) -> str:
        return "home://"

    def join(self, base: str, *parts: str) -> str:
        return self.base.join(*parts) if parts else base

    def list(self, path: str) -> list:
        if not is_trash(path):
            raise FileNotFoundError(path)
        return [Entry(name=i.name, path=i.path, is_dir=i.is_dir, size=i.size, mtime=i.deleted, kind="trash",
                      detail=os.path.dirname(i.original.rstrip("/" + chr(92))) or i.original)
                for i in self.items(fresh=True)]

    def scan(self, path: str):
        return iter(self.list(path))

    def stat(self, path: str) -> Entry:
        if not is_trash(path):
            raise FileNotFoundError(path)
        return Entry(name=TITLE, path=TRASH_URL, is_dir=True)

    def open_read(self, path: str):
        raise NotWritable("the Trash has no content of its own")
