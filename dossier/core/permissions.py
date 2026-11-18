"""Who may read, write and run a file (Mac and Linux): modes as text, the new mode for an item, a plan, and writing the plan.

Nothing here imports Qt. Properties asks for a change as two masks, ``on`` (bits to give) and ``off`` (bits to take away); a bit in
neither stays as it is, so a group of items that differ is only changed where the user touched a tick. The plan is a list of
``PermChange`` made on a thread; nothing is written until it is applied.

Rules the plan follows:
- Only the nine bits for owner, group and others change. Set-user-id, set-group-id and the sticky bit are never touched.
- Links are skipped (``chmod`` would follow them), never entered.
- With "also for everything inside", a folder found INSIDE keeps its own run (search) bits, whatever was asked, so it stays
  openable; the items the user chose themselves get exactly what was asked. A file inside gets run as asked.
- The owner of an item is never changed (that needs the administrator); the group can be set to one of the user's own groups.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from . import platform
from .progress import CancelToken, check

# the nine bits, in the order they are shown: (who, what, bit)
WHO = ("owner", "group", "others")
WHAT = ("read", "write", "run")
BITS = tuple((who, what, 0o400 >> (3 * i) >> j) for i, who in enumerate(WHO) for j, what in enumerate(WHAT))
ALL = 0o777
RUN_BITS = 0o111


def is_posix(posix: Optional[bool] = None) -> bool:
    """Whether permissions of this kind exist here. ``posix`` lets a test say so for the other systems."""
    return (not platform.IS_WINDOWS) if posix is None else posix


def bit_for(who: str, what: str) -> int:
    for w, t, bit in BITS:
        if w == who and t == what:
            return bit
    raise ValueError(f"no such permission: {who} {what}")


def format_mode(mode: int) -> str:
    """``rwxr-xr-x`` for the nine bits of ``mode``."""
    return "".join(c if mode & bit else "-" for c, (_w, _t, bit) in zip("rwx" * 3, BITS))


def parse_mode(text: str) -> int:
    """The nine bits of ``755`` (octal) or ``rwxr-xr-x``; raises ``ValueError`` for anything else."""
    text = text.strip()
    if len(text) == 9 and all(c in "rwx-" for c in text):
        mode = 0
        for c, expected, (_w, _t, bit) in zip(text, "rwx" * 3, BITS):
            if c == expected:
                mode |= bit
            elif c != "-":
                raise ValueError(f"not a mode: {text}")
        return mode
    if 1 <= len(text) <= 4 and all(c in "01234567" for c in text):
        return int(text, 8) & ALL
    raise ValueError(f"not a mode: {text}")


def new_mode(old: int, on: int, off: int, *, is_dir: bool = False, inside: bool = False) -> int:
    """The mode after giving the bits in ``on`` and taking away those in ``off`` (a bit in both is given). Special bits of ``old`` stay.
    A folder found inside a chosen folder (``inside``) keeps its run bits."""
    if is_dir and inside:
        on &= ~RUN_BITS
        off &= ~RUN_BITS
    on &= ALL
    off &= ALL & ~on
    return (old & ~ALL) | (((old & ALL) | on) & ~off)


@dataclass
class PermChange:
    path: str
    is_dir: bool
    old_mode: int = 0
    new_mode: int = 0
    old_gid: int = -1
    new_gid: int = -1                 # -1: the group stays
    problem: str = ""                 # why the item cannot be changed (it is then not written)

    @property
    def mode_changes(self) -> bool:
        return (self.old_mode & ALL) != (self.new_mode & ALL)

    @property
    def group_changes(self) -> bool:
        return self.new_gid != -1 and self.new_gid != self.old_gid

    @property
    def changes(self) -> bool:
        return not self.problem and (self.mode_changes or self.group_changes)


@dataclass
class Applied:
    done: int = 0
    failed: list = field(default_factory=list)       # (path, why)


def plan(paths: Iterable[str], on: int = 0, off: int = 0, gid: int = -1, *, recursive: bool = False,
         cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int], None]] = None,
         lstat: Callable = os.lstat, listdir: Callable = os.listdir) -> list:
    """What each item would become: the items given and, when ``recursive``, everything below the folders (links are skipped).
    An item that cannot be read carries ``problem``. ``lstat`` and ``listdir`` are seams for tests."""
    out: list = []
    stack = [(p, False) for p in list(paths)[::-1]]
    while stack:
        check(cancel)
        path, inside = stack.pop()
        try:
            st = lstat(path)
        except OSError as e:
            out.append(PermChange(path, False, problem=str(getattr(e, "strerror", None) or e)))
            continue
        if stat.S_ISLNK(st.st_mode):
            continue
        is_dir = stat.S_ISDIR(st.st_mode)
        out.append(PermChange(path, is_dir, st.st_mode, new_mode(st.st_mode, on, off, is_dir=is_dir, inside=inside),
                              getattr(st, "st_gid", -1), gid))
        if progress:
            progress(len(out))
        if recursive and is_dir:
            try:
                children = [os.path.join(path, n) for n in listdir(path)]
            except OSError as e:
                out[-1].problem = "the folder cannot be read: " + str(getattr(e, "strerror", None) or e)
                continue
            stack.extend((c, True) for c in reversed(children))
    return out


def _order(changes: list) -> list:
    """Parents before what is inside, so a folder that is being opened up is open when its contents are reached. A folder that loses its
    owner's run bit goes last, deepest first, so it is still open while its contents are done."""
    first, last = [], []
    for c in changes:
        if c.is_dir and (c.old_mode & 0o100) and not (c.new_mode & 0o100):
            last.append(c)
        else:
            first.append(c)
    last.sort(key=lambda c: -c.path.count(os.sep))
    return first + last


