"""The quarantine folder: where files go that you want out of the way but not deleted (a damaged zip, an empty file, a leftover). Qt-free.

A quarantined file keeps its place in the folder tree, so it can be put back where it came from: ``D:\\Photos\\2019\\a.jpg`` becomes
``D:\\Temp\\Quarantine\\Photos\\2019\\a.jpg``. Two ways to choose the folder (Settings > Quarantine):

* **on each drive** (the default): ``<drive>:\\Temp\\Quarantine``. Moving a file there stays on its drive, so it is instant and keeps the file's
  history; elsewhere than Windows the drive is the mount point the file lives on.
* **one folder** for everything: the files of every drive go there, each drive in a folder of its own (``C\\``, ``D\\``...), still mirrored.

Quarantine never deletes anything and never overwrites: a name that is taken in the quarantine keeps both files (the usual conflict dialog).
Emptying the quarantine is left to you.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence

from .ops import Kind, Plan, plan_move
from .platform import IS_WINDOWS, has_scheme, path_key
from .vfs import FileSystem

DRIVE, FOLDER = "drive", "folder"
SUBFOLDER = ("Temp", "Quarantine")


@dataclass(frozen=True)
class Settings:
    mode: str = DRIVE
    folder: str = ""                 # the one folder, when ``mode`` is FOLDER

    def cleaned(self) -> "Settings":
        """Folder mode without a folder is drive mode: nothing is ever quarantined to nowhere."""
        mode = self.mode if self.mode in (DRIVE, FOLDER) else DRIVE
        folder = os.path.normpath(self.folder.strip()) if self.folder.strip() else ""
        return Settings(FOLDER if mode == FOLDER and folder else DRIVE, folder)


class QuarantineError(ValueError):
    """A path that cannot be quarantined or put back, with the reason."""


def _mount_point(path: str) -> str:
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def volume_root(path: str) -> str:
    """The root of the drive ``path`` is on: ``D:\\``, ``\\\\server\\share\\``, or the mount point elsewhere."""
    if IS_WINDOWS:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        return drive + os.sep if drive else os.sep
    return _mount_point(path)


def _relative(path: str) -> str:
    """``path`` without its drive: what is kept of it inside the quarantine."""
    full = os.path.abspath(path)
    root = volume_root(full)
    return full[len(root):].strip("/" + chr(92)) if full.lower().startswith(root.lower()) else full.strip("/" + chr(92))


def _label(path: str) -> str:
    """The folder a drive gets inside the one quarantine folder: ``D`` for ``D:``, ``server_share`` for a network share, none elsewhere."""
    if not IS_WINDOWS:
        return ""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if drive.endswith(":"):
        return drive[:-1].upper()
    return drive.strip(chr(92)).replace(chr(92), "_") or "root"


def root_for(path: str, settings: Settings) -> str:
    """The quarantine folder that holds (or would hold) ``path``."""
    s = settings.cleaned()
    if s.mode == FOLDER:
        return s.folder
    return os.path.join(volume_root(path), *SUBFOLDER)


def is_quarantined(path: str, settings: Settings) -> bool:
    """Whether ``path`` is inside a quarantine folder (judged from the names alone)."""
    if has_scheme(path):
        return False
    key = path_key(os.path.abspath(path)).rstrip("/" + chr(92))
    root = path_key(root_for(path, settings)).rstrip("/" + chr(92))
    return key == root or key.startswith(root + os.sep) or key.startswith(root + "/")


def destination(path: str, settings: Settings) -> str:
    """Where ``path`` goes in the quarantine (mirrored). Raises ``QuarantineError`` if it cannot be quarantined."""
    if has_scheme(path):
        raise QuarantineError("only items on a drive of this computer can be quarantined")
    if is_quarantined(path, settings):
        raise QuarantineError("it is already in the quarantine folder")
    s = settings.cleaned()
    rel = _relative(path)
    if not rel:
        raise QuarantineError("a whole drive cannot be quarantined")
    if s.mode == FOLDER:
        label = _label(path)
        return os.path.join(s.folder, *([label] if label else []), rel)
    return os.path.join(volume_root(path), *SUBFOLDER, rel)


def original_of(path: str, settings: Settings) -> Optional[str]:
    """Where a quarantined ``path`` came from, or None when that cannot be told (it is not in the quarantine, or a label is unknown)."""
    if has_scheme(path) or not is_quarantined(path, settings):
        return None
    s = settings.cleaned()
    full = os.path.abspath(path)
    root = os.path.abspath(root_for(path, s))
    inside = full[len(root):].strip("/" + chr(92))               # is_quarantined said ``full`` is under ``root``
    if not inside:
        return None
    if s.mode == DRIVE:
        return os.path.join(volume_root(full), inside)
    parts = inside.replace("/", os.sep).split(os.sep, 1)
    if not IS_WINDOWS:
        return os.sep + inside
    label, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    if len(label) == 1 and label.isalpha() and rest:
        return label.upper() + ":" + os.sep + rest
    return None


def _merge(title: str, plans: list) -> Plan:
    ops: list = []
    warnings: list = []
    blocking: list = []
    skipped: list = []
    made: set = set()
    for p in plans:
        for op in p.ops:
            if op.kind is Kind.MKDIR:                    # two groups below the same new folder: it is made once
                if op.dst in made:
                    continue
                made.add(op.dst)
            ops.append(op)
        warnings += p.warnings
        blocking += p.blocking
        skipped += p.skipped
    return Plan(title, tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def _plan_into(fs: FileSystem, pairs: Sequence[tuple], title: str) -> Plan:
    """``pairs`` of ``(source, wanted target path)``: one move plan per target folder; a folder that is not there is made by the plan, when it
    runs (planning changes nothing). A move keeps the file's name, so every target ends in the source's own name."""
    groups: dict = {}
    for src, target in pairs:
        groups.setdefault(os.path.dirname(target), []).append(src)
    return _merge(title, [plan_move(fs, sources, folder, make_dest=True) for folder, sources in groups.items()])


def plan_quarantine(fs: FileSystem, paths: Sequence[str], settings: Settings) -> Plan:
    """Move ``paths`` into the quarantine, each keeping its place in the tree. Items that cannot be quarantined are left out with the reason
    in the plan's warnings; the folders it needs are made. Nothing is deleted or overwritten."""
    pairs: list = []
    warnings: list = []
    for path in paths:
        try:
            pairs.append((path, destination(path, settings)))
        except QuarantineError as e:
            warnings.append(f"left out, {e}: {path}")
    plan = _plan_into(fs, pairs, "Move to quarantine")
    return Plan(plan.title, plan.ops, tuple(warnings) + plan.warnings, plan.blocking, plan.skipped)


def plan_put_back(fs: FileSystem, paths: Sequence[str], settings: Settings) -> Plan:
    """Move quarantined ``paths`` back to where they came from (their folders are made again if they are gone)."""
    pairs: list = []
    warnings: list = []
    for path in paths:
        origin = original_of(path, settings)
        if origin is None:
            warnings.append(f"left out, not in the quarantine or its origin is not known: {path}")
        else:
            pairs.append((path, origin))
    plan = _plan_into(fs, pairs, "Put back")
    return Plan(plan.title, plan.ops, tuple(warnings) + plan.warnings, plan.blocking, plan.skipped)
