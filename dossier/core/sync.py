"""From the differences of two folders to the plans that make them alike.

``compare.py`` says what differs; here the owner's choice of direction (a *mode*) decides what to do about each difference, and the
chosen actions become ordinary copy and delete plans, so the conflict handling, the progress, the recycle bin, the queue and Ctrl+Z are
the ones every other copy and delete has. Nothing is done here: this module only decides and plans.

The modes, each from the point of view of what happens to the sides:

* ``update_right``  copy what is new or newer on the left to the right; never touches a newer file, never deletes;
* ``update_left``   the same the other way;
* ``mirror_right``  make the right side the same as the left: also replace files that differ whichever is newer, and delete what is only
                    on the right (to the recycle bin);
* ``mirror_left``   the same the other way;
* ``both``          what is only on one side is copied to the other, and the newer of two versions replaces the older. Files that
                    differ with the same time, and a file against a folder, are left for the owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .compare import DIFFERENT, LEFT_NEWER, ONLY_LEFT, ONLY_RIGHT, RIGHT_NEWER, Row, TYPE
from .ops import Plan, Resolution, plan_copy, plan_delete
from .vfs import FileSystem

MODES = (("update_right", "Update the right side: copy what is new or newer on the left"),
         ("update_left", "Update the left side: copy what is new or newer on the right"),
         ("both", "Both ways: copy what is missing, the newer version replaces the older"),
         ("mirror_right", "Make the right side the same as the left (also deletes what is only on the right)"),
         ("mirror_left", "Make the left side the same as the right (also deletes what is only on the left)"))
COPY_RIGHT, COPY_LEFT, DELETE_RIGHT, DELETE_LEFT, NOTHING = "copy_right", "copy_left", "delete_right", "delete_left", ""
ACTION_TEXT = {COPY_RIGHT: "Copy to the right  →", COPY_LEFT: "←  Copy to the left", DELETE_RIGHT: "Delete on the right",
               DELETE_LEFT: "Delete on the left", NOTHING: ""}
REPLACES_NEWER = "replaces a newer file"


@dataclass
class Action:
    row: Row
    kind: str                       # one of the constants above
    replaces: bool = False          # the target already has a file that is replaced
    replaces_newer: bool = False    # ... and it is newer than the one that replaces it (only the mirror modes do that)

    @property
    def source(self) -> Optional[object]:
        return self.row.left if self.kind in (COPY_RIGHT, DELETE_LEFT) else self.row.right

    @property
    def size(self) -> int:
        e = self.source
        return 0 if e is None or e.is_dir else e.size


def decide(row: Row, mode: str) -> Action:
    """What ``mode`` does about one difference."""
    s = row.status
    if s == TYPE:
        return Action(row, NOTHING)
    to_right = mode in ("update_right", "mirror_right", "both")
    to_left = mode in ("update_left", "mirror_left", "both")
    mirror_r, mirror_l = mode == "mirror_right", mode == "mirror_left"
    if s == ONLY_LEFT:
        if to_right:
            return Action(row, COPY_RIGHT)
        return Action(row, DELETE_LEFT) if mirror_l else Action(row, NOTHING)
    if s == ONLY_RIGHT:
        if to_left:
            return Action(row, COPY_LEFT)
        return Action(row, DELETE_RIGHT) if mirror_r else Action(row, NOTHING)
    if s == LEFT_NEWER:
        if to_right:
            return Action(row, COPY_RIGHT, replaces=True)
        return Action(row, COPY_LEFT, replaces=True, replaces_newer=True) if mirror_l else Action(row, NOTHING)
    if s == RIGHT_NEWER:
        if to_left:
            return Action(row, COPY_LEFT, replaces=True)
        return Action(row, COPY_RIGHT, replaces=True, replaces_newer=True) if mirror_r else Action(row, NOTHING)
    if s == DIFFERENT:
        if mirror_r:
            return Action(row, COPY_RIGHT, replaces=True)
        if mirror_l:
            return Action(row, COPY_LEFT, replaces=True)
    return Action(row, NOTHING)


def decide_all(rows: list, mode: str) -> list:
    return [decide(r, mode) for r in rows]


@dataclass
class Summary:
    copies_right: int = 0
    copies_left: int = 0
    deletes_right: int = 0
    deletes_left: int = 0
    replaced: int = 0
    replaced_newer: int = 0
    bytes: int = 0

    @property
    def total(self) -> int:
        return self.copies_right + self.copies_left + self.deletes_right + self.deletes_left

    def text(self) -> str:
        parts = []
        if self.copies_right:
            parts.append(f"copy {self.copies_right:,} to the right")
        if self.copies_left:
            parts.append(f"copy {self.copies_left:,} to the left")
        if self.deletes_right:
            parts.append(f"delete {self.deletes_right:,} on the right")
        if self.deletes_left:
            parts.append(f"delete {self.deletes_left:,} on the left")
        text = ", ".join(parts) or "nothing to do"
        if self.replaced:
            text += f"; {self.replaced:,} existing file{'s' if self.replaced != 1 else ''} replaced"
        if self.replaced_newer:
            text += f", {self.replaced_newer:,} of them {REPLACES_NEWER}" if self.replaced_newer == 1 else \
                f", {self.replaced_newer:,} of them newer than the file that replaces them"
        return text


def summarise(actions: list) -> Summary:
    s = Summary()
    for a in actions:
        if a.kind == COPY_RIGHT:
            s.copies_right += 1
        elif a.kind == COPY_LEFT:
            s.copies_left += 1
        elif a.kind == DELETE_RIGHT:
            s.deletes_right += 1
        elif a.kind == DELETE_LEFT:
            s.deletes_left += 1
        else:
            continue
        s.replaced += a.replaces
        s.replaced_newer += a.replaces_newer
        if a.kind in (COPY_RIGHT, COPY_LEFT):
            s.bytes += a.size
    return s


def _parent_of(fs: FileSystem, root: str, rel: str) -> str:
    parts = rel.split("/")[:-1]
    return fs.join(root, *parts) if parts else root


def build_plans(fs: FileSystem, left_root: str, right_root: str, actions: list) -> list:
    """The plans that carry out ``actions``: one copy plan to each side (a file that is replaced is overwritten, which the owner has
    agreed to by choosing the mode), then one delete plan per side. A plan that has nothing in it is left out."""
    plans = []
    for kind, source_root, target_root in ((COPY_RIGHT, left_root, right_root), (COPY_LEFT, right_root, left_root)):
        by_folder: dict = {}
        for a in actions:
            if a.kind == kind:
                by_folder.setdefault(_parent_of(fs, target_root, a.row.rel), []).append(
                    (a.row.left if kind == COPY_RIGHT else a.row.right).path)
        parts = [plan_copy(fs, sources, folder) for folder, sources in by_folder.items()]
        if not parts:
            continue
        ops = tuple(op for p in parts for op in p.ops)
        merged = Plan("Copy", ops, tuple(w for p in parts for w in p.warnings), tuple(b for p in parts for b in p.blocking),
                      tuple(s for p in parts for s in p.skipped))
        plans.append(merged.resolve(Resolution.OVERWRITE, fs) if merged.conflicts else merged)
    for kind in (DELETE_RIGHT, DELETE_LEFT):
        paths = [(a.row.right if kind == DELETE_RIGHT else a.row.left).path for a in actions if a.kind == kind]
        if paths:
            plans.append(plan_delete(fs, paths, to_trash=True))
    return plans