def apply(changes: Iterable[PermChange], cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int, int], None]] = None,
          chmod: Callable = os.chmod, chown: Optional[Callable] = None) -> Applied:
    """Write a plan. An item that fails is listed and the rest goes on."""
    chown = chown or getattr(os, "chown", None)
    items = _order([c for c in changes if c.changes])
    result = Applied()
    for n, c in enumerate(items, 1):
        check(cancel)
        try:
            if c.group_changes:
                chown(c.path, -1, c.new_gid)
            if c.mode_changes:
                chmod(c.path, (c.old_mode & ~ALL & 0o7777) | (c.new_mode & ALL))
            result.done += 1
        except OSError as e:
            result.failed.append((c.path, str(getattr(e, "strerror", None) or e)))
        if progress:
            progress(n, len(items))
    return result


# what the Properties tab shows ----------------------------------------------------------------------------------------------------------
@dataclass
class PermInfo:
    """The permissions of the chosen items, for the tab: per bit how many items have it, the owner and group names."""
    count: int = 0
    folders: int = 0                                 # how many of them are folders
    have: dict = field(default_factory=dict)         # bit -> number of items that have it
    owners: list = field(default_factory=list)       # distinct owner names
    groups: list = field(default_factory=list)       # distinct (gid, name)
    mine: list = field(default_factory=list)         # (gid, name) of the groups this user may give an item to

    def state(self, bit: int) -> int:
        """0 none have it, 2 every item has it, 1 some do."""
        n = self.have.get(bit, 0)
        return 0 if n == 0 else 2 if n == self.count else 1

    def mask(self, state: int) -> int:
        return sum(bit for _w, _t, bit in BITS if self.state(bit) == state)


def _user_name(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)


def _group_name(gid: int) -> str:
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except (ImportError, KeyError):
        return str(gid)


def read_info(paths: Iterable[str], lstat: Callable = os.lstat, user_name: Callable = _user_name, group_name: Callable = _group_name,
              my_groups: Optional[Iterable[int]] = None) -> Optional[PermInfo]:
    """The permissions of local items, or None when none can be read or one is a link (a link has no mode of its own)."""
    info = PermInfo()
    owners, groups = [], []
    for p in paths:
        try:
            st = lstat(p)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode):
            continue
        info.count += 1
        if stat.S_ISDIR(st.st_mode):
            info.folders += 1
        for _w, _t, bit in BITS:
            if st.st_mode & bit:
                info.have[bit] = info.have.get(bit, 0) + 1
        name = user_name(getattr(st, "st_uid", -1))
        if name not in owners:
            owners.append(name)
        g = (getattr(st, "st_gid", -1), group_name(getattr(st, "st_gid", -1)))
        if g not in groups:
            groups.append(g)
    if not info.count:
        return None
    info.owners, info.groups = owners, groups
    if my_groups is None:
        my_groups = []
        try:
            my_groups = [os.getegid(), *os.getgroups()]
        except AttributeError:
            pass
    seen = []
    for gid in my_groups:
        if gid not in [x[0] for x in seen]:
            seen.append((gid, group_name(gid)))
    info.mine = sorted(seen, key=lambda x: x[1].casefold())
    return info
