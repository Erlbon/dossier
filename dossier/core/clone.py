"""Replace duplicate files with clones (card 66B): the copy keeps its name, place, dates and attributes but shares the data blocks
with the one that is kept, so the space comes back. A later change to one copy changes only that copy (copy-on-write).

Only where the file system has clones: APFS (the Mac), btrfs and XFS (Linux), ReFS (Windows). NTFS has none. No hard links, ever.
Nothing is deleted: a copy is replaced atomically by a clone made beside it, after the two files were read and found identical.
Qt-free; the system calls live in ``platform``.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import platform
from .progress import Cancelled, CancelToken

CLONE_FILESYSTEMS = ("apfs", "btrfs", "xfs", "refs")
CHUNK = 1024 * 1024


class CloneError(OSError):
    """A copy could not be replaced; the copy is untouched."""


def is_clone_filesystem(name: str) -> bool:
    return (name or "").lower() in CLONE_FILESYSTEMS


def filesystem_of(path: str) -> str:
    return platform.filesystem_name(path)


def supports_clone(path: str, fstype: Optional[Callable[[str], str]] = None) -> bool:
    """Whether the volume holding ``path`` can clone files. ``fstype`` replaces the system's answer (for tests)."""
    return is_clone_filesystem((fstype or filesystem_of)(path))


def not_supported_reason(name: str) -> str:
    what = f"This volume uses {name.upper()}, which" if name else "This volume's file system"
    return (f"{what} cannot share space between files. Clones need APFS (Mac), btrfs or XFS (Linux), or ReFS (Windows); "
            "NTFS has none.")


def clone_file(src: str, dst: str) -> None:
    """Make ``dst`` (it must not exist) a clone of ``src``. Raises ``CloneError`` when the file system cannot."""
    try:
        platform.clone_native(src, dst)
    except OSError as e:
        raise CloneError(e.errno, f"The file system could not clone this file ({e.strerror or e})", dst) from e


def files_identical(a: str, b: str) -> bool:
    """Byte for byte, read from the disk now."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x = fa.read(CHUNK)
                if x != fb.read(CHUNK):
                    return False
                if not x:
                    return True
    except OSError:
        return False


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _copy_owner(src: str, dst: str) -> None:
    chown = getattr(os, "chown", None)
    if chown is None:
        return
    try:
        st = os.stat(src)
        chown(dst, st.st_uid, st.st_gid)
    except OSError:
        pass                                              # not allowed to give a file away: the owner stays the user


def replace_with_clone(keep: str, dup: str, *, clone: Callable[[str, str], None] = clone_file,
                       same: Callable[[str, str], bool] = files_identical) -> None:
    """Make ``dup`` share the data of ``keep``. Steps: refuse a link, the same file or a different size; clone ``keep`` into a hidden
    temp file in ``dup``'s folder; read the clone and ``dup`` and refuse unless they are byte for byte the same (so a file that changed
    since the scan is left alone); give the clone ``dup``'s dates, mode and owner; replace ``dup`` with it in one step.
    On any failure the temp file is removed and ``dup`` is as it was. Raises ``CloneError``."""
    if os.path.islink(dup) or os.path.islink(keep):
        raise CloneError(0, "A link is never replaced", dup)
    try:
        if os.path.getsize(keep) != os.path.getsize(dup):
            raise CloneError(0, "The file changed since it was found", dup)
    except OSError as e:
        raise CloneError(e.errno, f"Cannot read the file ({e.strerror or e})", dup) from e
    if _same_file(keep, dup):
        raise CloneError(0, "Already the same file", dup)
    folder = os.path.dirname(os.path.abspath(dup))
    fd, tmp = tempfile.mkstemp(prefix=".dossier-clone-", dir=folder)
    os.close(fd)
    os.unlink(tmp)                                        # the clone call makes the file itself
    try:
        try:
            clone(keep, tmp)
        except CloneError:
            raise
        except OSError as e:
            raise CloneError(e.errno, f"The file system could not clone this file ({e.strerror or e})", dup) from e
        if not same(tmp, dup):
            raise CloneError(0, "The file changed since it was found", dup)
        try:
            shutil.copystat(dup, tmp)
            _copy_owner(dup, tmp)
            os.replace(tmp, dup)
        except OSError as e:
            raise CloneError(e.errno, f"Could not replace the file ({e.strerror or e})", dup) from e
    finally:
        if os.path.lexists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# the plan -----------------------------------------------------------------------------------------------------------------------

@dataclass
class CloneItem:
    keep: str
    dup: str
    size: int


@dataclass
class ClonePlan:
    items: list = field(default_factory=list)       # CloneItem
    skipped: list = field(default_factory=list)     # (path, reason)

    @property
    def space(self) -> int:
        return sum(i.size for i in self.items)


def _device(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def build_plan(groups: list, replace: list, *, fstype_of: Callable[[str], str] = filesystem_of) -> ClonePlan:
    """From the groups of duplicates and the paths chosen to be replaced: in each group the first copy that is not chosen is kept,
    and each chosen copy becomes a clone of it. A copy is skipped (with the reason) when the group has nothing left to keep, the
    two are on different volumes, the volume cannot clone, or they are already one file. Reads file info, so run it on a thread."""
    chosen = set(replace)
    plan = ClonePlan()
    cache: dict = {}

    def fs_name(path: str) -> str:
        folder = os.path.dirname(path)
        if folder not in cache:
            cache[folder] = fstype_of(folder)
        return cache[folder]

    for group in groups:
        keeps = [e for e in group.files if e.path not in chosen]
        targets = [e for e in group.files if e.path in chosen]
        for e in targets:
            if not keeps:
                plan.skipped.append((e.path, "Every copy of the file is chosen: one must stay"))
                continue
            keep = keeps[0]
            name = fs_name(e.path)
            if not is_clone_filesystem(name):
                plan.skipped.append((e.path, not_supported_reason(name)))
            elif _device(keep.path) is None or _device(keep.path) != _device(e.path):
                plan.skipped.append((e.path, "The copy to keep is on another volume"))
            elif _same_file(keep.path, e.path):
                plan.skipped.append((e.path, "Already the same file"))
            else:
                plan.items.append(CloneItem(keep.path, e.path, e.size))
    return plan


@dataclass
class CloneReport:
    done: int = 0
    freed: int = 0
    failures: list = field(default_factory=list)    # (path, reason)
    cancelled: bool = False


def run_plan(plan: ClonePlan, *, cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int, int], None]] = None,
             replace: Callable[..., None] = replace_with_clone, clone: Optional[Callable[[str, str], None]] = None) -> CloneReport:
    """Carry out the plan, one file at a time; a failure is noted and the next file goes on. ``progress(done, total)`` counts files.
    A cancel stops before the next file."""
    report = CloneReport()
    total = len(plan.items)
    for i, item in enumerate(plan.items):
        try:
            if cancel is not None:
                cancel.check()
        except Cancelled:
            report.cancelled = True
            break
        if progress:
            progress(i, total)
        try:
            if clone is None:
                replace(item.keep, item.dup)
            else:
                replace(item.keep, item.dup, clone=clone)
            report.done += 1
            report.freed += item.size
        except OSError as e:
            report.failures.append((item.dup, e.strerror or str(e)))
    if progress:
        progress(report.done + len(report.failures), total)
    return report
