"""File operations as plans (spec section 4, principle 3: planned, shown, then committed).

``plan_*`` functions only look at the file system and return a ``Plan``: the exact list of
steps, the conflicts found and the warnings. Nothing changes until ``execute`` runs a plan
that has no unresolved conflict. Every step that can be reverted is journaled for undo
(``undo_log.py``).

Limits of this first version, each reported to the user rather than hidden:
  * everything happens inside ONE file system (copy between sources comes with the VFS work);
  * symbolic links and junctions are skipped with a warning, never followed;
  * a folder cannot be moved to another drive yet (files can: copy, verify, delete);
  * deleting to the recycle bin or trash cannot be undone from here (the bin keeps the item).
"""
from __future__ import annotations

import errno
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Iterable, Optional, Sequence

from .drives import drive_of, list_drives
from .platform import IS_WINDOWS, has_scheme, path_key, strip_longpath
from .progress import Cancelled, CancelToken, ProgressFn, SpeedLimit, check
from .transfer import copy_file, flush_file, move_item as _move_item, verify_copy
from .undo_log import Step, UndoAction, UndoLog
from .vfs import Entry, FileSystem, NotWritable, sort_entries


class Kind(str, Enum):
    COPY = "copy"      # one file
    MKDIR = "mkdir"    # a folder created for a copy (merges if it already exists)
    MOVE = "move"      # file or folder to another folder
    RENAME = "rename"  # same folder, new name
    DELETE = "delete"
    FINISH_MOVE = "finish_move"   # the last step of a folder moved to another drive: removes what was copied


