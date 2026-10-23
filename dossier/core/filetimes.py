"""Change the dates and attributes of files and folders, one by one or many at once. Qt-free; local disks only.

The window and the command line first ask for a *plan* (``plan_times``, ``plan_flags``): for every item what it is now and what it
would become. Nothing is written until ``apply`` is given the plan, so the owner sees the result first. A change has no undo (the plan
shows the old values, and ``restore_plan`` makes a plan that puts them back), because the same dates are not found anywhere else.

Dates: *modified*, *accessed* and *created*. Windows can set all three. Other systems keep no creation date that a program may set, so
there *created* is only ever read (``CAN_SET_CREATED``). A rule says where the new date comes from: a given moment, a shift by some
time, another item's date, or the date a photo was taken. Attributes (Windows): read-only, hidden, system, archive; elsewhere only
read-only, which is the write permission.
"""
from __future__ import annotations

import ctypes
import os
import stat
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Iterable, Optional

from .platform import IS_WINDOWS, has_scheme
from .progress import CancelToken, check

FIELDS = ("modified", "accessed", "created")
CAN_SET_CREATED = IS_WINDOWS
FLAGS = ("readonly", "hidden", "system", "archive")
_FLAG_BITS = {"readonly": 0x1, "hidden": 0x2, "system": 0x4, "archive": 0x20}
_EPOCH_DELTA = 11644473600                           # seconds from 1601 (Windows) to 1970
SET, SHIFT, FROM_FILE, FROM_EXIF, COPY_FIELD = "set", "shift", "from_file", "from_exif", "copy_field"


class TimeError(Exception):
    """A date or attribute that cannot be changed, with the reason."""


@dataclass(frozen=True)
class Times:
    modified: float = 0.0
    accessed: float = 0.0
    created: float = 0.0                             # 0 = unknown


@dataclass(frozen=True)
class Rule:
    kind: str                                        # set | shift | from_file | from_exif | copy_field
    when: float = 0.0                                # set: the moment (seconds since 1970)
    seconds: float = 0.0                             # shift: later (+) or earlier (-)
    source: str = ""                                 # from_file: the item whose date is taken
    source_field: str = "modified"                   # from_file and copy_field: which of its dates


@dataclass(frozen=True)
class Change:
    path: str
    is_dir: bool
    old: Times
    new: Times                                       # a date that stays is equal to the old one
    old_flags: tuple = ()                            # the flags that are on now
    new_flags: tuple = ()
    problem: str = ""                                # why this item is left out (the plan shows it, ``apply`` skips it)

    @property
    def dates_change(self) -> bool:
        return any(getattr(self.new, f) != getattr(self.old, f) for f in FIELDS)

    @property
    def flags_change(self) -> bool:
        return set(self.new_flags) != set(self.old_flags)

    @property
    def changes(self) -> bool:
        return not self.problem and (self.dates_change or self.flags_change)


@dataclass
class Applied:
    done: int = 0
    failed: list = field(default_factory=list)       # (path, reason)


# reading -------------------------------------------------------------------------------------------------------------------------------
def read_times(path: str) -> Times:
    """The dates of the item itself (a link is not followed). Raises ``OSError``."""
    st = os.lstat(path)
    created = getattr(st, "st_birthtime", 0.0) or (st.st_ctime if IS_WINDOWS else 0.0)
    return Times(st.st_mtime, st.st_atime, created)


def read_flags(path: str) -> tuple:
    """The attributes that are on, from ``FLAGS``."""
    st = os.lstat(path)
    bits = getattr(st, "st_file_attributes", None)
    if bits is not None:
        return tuple(name for name, bit in _FLAG_BITS.items() if bits & bit)
    return () if st.st_mode & stat.S_IWUSR else ("readonly",)


def supported_flags() -> tuple:
    return FLAGS if IS_WINDOWS else ("readonly",)


# writing -------------------------------------------------------------------------------------------------------------------------------
def _filetime(ts: float) -> ctypes.c_ulonglong:
    return ctypes.c_ulonglong(int((ts + _EPOCH_DELTA) * 10_000_000))


