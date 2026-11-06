"""A short list of the copies, moves and deletes that were started, kept on disk so they can be continued after a restart.

It is opt-in (Settings > Copy and Move) because it names folders and files. What is kept for a copy, move or delete is the *intention*,
not the plan: what was asked for, the items, and where they were going. After a restart the plan is made again from what is still
there: a source that was already moved is gone and drops out by itself, a file that was copied completely is recognised as identical to
its source and skipped. A half-written file is never mistaken for done: a big file or one that replaces another is written as
``name.dossier-part`` and renamed at the end, and a small new file, which the system copies straight to its name at full size, still
has the time it was made, after the job started, so it is copied again (``is_leftover``). An entry is taken off the list when its operation finishes or the owner cancels
it; it stays when the program is closed or killed while the operation is running or waiting, and when it ended with failed steps
(``note`` then says so).

Anything else that runs as a plan (unpack, synchronise, copy with flatten, what the assistant asks for) is kept as a *plan* entry: the
steps themselves, with the owner's conflict choices already in them. After a restart ``remaining_plan`` drops the steps that are done
(the source is gone, or the destination is already the same file), so only what is left runs.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, fields, replace
from typing import Optional

from .ops import Kind, Op, Plan
from .vfs import FileSystem, stat_or_none

MAX_ENTRIES = 50
KINDS = ("copy", "move", "delete", "plan")
PLAN_KINDS = (Kind.COPY, Kind.MOVE, Kind.DELETE, Kind.FINISH_MOVE)    # a plan with none of these (renames, new folders) is not kept
MAX_PLAN_OPS = 100_000
SAME_TIME = 2.0                                                         # seconds (FAT keeps two)
_SETTLED = ("conflict", "dst_is_dir", "dst_mtime", "dst_size")          # a plan is kept after its conflicts were settled


@dataclass
class Entry:
    kind: str                                   # copy | move | delete | plan
    sources: list
    dest: str = ""                              # the folder the items were going to (copy, move)
    to_trash: bool = True                       # delete: to the recycle bin (False: for good)
    title: str = ""
    started: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ops: list = field(default_factory=list)     # plan: the steps still to do (Op objects)
    note: str = ""                              # for example "3 failed last time"

    def to_json(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "ops"}
        if self.ops:
            data["ops"] = [_op_to_json(op) for op in self.ops]
        return data

    def describe(self) -> str:
        return self._describe() + (f" ({self.note})" if self.note else "")

    def _describe(self) -> str:
        if self.kind == "plan":
            n = len(self.ops)
            return f"{self.title or 'Operation'}: {n:,} step{'s' if n != 1 else ''}"
        n = len(self.sources)
        items = f"{n} item{'s' if n != 1 else ''}"
        if self.kind == "delete":
            return f"Delete {items}" + ("" if self.to_trash else " permanently")
        return f"{'Move' if self.kind == 'move' else 'Copy'} {items} to {self.dest}"


_OP_DEFAULTS = {f.name: f.default for f in fields(Op) if f.name != "kind"}


def _op_to_json(op: Op) -> dict:
    data = {"kind": op.kind.value}
    for name, default in _OP_DEFAULTS.items():
        if name not in _SETTLED and getattr(op, name) != default:
            data[name] = getattr(op, name)
    return data


def _op_from_json(data) -> Optional[Op]:
    try:
        kwargs = {k: type(_OP_DEFAULTS[k])(v) for k, v in data.items() if k in _OP_DEFAULTS and k not in _SETTLED}
        return Op(Kind(data["kind"]), **kwargs)
    except (KeyError, TypeError, ValueError):
        return None


def _entry_from(data) -> Optional[Entry]:
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return None
    sources = [str(s) for s in data.get("sources", []) if s] if isinstance(data.get("sources"), list) else []
    ops: list = []
    if data["kind"] == "plan":
        raw = data.get("ops") if isinstance(data.get("ops"), list) else []
        ops = [op for op in (_op_from_json(d) for d in raw if isinstance(d, dict)) if op is not None]
        if not ops:
            return None
    elif not sources:
        return None
    return Entry(data["kind"], sources, str(data.get("dest", "")), bool(data.get("to_trash", True)), str(data.get("title", "")),
                 float(data.get("started", 0) or 0), str(data.get("id") or uuid.uuid4().hex), ops, str(data.get("note", "")))


def plan_entry(plan: Plan) -> Optional[Entry]:
    """The entry that keeps a settled plan, or None when it is not worth keeping (only renames and new folders) or too big."""
    if not plan.ops or len(plan.ops) > MAX_PLAN_OPS or not any(op.kind in PLAN_KINDS for op in plan.ops):
        return None
    return Entry("plan", [], title=plan.title, ops=list(plan.ops))


def remaining_plan(entry: Entry, fs: FileSystem) -> Plan:
    """The steps of a plan entry that are still to do. A step whose source is gone was done (or the item went away); a copy whose
    destination is already the same file (same size, same time to the second) was made before the program stopped, unless it is a
    leftover the stopped run was still writing (``is_leftover``), which is copied again over it. Nothing else is dropped: a folder
    step merges, and the removal after a move across drives still needs its source."""
    kept = []
    for op in entry.ops:
        if op.kind is Kind.MKDIR:
            kept.append(op)
            continue
        try:
            src = stat_or_none(fs, op.src) if op.src else None
            if src is None:
                continue
            dst = stat_or_none(fs, op.dst) if op.kind is Kind.COPY and not op.is_dir else None
        except OSError:
            kept.append(op)                      # cannot tell (a server that does not answer): leave the step in
            continue
        if dst is not None and not dst.is_dir and is_leftover(dst.size, dst.mtime, src.size, entry.started):
            kept.append(replace(op, overwrite=True))     # what the stopped run was still writing: copied again over it
            continue
        if dst is not None and not dst.is_dir and dst.size == src.size and abs(dst.mtime - op.src_mtime) <= SAME_TIME:
            continue
        kept.append(op)
    return Plan(entry.title or "Continue", tuple(kept))


class Journal:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._pool: Optional[ThreadPoolExecutor] = None
        self._gone: set = set()                   # ids taken off, so a slow background write cannot bring one back

    def load(self) -> list:
        """Every entry; a missing, empty or damaged file is an empty list (never an error)."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        items = data if isinstance(data, list) else []
        return [e for e in (_entry_from(d) for d in items) if e is not None][:MAX_ENTRIES]

    def _save(self, entries: list) -> None:
        try:
            if not entries:
                if os.path.exists(self.path):
                    os.remove(self.path)
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            part = self.path + ".part"
            with open(part, "w", encoding="utf-8") as f:
                json.dump([e.to_json() for e in entries], f, ensure_ascii=False, separators=(",", ":"))
            os.replace(part, self.path)
        except OSError:
            pass                                 # a list that cannot be written must never stop a copy

    def add(self, entry: Entry) -> None:
        with self._lock:
            self._gone.discard(entry.id)
            entries = [e for e in self.load() if e.id != entry.id]
            entries.append(entry)
            self._save(entries[-MAX_ENTRIES:])

    def add_later(self, entry: Entry) -> None:
        """``add`` on a thread, for a plan with many steps (the window's thread does not wait for the disk). The writes go one after the
        other in the order they were asked for, and an entry that is taken off before its write happens is not written."""
        def write() -> None:
            with self._lock:
                if entry.id not in self._gone:
                    self.add(entry)
        with self._lock:
            self._gone.discard(entry.id)
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dossier-journal")
        self._pool.submit(write)

    def flush(self) -> None:
        """Wait until the writes asked for so far are on disk."""
        if self._pool is not None:
            self._pool.submit(lambda: None).result()

    def remove(self, entry_id: str) -> None:
        with self._lock:
            self._gone.add(entry_id)
            entries = self.load()
            kept = [e for e in entries if e.id != entry_id]
            if len(kept) != len(entries):
                self._save(kept)

    def clear(self) -> None:
        with self._lock:
            self._gone.update(e.id for e in self.load())
            self._save([])


def is_leftover(dst_size: int, dst_mtime: float, src_size: int, started: float) -> bool:
    """A file the interrupted run was still writing when it stopped. A small file is copied straight to its name by the system, which
    reserves the full size at once, so a cut-off copy has the right size; but it has the time it was made, after the job started,
    where a finished copy carries the source's time. (A file someone else wrote there in the meantime with exactly the source's size
    would be taken for one too: it is replaced, on a drive with a recycle bin into the bin.)"""
    return started > 0 and dst_size == src_size and dst_mtime >= started - SAME_TIME


def settle_leftovers(plan, fs, started: float):
    """Settle the clashes that are only what the interrupted run (begun at ``started``) left behind: a leftover it was still writing is
    copied again without a question, and only then a file with the source's size and time is the copy already made, skipped. Every
    other clash stays for the owner."""
    from .ops import Resolution, conflict_rows
    choices = {}
    for row in conflict_rows(plan, fs):
        if row.can_overwrite and is_leftover(row.dst_size, row.dst_mtime, row.size, started):
            choices[row.index] = Resolution.OVERWRITE
        elif row.identical:
            choices[row.index] = Resolution.SKIP
    return plan.resolve_each(choices, fs) if choices else plan
