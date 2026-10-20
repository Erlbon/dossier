"""Undo journal for file operations (spec F10).

A finished operation leaves an ``UndoAction``: the steps that changed something and can be
reverted (a move, a created file, a created folder). Undo checks that the world still looks
as the operation left it and refuses, per step, when it does not, so a file the user edited
afterwards is never removed.

The journal holds paths, which are user data, so it lives in memory only. ``save`` and
``load`` exist for a caller that the user has explicitly allowed to keep a history.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .platform import path_key
from .transfer import move_item as _move_item
from .vfs import FileSystem

_MTIME_TOLERANCE = 2.0   # seconds: some file systems store time coarsely


@dataclass
class Step:
    kind: str            # moved | created_file | created_dir
    a: str               # moved: original path; otherwise the created path
    b: str = ""          # moved: where it went
    size: int = 0
    mtime: float = 0.0
    replaced: str = ""      # an older file this step replaced went to the recycle bin under this name


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
    removed: list = field(default_factory=list)    # created items the undo removed
    notes: list = field(default_factory=list)      # things the user should know although nothing went wrong


class UndoLog:
    def __init__(self, max_entries: int = 50) -> None:
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
        """Revert the newest action. Steps that cannot be reverted safely stay in the action, so
        the user can fix the cause and try again. Returns None when there is nothing to undo."""
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
                if step.replaced:
                    shown = step.replaced[:-len(".dossier-old")] if step.replaced.endswith(".dossier-old") else step.replaced
                    report.notes.append(f"{shown} had replaced an older file, which is in the recycle bin as "
                                        f"{step.replaced}: restore it from there.")
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

    # explicit persistence ------------------------------------------------------------------
    def save(self, path: str) -> None:
        data = [{"label": a.label, "when": a.when, "steps": [asdict(s) for s in a.steps]} for a in self._actions]
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def load(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._actions = [UndoAction(d["label"], [Step(**s) for s in d["steps"]], d["when"]) for d in data]
        del self._actions[: -self.max_entries]


def _stat(fs: FileSystem, path: str):
    try:
        return fs.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _revert(fs: FileSystem, step: Step) -> str:
    """Undo one step. Returns a problem description, or an empty string on success."""
    if step.kind == "moved":
        now = _stat(fs, step.b)
        if now is None:
            return f"{step.b} is no longer there"
        if _stat(fs, step.a) is not None and path_key(step.a) != path_key(step.b):
            return f"the original place is taken: {step.a}"
        fs.mkdir(fs.dirname(step.a), parents=True, exist_ok=True)
        try:
            _move_item(fs, step.b, step.a, now.is_dir, None)
        except OSError as e:
            return f"{step.b}: {e}"
        return ""
    if step.kind == "created_file":
        now = _stat(fs, step.a)
        if now is None:
            return ""
        if now.size != step.size or abs(now.mtime - step.mtime) > _MTIME_TOLERANCE:
            return f"changed since it was copied, left in place: {step.a}"
        try:
            fs.remove(step.a)
        except OSError as e:
            return f"{step.a}: {e}"
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