def set_times(path: str, *, modified: Optional[float] = None, accessed: Optional[float] = None, created: Optional[float] = None) -> None:
    """Set the dates that are given (None = leave). Works on read-only files and on folders; a link gets its own dates, its target is
    not touched. Raises ``TimeError`` or ``OSError``."""
    if created is not None and not CAN_SET_CREATED:
        raise TimeError("this system has no creation date that a program can set")
    if modified is None and accessed is None and created is None:
        return
    if IS_WINDOWS:
        _set_times_windows(path, modified, accessed, created)
        return
    now = read_times(path)
    os.utime(path, (now.accessed if accessed is None else accessed, now.modified if modified is None else modified), follow_symlinks=False)


def _set_times_windows(path: str, modified, accessed, created) -> None:
    kernel = ctypes.windll.kernel32                                    # type: ignore[attr-defined]
    kernel.CreateFileW.restype = ctypes.c_void_p
    full = os.path.abspath(path)
    if not full.startswith("\\\\?\\"):
        full = "\\\\?\\" + full if not full.startswith("\\\\") else "\\\\?\\UNC\\" + full[2:]
    # FILE_WRITE_ATTRIBUTES needs no write access to the data, so a read-only file works; backup semantics lets a folder be opened,
    # and not following the reparse point means a link's own dates are set
    handle = kernel.CreateFileW(ctypes.c_wchar_p(full), 0x100, 7, None, 3, 0x02000000 | 0x00200000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError()                                         # type: ignore[attr-defined]
    try:
        c = None if created is None else _filetime(created)
        a = None if accessed is None else _filetime(accessed)
        m = None if modified is None else _filetime(modified)
        ref = lambda v: None if v is None else ctypes.byref(v)         # noqa: E731
        if not kernel.SetFileTime(ctypes.c_void_p(handle), ref(c), ref(a), ref(m)):
            raise ctypes.WinError()                                     # type: ignore[attr-defined]
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def set_flags(path: str, on: Iterable[str]) -> None:
    """Make exactly the attributes in ``on`` (from ``supported_flags()``) the ones that are set. Other attributes stay."""
    on = set(on)
    if IS_WINDOWS:
        kernel = ctypes.windll.kernel32                                # type: ignore[attr-defined]
        now = os.lstat(path).st_file_attributes                        # type: ignore[attr-defined]
        bits = now
        for name, bit in _FLAG_BITS.items():
            bits = (bits | bit) if name in on else (bits & ~bit)
        bits &= ~0x80                                                  # "normal" cannot be combined with others
        if bits == 0:
            bits = 0x80
        if bits != now and not kernel.SetFileAttributesW(ctypes.c_wchar_p(os.path.abspath(path)), bits):
            raise ctypes.WinError()                                    # type: ignore[attr-defined]
        return
    if os.path.islink(path):
        raise TimeError("the attributes of a symbolic link cannot be changed here")
    mode = os.lstat(path).st_mode
    os.chmod(path, (mode & ~0o222) if "readonly" in on else (mode | stat.S_IWUSR))


# planning ------------------------------------------------------------------------------------------------------------------------------
def parse_exif_date(text: str) -> Optional[float]:
    """``2019:07:14 16:02:33`` (how a photo stores it) as local seconds since 1970, or None."""
    try:
        return datetime.strptime(text.strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _source_value(rule: Rule, path: str, old: Times, cache: dict) -> float:
    """The new moment for one item under ``rule``; raises ``TimeError`` when the item has no such date."""
    if rule.kind == SET:
        return rule.when
    if rule.kind == SHIFT:
        return -1.0                                                     # the caller shifts each date by itself
    if rule.kind == COPY_FIELD:
        return getattr(old, rule.source_field)
    if rule.kind == FROM_FILE:
        if rule.source not in cache:
            cache[rule.source] = read_times(rule.source)
        return getattr(cache[rule.source], rule.source_field)
    if rule.kind == FROM_EXIF:
        from .exif import read_exif
        exif = read_exif(path)
        found = parse_exif_date(exif.get("Date taken") or exif.get("Date digitized"))
        if found is None:
            raise TimeError("no date taken in this file")
        return found
    raise TimeError(f"unknown rule: {rule.kind}")


def _walk(paths: Iterable[str], recursive: bool, cancel: Optional[CancelToken]):
    """``(path, is_dir)`` for every item: the ones given and, when ``recursive``, everything below the folders. Links are listed, never entered."""
    stack = list(paths)[::-1]
    while stack:
        check(cancel)
        path = stack.pop()
        try:
            st = os.lstat(path)
        except OSError:
            yield path, False
            continue
        is_dir = stat.S_ISDIR(st.st_mode) and not os.path.islink(path)
        yield path, is_dir
        if recursive and is_dir:
            try:
                with os.scandir(path) as it:
                    children = [os.path.join(path, e.name) for e in it]
            except OSError:
                continue
            stack.extend(reversed(children))


def plan_times(paths: Iterable[str], rule: Rule, which: Iterable[str], *, recursive: bool = False, include_folders: bool = True,
               cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int], None]] = None) -> list:
    """What each item's dates would become. ``which`` names the dates to change; the others stay. An item that cannot be changed carries
    a ``problem`` instead of new dates."""
    which = tuple(w for w in which if w in FIELDS)
    if not which:
        raise TimeError("no date chosen to change")
    if "created" in which and not CAN_SET_CREATED:
        raise TimeError("this system has no creation date that a program can set")
    out: list = []
    cache: dict = {}
    for path, is_dir in _walk(paths, recursive, cancel):
        if has_scheme(path):
            out.append(Change(path, is_dir, Times(), Times(), problem="only items on a drive of this computer can be changed"))
            continue
        if is_dir and not include_folders:
            continue
        old = Times()
        try:
            old = read_times(path)
            new = old
            for name in which:
                if rule.kind == SHIFT:
                    value = getattr(old, name) + rule.seconds
                else:
                    value = _source_value(rule, path, old, cache)
                new = replace(new, **{name: value})
            out.append(Change(path, is_dir, old, new))
        except TimeError as e:
            out.append(Change(path, is_dir, old, Times(), problem=str(e)))
        except OSError as e:
            out.append(Change(path, is_dir, Times(), Times(), problem=str(e.strerror or e)))
        if progress and len(out) % 200 == 0:
            progress(len(out))
    return out


