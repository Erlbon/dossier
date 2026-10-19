"""Drives and mounts for the drive selector (spec O3, W7): a quick list that never blocks, and free
space fetched on the side so a dead network share cannot freeze a window."""
from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .platform import IS_WINDOWS, home_dir, list_volumes, path_key


@dataclass(frozen=True)
class Drive:
    path: str      # root to open: 'D:\\' or '/mnt/data'
    name: str      # short name for a button: 'D:' or 'data'
    label: str     # volume label or share path, may be empty
    kind: str      # fixed | removable | network | optical | other | home

    @property
    def title(self) -> str:
        return f"{self.name} {self.label}".strip() if self.label else self.name


def _short_name(root: str, label: str) -> str:
    if IS_WINDOWS:
        return root.rstrip("\\/")                      # 'D:'
    return "/" if root == "/" else os.path.basename(root.rstrip("/")) or root


def list_drives(volumes: Optional[list] = None, home: Optional[str] = None) -> list:
    """Every drive, then the home folder. ``volumes`` and ``home`` are for tests."""
    drives = [Drive(root, _short_name(root, label), label, kind)
              for root, label, kind in (list_volumes() if volumes is None else volumes)]
    drives.append(Drive(home or home_dir(), "Home", "", "home"))
    return drives


def drive_of(path: str, drives: list) -> Optional[Drive]:
    """The drive that holds ``path``: the one with the longest matching root. The home folder only
    wins when no real drive holds the path (it usually lives on one)."""
    key = path_key(path)
    best, best_len = None, -1
    for d in drives:
        if d.kind == "home":
            continue
        root = path_key(d.path).rstrip(os.sep)
        if (key == root or key.startswith(root + os.sep) or root == "") and len(root) > best_len:
            best, best_len = d, len(root)
    return best


def disk_usage(path: str) -> Optional[tuple]:
    """``(total, free)`` in bytes, or None. May block on a dead share: call it through ``usage_async``."""
    try:
        u = shutil.disk_usage(path)
        return u.total, u.free
    except OSError:
        return None


def usage_async(paths: list, callback: Callable[[str, Optional[tuple]], None]) -> None:
    """Ask for the usage of each path on its own daemon thread (a hung share holds only its own thread
    and never blocks the application from exiting). ``callback(path, usage_or_None)`` runs on that
    thread: the GUI hands in a dispatching wrapper."""
    for p in paths:
        threading.Thread(target=lambda p=p: callback(p, disk_usage(p)), daemon=True, name="dossier-usage").start()
