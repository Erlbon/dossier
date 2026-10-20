"""Undo for the few changes that can be put back without risk (spec F10, scaled down on 2026-10-20).

What is journaled and undone:
  * a rename, or a move to another folder on the same drive: renamed back (the same cheap rename that made it);
  * a folder the user created with New Folder and that is still empty: removed.

What is not, on purpose: a copy is never "undone" by deleting the files it made (that is how an undo destroys data);
an overwrite, a delete (it went to the recycle bin; restore it from there) and a move to another drive (it is a
copy and a delete) have no undo either. A file manager's undo is a small convenience, not a safety net: the plan
and its confirmation, the swap that keeps the older file until the new one is in place, and the recycle bin are.

The journal holds paths, which are user data, so it lives in memory only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .platform import path_key
from .vfs import FileSystem, stat_or_none


@dataclass
class Step:
    kind: str            # moved | created_dir
    a: str               # moved: the original path; created_dir: the folder
    b: str = ""          # moved: where it went


@dataclass
class UndoAction:
    label: str
    steps: list
    when: float = field(default_factory=time.time)


@dataclass
class UndoReport:
    label: str
    reverted: int = 0
    problems: list = field(default_factory=list)
    moved: dict = field(default_factory=dict)      # where reverted items are now: old path -> new path
    removed: list = field(default_factory=list)    # created folders the undo removed


class UndoLog:
    def __init__(self, max_entries: int = 20) -> None:
        self.max_entries = max_entries
        self._actions: list = []

    def __len__(self) -> int:
        return len(self._actions)

    def push(self, action: UndoAction) -> None:
        self._actions.append(action)
        del self._actions[: -self.max_entries]

    def labels(self) -> list:
        """Newest first, as a history list would show them."""
        return [a.label for a in reversed(self._actions)]

    def clear(self) -> None:
        self._actions.clear()

    def undo_last(self, fs: FileSystem) -> Optional[UndoReport]:
        """Revert the newest action. Steps that cannot be reverted safely stay in the action, so the user can fix the
        cause and try again. Returns None when there is nothing to undo."""
        if not self._actions:
            return None
        action = self._actions[-1]
        report = UndoReport(action.label)
        left: list = []
        for step in reversed(action.steps):
            problem = _revert(fs, step)
            if problem:
                report.problems.append(problem)
                left.append(step)
            else:
                report.reverted += 1
                if step.kind == "moved":
                    report.moved[step.b] = step.a
                else:
                    report.removed.append(step.a)
        left.reverse()
        if left:
            action.steps = left
        else:
            self._actions.pop()
        return report


_stat = stat_or_none


def _revert(fs: FileSystem, step: Step) -> str:
    """Undo one step. Returns a problem description, or an empty string on success."""
    if step.kind == "moved":
        if _stat(fs, step.b) is None:
            return f"{step.b} is no longer there"
        if _stat(fs, step.a) is not None and path_key(step.a) != path_key(step.b):
            return f"the original place is taken: {step.a}"
        try:
            fs.mkdir(fs.dirname(step.a), parents=True, exist_ok=True)
            fs.rename(step.b, step.a)
        except OSError as e:
            return f"{step.b}: {e.strerror or e}"
        return ""
    if step.kind == "created_dir":
        if _stat(fs, step.a) is None:
            return ""
        try:
            fs.remove(step.a)
        except OSError:
            return f"folder not empty, left in place: {step.a}"
        return ""
    return f"unknown step: {step.kind}"