def plan_flags(paths: Iterable[str], *, set_on: Iterable[str] = (), set_off: Iterable[str] = (), recursive: bool = False,
               include_folders: bool = True, cancel: Optional[CancelToken] = None) -> list:
    """What each item's attributes would become: those in ``set_on`` are switched on, those in ``set_off`` off, the rest stay."""
    on, off = set(set_on), set(set_off)
    unknown = (on | off) - set(supported_flags())
    if unknown:
        raise TimeError("this system cannot set: " + ", ".join(sorted(unknown)))
    out: list = []
    for path, is_dir in _walk(paths, recursive, cancel):
        if is_dir and not include_folders:
            continue
        try:
            now = read_flags(path)
            new = tuple(f for f in FLAGS if (f in now or f in on) and f not in off)
            out.append(Change(path, is_dir, Times(), Times(), old_flags=now, new_flags=new))
        except OSError as e:
            out.append(Change(path, is_dir, Times(), Times(), problem=str(e.strerror or e)))
    return out


def restore_plan(changes: Iterable[Change]) -> list:
    """The plan that puts the old values back (what was planned, reversed)."""
    return [Change(c.path, c.is_dir, c.new, c.old, c.new_flags, c.old_flags) for c in changes if not c.problem]


# applying ------------------------------------------------------------------------------------------------------------------------------
def apply(changes: Iterable[Change], cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int, int], None]] = None) -> Applied:
    """Write a plan. An item that fails is listed and the rest goes on. Folders are done after what is inside them, so writing a file
    never moves the date of a folder that was already set."""
    items = [c for c in changes if c.changes]
    items.sort(key=lambda c: (c.is_dir, -c.path.count(os.sep)))
    result = Applied()
    for n, c in enumerate(items, 1):
        check(cancel)
        try:
            if c.dates_change:
                set_times(c.path, **{f: getattr(c.new, f) for f in FIELDS if getattr(c.new, f) != getattr(c.old, f)})
            if c.flags_change:
                set_flags(c.path, c.new_flags)
            result.done += 1
        except (OSError, TimeError) as e:
            result.failed.append((c.path, str(getattr(e, "strerror", None) or e)))
        if progress:
            progress(n, len(items))
    return result