class Resolution(Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    KEEP_BOTH = "keep both"
    OVERWRITE_IF_NEWER = "overwrite if newer"


@dataclass(frozen=True)
class Op:
    kind: Kind
    src: str = ""
    dst: str = ""
    size: int = 0
    is_dir: bool = False
    src_mtime: float = 0.0
    overwrite: bool = False
    to_trash: bool = True
    conflict: str = ""          # not empty = unresolved; the text says why
    dst_is_dir: bool = False    # what is in the way
    dst_mtime: float = 0.0
    group: int = 0              # the steps of a folder moved to another drive belong together


class PlanNotReady(Exception):
    """``execute`` was given a plan that still has conflicts or blocking problems."""


@dataclass(frozen=True)
class Plan:
    title: str
    ops: tuple = ()
    warnings: tuple = ()
    blocking: tuple = ()
    skipped: tuple = ()          # paths left out (nothing to do, vanished, or skipped by the user)

    @property
    def conflicts(self) -> list:
        return [i for i, op in enumerate(self.ops) if op.conflict]

    @property
    def executable(self) -> bool:
        return bool(self.ops) and not self.blocking and not self.conflicts

    @property
    def total_work(self) -> int:
        """Progress denominator: bytes for copies and for moved files (a move to another drive copies them), one unit
        for every other step."""
        return sum(max(op.size, 1) if op.kind is Kind.COPY or (op.kind is Kind.MOVE and not op.is_dir) else 1
                   for op in self.ops)

    def resolve(self, resolution: Resolution, fs: FileSystem, only: Optional[Iterable[int]] = None) -> "Plan":
        """Settle conflicts (all of them, or the listed step numbers). Returns a new plan."""
        chosen = None if only is None else set(only)
        ops = list(self.ops)
        skipped = list(self.skipped)
        drop: set = set()
        for i, op in enumerate(ops):
            if not op.conflict or (chosen is not None and i not in chosen):
                continue
            if resolution is Resolution.SKIP:
                drop.add(i)
                skipped.append(op.dst)
            elif resolution is Resolution.KEEP_BOTH:
                taken = {path_key(o.dst) for j, o in enumerate(ops) if j != i and o.dst}
                new_dst = _unique_name(fs, op.dst, op.is_dir, taken)
                if op.kind is Kind.MKDIR:   # children were planned under the old folder name
                    old_prefix = op.dst.rstrip(fs.sep) + fs.sep
                    for j in range(i + 1, len(ops)):
                        if ops[j].kind is Kind.FINISH_MOVE and ops[j].dst == op.dst:
                            ops[j] = replace(ops[j], dst=new_dst)
                        elif ops[j].dst.startswith(old_prefix):
                            moved = new_dst + fs.sep + ops[j].dst[len(old_prefix):]
                            still = ops[j].conflict if ops[j].conflict != _SAME_ITEM else ""
                            ops[j] = replace(ops[j], dst=moved, conflict=still)
                ops[i] = replace(op, dst=new_dst, conflict="", dst_is_dir=False, dst_mtime=0.0)
            else:
                same_item = path_key(op.src) == path_key(op.dst)
                if same_item or op.is_dir or op.dst_is_dir:
                    ops[i] = replace(op, conflict=_NO_OVERWRITE)
                elif resolution is Resolution.OVERWRITE_IF_NEWER and op.src_mtime <= op.dst_mtime:
                    drop.add(i)
                    skipped.append(op.dst)
                else:
                    ops[i] = replace(op, overwrite=True, conflict="")
        kept = tuple(op for i, op in enumerate(ops) if i not in drop)
        return replace(self, ops=kept, skipped=tuple(skipped))


_SAME_ITEM = "this is the same item"
_NO_OVERWRITE = "a folder, or the item itself, cannot be overwritten: skip it or keep both"


# names ---------------------------------------------------------------------------------
_WIN_BAD = '<>:"|?*'
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def check_name(name: str) -> str:
    """Why ``name`` cannot be a single file name here, or an empty string if it can."""
    if not name or name in (".", ".."):
        return "the name is empty"
    if "/" in name or "\x00" in name or (IS_WINDOWS and "\\" in name):
        return "a name cannot contain a path separator"
    if IS_WINDOWS:
        if any(c in _WIN_BAD or ord(c) < 32 for c in name):
            return "Windows does not allow these characters in a name: < > : \" | ? *"
        if name[-1] in " .":
            return "Windows does not allow a name that ends with a space or a dot"
        if name.split(".")[0].upper() in _WIN_RESERVED:
            return "Windows reserves this name"
    return ""


# planning --------------------------------------------------------------------------------
def _stat(fs: FileSystem, path: str) -> Optional[Entry]:
    try:
        return fs.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _within(fs: FileSystem, child: str, parent: str) -> bool:
    c, p = path_key(child), path_key(parent)
    return c == p or c.startswith(p.rstrip(fs.sep) + fs.sep)


def _unique_name(fs: FileSystem, dst: str, is_dir: bool, taken: set) -> str:
    folder, base = fs.dirname(dst), fs.basename(dst)
    stem, ext = (base, "") if is_dir else os.path.splitext(base)
    n = 2
    while True:
        cand = fs.join(folder, f"{stem} ({n}){ext}")
        if path_key(cand) not in taken and _stat(fs, cand) is None:
            return cand
        n += 1


def _placed(fs: FileSystem, src: str, dst: str, taken: set, is_dir: bool) -> dict:
    """Conflict fields for putting ``src`` at ``dst``; ``taken`` holds the targets already planned."""
    key = path_key(dst)
    fields: dict = {}
    existing = _stat(fs, dst)
    if key in taken:
        fields["conflict"] = "two items in this batch would get the same name"
    elif path_key(src) == key:
        fields["conflict"] = _SAME_ITEM
    elif existing is not None:
        if is_dir and existing.is_dir:
            pass                              # folders merge; their contents are checked one by one
        else:
            fields["conflict"] = "a folder is in the way" if existing.is_dir else "already exists"
    if existing is not None:
        fields["dst_is_dir"] = existing.is_dir
        fields["dst_mtime"] = existing.mtime
    taken.add(key)
    return fields


def _tree_ops(fs: FileSystem, src: str, dst: str, taken: set, ops: list, warnings: list) -> None:
    ops.append(Op(Kind.MKDIR, src, dst, is_dir=True, **_placed(fs, src, dst, taken, True)))
    for e in sort_entries(fs.list(src)):
        child_src = fs.join(src, fs.basename(e.path))
        child_dst = fs.join(dst, fs.basename(e.path))
        if e.is_link:
            warnings.append(f"link skipped (links are not followed): {child_src}")
        elif e.is_dir:
            _tree_ops(fs, child_src, child_dst, taken, ops, warnings)
        else:
            ops.append(Op(Kind.COPY, child_src, child_dst, size=e.size, src_mtime=e.mtime,
                          **_placed(fs, child_src, child_dst, taken, False)))


def _flat_files(fs: FileSystem, src: str, warnings: list) -> Iterable[Entry]:
    for e in sort_entries(fs.list(src)):
        if e.is_link:
            warnings.append(f"link skipped (links are not followed): {e.path}")
        elif e.is_dir:
            yield from _flat_files(fs, e.path, warnings)
        else:
            yield e


def _check_destination(fs: FileSystem, dest_dir: str, blocking: list) -> None:
    d = _stat(fs, dest_dir)
    if d is None or not d.is_dir:
        blocking.append(f"the destination folder does not exist: {dest_dir}")
    elif not fs.is_writable(dest_dir):
        blocking.append("this folder is read-only (items inside an archive cannot be added or changed yet)")


def _check_sources_writable(fs: FileSystem, sources: Sequence[str], what: str, blocking: list) -> None:
    if any(not fs.is_writable(s) for s in sources):
        blocking.append(f"cannot {what} items inside an archive (read-only); copy them out instead")


def plan_copy(fs: FileSystem, sources: Sequence[str], dest_dir: str, *, flatten: bool = False) -> Plan:
    """Copy files and folders into ``dest_dir``. ``flatten`` puts every file straight into it."""
    ops: list = []
    warnings: list = []
    blocking: list = []
    skipped: list = []
    taken: set = set()
    _check_destination(fs, dest_dir, blocking)
    for src in sources:
        e = _stat(fs, src)
        if e is None:
            warnings.append(f"no longer there, left out: {src}")
            skipped.append(src)
        elif e.is_link:
            warnings.append(f"link skipped (links are not followed): {src}")
            skipped.append(src)
        elif e.is_dir:
            if _within(fs, dest_dir, src) and path_key(dest_dir) != path_key(fs.dirname(src)):
                blocking.append(f"cannot copy a folder into itself: {src}")
            elif flatten:
                for f in _flat_files(fs, src, warnings):
                    dst = fs.join(dest_dir, fs.basename(f.path))
                    ops.append(Op(Kind.COPY, f.path, dst, size=f.size, src_mtime=f.mtime,
                                  **_placed(fs, f.path, dst, taken, False)))
            else:
                _tree_ops(fs, src, fs.join(dest_dir, fs.basename(src)), taken, ops, warnings)
        else:
            dst = fs.join(dest_dir, fs.basename(src))
            ops.append(Op(Kind.COPY, src, dst, size=e.size, src_mtime=e.mtime, **_placed(fs, src, dst, taken, False)))
    return Plan("Copy", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def same_volume(fs: FileSystem, a: str, b: str) -> bool:
    """Whether a rename from ``a`` to ``b`` stays on one drive. Anything that is not the local disk counts as
    one volume (the file system itself decides whether it can rename); a failed look counts as one too."""
    if fs.scheme or has_scheme(a) or has_scheme(b):
        return True
    try:
        if IS_WINDOWS:
            return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return True


def plan_move(fs: FileSystem, sources: Sequence[str], dest_dir: str) -> Plan:
    ops: list = []
    warnings: list = []
    blocking: list = []
    skipped: list = []
    taken: set = set()
    _check_destination(fs, dest_dir, blocking)
    _check_sources_writable(fs, sources, "move", blocking)
    for src in sources:
        e = _stat(fs, src)
        dst = fs.join(dest_dir, fs.basename(src))
        if e is None:
            warnings.append(f"no longer there, left out: {src}")
            skipped.append(src)
        elif path_key(src) == path_key(dst):
            warnings.append(f"already in that folder, left out: {src}")
            skipped.append(src)
        elif e.is_dir and _within(fs, dest_dir, src):
            blocking.append(f"cannot move a folder into itself: {src}")
        elif e.is_dir and not same_volume(fs, src, dest_dir):
            # another drive: copy the whole tree (folders merge, as in a copy), then take away the source files
            # that really were copied. Nothing is removed from the source unless every copy succeeded.
            group = len([o for o in ops if o.kind is Kind.FINISH_MOVE]) + 1
            first = len(ops)
            _tree_ops(fs, src, dst, taken, ops, warnings)
            for k in range(first, len(ops)):
                ops[k] = replace(ops[k], group=group)
            ops.append(Op(Kind.FINISH_MOVE, src, dst, is_dir=True, group=group))
        else:
            fields = _placed(fs, src, dst, taken, False)   # a folder never merges on a move
            ops.append(Op(Kind.MOVE, src, dst, size=e.size, is_dir=e.is_dir, src_mtime=e.mtime, **fields))
    return Plan("Move", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def plan_rename_many(fs: FileSystem, pairs: Sequence[tuple]) -> Plan:
    """Rename ``(path, new_name)`` pairs. A target that exists, even one that is itself being
    renamed in this batch, is a conflict, so swaps and chains are never done half way."""
    ops: list = []
    warnings: list = []
    blocking: list = []
    skipped: list = []
    taken: set = set()
    _check_sources_writable(fs, [p for p, _n in pairs], "rename", blocking)
    for src, new_name in pairs:
        why = check_name(new_name)
        e = _stat(fs, src)
        if why:
            blocking.append(f"{fs.basename(src)}: {why}")
            continue
        if e is None:
            warnings.append(f"no longer there, left out: {src}")
            skipped.append(src)
            continue
        dst = fs.join(fs.dirname(src), new_name)
        if fs.basename(src) == new_name:
            skipped.append(src)
            continue
        case_only = path_key(src) == path_key(dst)          # only differs in case, on a case-insensitive system
        if case_only:
            ops.append(Op(Kind.RENAME, src, dst, is_dir=e.is_dir, size=e.size, src_mtime=e.mtime))
            taken.add(path_key(dst))
        else:
            ops.append(Op(Kind.RENAME, src, dst, is_dir=e.is_dir, size=e.size, src_mtime=e.mtime,
                          **_placed(fs, src, dst, taken, False)))
    return Plan("Rename", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def plan_rename(fs: FileSystem, path: str, new_name: str) -> Plan:
    return plan_rename_many(fs, [(path, new_name)])


def plan_delete(fs: FileSystem, sources: Sequence[str], *, to_trash: bool = True) -> Plan:
    ops: list = []
    warnings: list = []
    skipped: list = []
    blocking: list = []
    _check_sources_writable(fs, sources, "delete", blocking)
    for src in sources:
        e = _stat(fs, src)
        if e is None:
            warnings.append(f"no longer there, left out: {src}")
            skipped.append(src)
        else:
            ops.append(Op(Kind.DELETE, src, is_dir=e.is_dir, size=e.size, src_mtime=e.mtime, to_trash=to_trash))
    if ops and not to_trash:
        warnings.append("these items will be deleted permanently and cannot be brought back")
    return Plan("Delete" if not to_trash else "Delete to the recycle bin", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


# executing -----------------------------------------------------------------------------------
Trasher = Callable[[str], None]


def default_trash(path: str) -> None:
    """Send one item to the recycle bin (Windows) or the freedesktop trash (Linux)."""
    try:
        from send2trash import send2trash
    except ImportError as e:  # the item stays where it is
        raise OSError("the recycle bin is not available (send2trash is not installed)") from e
    send2trash(os.path.normpath(strip_longpath(path)))


@dataclass
class OpResult:
    op: Op
    status: str            # done | skipped | failed | cancelled
    error: str = ""
    attempts: int = 1      # more than one when a locked file was tried again


@dataclass
class Result:
    results: list = field(default_factory=list)
    cancelled: bool = False
    aborted: bool = False                          # the user chose to stop after an error: later steps never started
    action: Optional[UndoAction] = None

    @property
    def retried(self) -> list:
        return [r for r in self.results if r.attempts > 1]

    @property
    def failed(self) -> list:
        return [r for r in self.results if r.status == "failed"]

    @property
    def done(self) -> list:
        return [r for r in self.results if r.status == "done"]


@dataclass
class SelectionEffects:
    moved: dict = field(default_factory=dict)     # old path -> new path
    removed: list = field(default_factory=list)   # paths that no longer exist


def selection_effects(result: Result) -> SelectionEffects:
    """What a finished (or cancelled) run did to paths, so the shared selection can follow it."""
    effects = SelectionEffects()
    for r in result.results:
        if r.status == "done" and r.op.kind is Kind.DELETE:
            effects.removed.append(r.op.src)
    if result.action is not None:
        for step in result.action.steps:
            if step.kind == "moved":
                effects.moved[step.a] = step.b
    return effects


def _remove_tree(fs: FileSystem, path: str) -> None:
    e = fs.stat(path)
    if e.is_dir and not e.is_link:
        for child in fs.list(path):
            _remove_tree(fs, fs.join(path, fs.basename(child.path)))
    fs.remove(path)


SMALL_FILE_LIMIT = 8 * 1024 * 1024        # files up to this size are copied by several workers at once
MIN_FILES_FOR_WORKERS = 4                 # fewer small files than this are not worth a pool


@dataclass
class ExecOptions:
    """How a plan is run. The defaults are what a user wants without asking."""
    workers: Optional[int] = None         # None: choose by the target; 1 forces one file at a time
    small_limit: int = SMALL_FILE_LIMIT
    retries: int = 3                      # extra tries for a locked file (the virus scanner has it for a moment)
    retry_delay: float = 0.25             # first wait; doubles each try
    limit_bps: Optional[int] = None       # copy speed limit in bytes per second, for all workers together
    verify: bool = False                  # read every copy back and compare it with the original (C6)
    flush: Optional[bool] = None          # push the data to the device at the end: None = only for removable and network targets
    native_copy: bool = True              # large local files go through the operating system's own copy (C5)
    on_item: Optional[Callable] = None    # (op, number started, number of steps): which item is being worked on
    on_error: Optional[Callable] = None   # (op, error text) -> "retry" | "skip" | "abort", after the retries ran out


SKIP, RETRY, ABORT = "skip", "retry", "abort"
_BUSY_WINERRORS = (5, 32, 33)             # access denied, sharing violation, lock violation
_BUSY_ERRNOS = (errno.EBUSY, errno.ETXTBSY, errno.EAGAIN)


def is_transient(error: OSError) -> bool:
    """A failure that may pass by itself: a file another program holds for a moment. A missing file, a full
    disk, a read-only system or a name that is taken will not."""
    if isinstance(error, (FileNotFoundError, FileExistsError, NotADirectoryError, IsADirectoryError)):
        return False
    if isinstance(error, NotWritable):
        return False
    if error.errno == errno.ENOSPC:
        return False
    return (isinstance(error, PermissionError) or getattr(error, "winerror", None) in _BUSY_WINERRORS
            or error.errno in _BUSY_ERRNOS)


def target_kind(plan: Plan) -> str:
    """What the files are copied to: fixed, removable, network, optical (fixed when it cannot be told)."""
    try:
        dest = next((op.dst for op in plan.ops if op.kind is Kind.COPY), "")
        drive = drive_of(dest, list_drives()) if dest else None
        return drive.kind if drive else "fixed"
    except Exception:                          # the drive list must never stop a copy
        return "fixed"


def choose_workers(fs: FileSystem, plan: Plan, small_count: int, options: ExecOptions) -> int:
    """How many files to copy at once. The cost of a small file is mostly waiting (the virus scanner, the
    file system), so several at once is much faster on a normal disk; on a USB stick, a network share or an
    optical drive it only makes the device seek, so there it is kept low. A single big file never gets a pool."""
    if options.workers is not None:
        return max(1, options.workers)
    if small_count < MIN_FILES_FOR_WORKERS:
        return 1
    cpus = os.cpu_count() or 4
    if fs.scheme:                              # a virtual or remote system: a few connections, never a flood
        return min(4, cpus)
    kind = target_kind(plan)
    if kind in ("removable", "network"):
        return 2
    if kind == "optical":
        return 1
    return max(2, min(8, cpus))


class _Progress:
    """Overall progress that several workers add to. Each running file reports its own bytes; this keeps the
    sum, and a file that ends (done or failed) is counted in full so the bar reaches the end."""

    def __init__(self, callback: Optional[ProgressFn], total: int) -> None:
        self._callback, self._total = callback, total
        self._lock = threading.Lock()
        self._done = 0
        self._seen: dict = {}

    def partial(self, key: int, done_in_item: int) -> None:
        with self._lock:
            self._done += done_in_item - self._seen.get(key, 0)
            self._seen[key] = done_in_item
            self._emit()

    def finish(self, key: int, unit: int) -> None:
        self.partial(key, unit)

    def _emit(self) -> None:
        if self._callback is not None:
            self._callback(min(self._done, self._total), self._total)


def execute(
    plan: Plan,
    fs: FileSystem,
    *,
    progress: Optional[ProgressFn] = None,
    cancel: Optional[CancelToken] = None,
    trasher: Trasher = default_trash,
    undo_log: Optional[UndoLog] = None,
    options: Optional[ExecOptions] = None,
) -> Result:
    """Run a plan. One failing step is reported and the rest carry on; cancel stops promptly (a half-copied
    file is removed), and what was already done stays undoable.

    Order of work: the folders to create first, then the small files by several workers at once, then the big
    files one at a time, then every other step (moves, renames, deletes) in plan order. The undo journal and
    the list of results are always in plan order, whatever order the workers finished in."""
    if not plan.executable:
        raise PlanNotReady("; ".join(plan.blocking) or "the plan has unresolved conflicts or nothing to do")
    opts = options or ExecOptions()
    copies_all = [op for op in plan.ops if op.kind is Kind.COPY]
    local_target = fs.scheme == "" and all(not has_scheme(op.dst) for op in copies_all)
    want_flush = opts.flush if opts.flush is not None else target_kind(plan) in ("removable", "network")
    want_flush = bool(want_flush and local_target and copies_all)
    verify_extra = sum(max(op.size, 1) for op in copies_all) if opts.verify else 0     # reading back is work too
    flush_share = max(len(copies_all), plan.total_work // 50) if want_flush else 0        # the last 2 percent of the bar
    done = _Progress(progress, plan.total_work + verify_extra + flush_share)
    outcomes: dict = {}                              # plan index -> (OpResult, [Step])
    trash_lock = threading.Lock()                    # the recycle bin is asked one item at a time
    ask_lock = threading.Lock()                      # so is the user
    stop = threading.Event()                         # set when the user chose to abort
    started, started_lock = [0], threading.Lock()
    visible_steps = sum(1 for op in plan.ops if op.kind is not Kind.MKDIR)
    limit = SpeedLimit(opts.limit_bps) if opts.limit_bps else None
    pause = time.sleep if opts.retry_delay else (lambda _s: None)

    def safe_trasher(path: str) -> None:
        with trash_lock:
            trasher(path)

    def wait_to_retry(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if cancel is not None and cancel.cancelled:
                raise Cancelled()
            pause(min(0.05, max(0.0, end - time.monotonic())))

    def run_one(i: int, op: Op) -> None:
        if (cancel is not None and cancel.cancelled) or stop.is_set():
            return                                   # never started: it has no result
        counts_bytes = op.kind is Kind.COPY or (op.kind is Kind.MOVE and not op.is_dir)
        if opts.on_item is not None and op.kind is not Kind.MKDIR:
            with started_lock:
                started[0] += 1
                number = started[0]
            opts.on_item(op, number, visible_steps)
        size_unit = max(op.size, 1) if counts_bytes else 1
        unit = size_unit * (2 if opts.verify and op.kind is Kind.COPY else 1)
        sub = (lambda d, _t: done.partial(i, min(d, size_unit))) if progress else None
        sub_verify = (lambda d: done.partial(i, size_unit + min(d, size_unit))) if progress else None
        attempts, tries = 0, 0
        while True:
            steps: list = []
            attempts += 1
            try:
                if op.kind is Kind.FINISH_MOVE:
                    _finish_move(op, indexed, outcomes, fs, steps)
                else:
                    _run_op(op, fs, steps, sub, cancel, safe_trasher, limit, opts.native_copy,
                            sub_verify if opts.verify else False)
                outcome = OpResult(op, "done", attempts=attempts)
                done.finish(i, unit)
                break
            except Cancelled:
                outcome = OpResult(op, "cancelled", attempts=attempts)
                break
            except OSError as e:
                if is_transient(e) and tries < opts.retries:
                    try:
                        wait_to_retry(opts.retry_delay * (2 ** tries))
                    except Cancelled:
                        outcome = OpResult(op, "cancelled", attempts=attempts)
                        break
                    tries += 1
                    done.partial(i, 0)
                    continue
                decision = SKIP
                if opts.on_error is not None:
                    with ask_lock:
                        decision = ABORT if stop.is_set() else opts.on_error(op, str(e))
                if decision == RETRY and not (cancel is not None and cancel.cancelled):
                    tries = 0
                    done.partial(i, 0)
                    continue
                if decision == ABORT:
                    stop.set()
                outcome = OpResult(op, "failed", str(e), attempts=attempts)
                done.finish(i, unit)
                break
        outcomes[i] = (outcome, steps)

    indexed = list(enumerate(plan.ops))
    folders = [(i, op) for i, op in indexed if op.kind is Kind.MKDIR]
    copies = [(i, op) for i, op in indexed if op.kind is Kind.COPY]
    small = [(i, op) for i, op in copies if op.size <= opts.small_limit]
    big = [(i, op) for i, op in copies if op.size > opts.small_limit]
    others = [(i, op) for i, op in indexed if op.kind not in (Kind.MKDIR, Kind.COPY)]
    workers = choose_workers(fs, plan, len(small), opts)
    try:
        for i, op in folders:
            run_one(i, op)
        if workers > 1 and len(small) > 1:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dossier-copy") as pool:
                for future in [pool.submit(run_one, i, op) for i, op in small]:
                    future.result()                  # a bug in a worker is raised here, not swallowed
        else:
            for i, op in small:
                run_one(i, op)
        for i, op in big + others:
            run_one(i, op)
        if want_flush and not stop.is_set() and not (cancel is not None and cancel.cancelled):
            _flush_pass(outcomes, done, flush_share, cancel)
    finally:
        result = Result()
        steps_in_order: list = []
        for i in sorted(outcomes):
            outcome, steps = outcomes[i]
            result.results.append(outcome)
            steps_in_order.extend(steps)
            if outcome.status == "cancelled":
                result.cancelled = True
        if cancel is not None and cancel.cancelled and len(outcomes) < len(plan.ops):
            result.cancelled = True
        result.aborted = stop.is_set()
        if steps_in_order:
            result.action = UndoAction(plan.title, steps_in_order)
            if undo_log is not None:
                undo_log.push(result.action)
    return result


def _flush_pass(outcomes: dict, done: _Progress, share: int, cancel) -> None:
    """Push every copied file to the device, so "done" means the data is there and not only in the cache. A file
    that cannot be flushed is reported as failed; the bar moves one step per file inside its last 2 percent."""
    copied = [(i, o) for i, (o, _s) in sorted(outcomes.items()) if o.status == "done" and o.op.kind is Kind.COPY]
    each = max(1, share // max(1, len(copied)))
    for n, (i, outcome) in enumerate(copied):
        if cancel is not None and cancel.cancelled:
            return
        try:
            flush_file(outcome.op.dst)
        except OSError as e:
            outcomes[i] = (OpResult(outcome.op, "failed", f"copied, but could not be flushed to the device: {e}",
                                    attempts=outcome.attempts), outcomes[i][1])
        done.finish(-1 - n, each)


def _finish_move(op: Op, indexed: list, outcomes: dict, fs: FileSystem, steps: list) -> None:
    """The last step of a folder moved to another drive. Only when every file of the folder was copied (and has
    the size of its original) are the originals removed, then the folders that are empty by then; otherwise
    nothing is touched and the user is told. The journal gets one "moved" entry: the copies are not journaled,
    because undoing them would delete the only copy."""
    members = [(i, o) for i, o in indexed if o.group == op.group and o.kind in (Kind.COPY, Kind.MKDIR)]
    files = [(i, o) for i, o in members if o.kind is Kind.COPY]
    not_done = [o for i, o in files if i not in outcomes or outcomes[i][0].status != "done"]
    if not_done:
        raise OSError(f"{len(not_done)} of {len(files)} files were not copied, so nothing was removed from {op.src}")
    for _i, o in files:
        if fs.stat(o.dst).size != fs.stat(o.src).size:
            raise OSError(f"the copy of {fs.basename(o.src)} does not match the original, so nothing was removed from {op.src}")
    stuck = []
    for _i, o in files:
        try:
            fs.remove(o.src)
        except OSError as e:
            stuck.append(f"{fs.basename(o.src)}: {e.strerror or e}")
    folders = sorted((o.src for _i, o in members if o.kind is Kind.MKDIR), key=len, reverse=True)
    for folder in folders:
        try:
            fs.remove(folder)                     # only succeeds when it is empty
        except OSError:
            pass
    if stuck:
        raise OSError(f"copied, but {len(stuck)} originals could not be removed: " + "; ".join(stuck[:3]))
    steps.append(Step("moved", op.src, op.dst))


def _run_op(op: Op, fs: FileSystem, steps: list, progress, cancel, trasher: Trasher, throttle=None,
            native: bool = True, verify=False) -> None:
    if op.kind is Kind.MKDIR:
        existing = _stat(fs, op.dst)
        if existing is None:
            fs.mkdir(op.dst, parents=True)
            if not op.group:                      # an undo must never delete the only copy of a moved folder
                steps.append(Step("created_dir", op.dst))
        elif not existing.is_dir:
            raise FileExistsError(op.dst)
        return
    if op.kind is Kind.DELETE:
        if op.to_trash:
            trasher(op.src)
        else:
            _remove_tree(fs, op.src)
        return
    if op.overwrite and _stat(fs, op.dst) is not None:
        trasher(op.dst)                       # the old target goes to the bin first: nothing is lost
    if op.kind is Kind.COPY:
        copy_file(fs, op.src, fs, op.dst, progress=progress, cancel=cancel, throttle=throttle, native=native)
        if verify is not False:
            try:
                verify_copy(fs, op.src, fs, op.dst, progress=verify, cancel=cancel)
            except BaseException:
                try:
                    fs.remove(op.dst)                 # a copy that does not match the original is not kept
                except OSError:
                    pass
                raise
        made = fs.stat(op.dst)
        if not op.group:
            steps.append(Step("created_file", op.dst, size=made.size, mtime=made.mtime))
    else:                                     # MOVE or RENAME
        _move_item(fs, op.src, op.dst, op.is_dir, cancel, progress=progress, throttle=throttle)
        steps.append(Step("moved", op.src, op.dst))
