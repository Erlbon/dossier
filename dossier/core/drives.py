"""Drives and mounts for the drive selector (spec O3, W7): a quick list that never blocks, and free
space fetched on the side so a dead network share cannot freeze a window."""
from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .platform import IS_WINDOWS, has_scheme, home_dir, is_server_path, list_volumes, path_key, strip_longpath


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
    folder = home or home_dir()
    drives.append(Drive(folder, os.path.basename(folder.rstrip("/" + chr(92))) or "Home", "(your folder)", "home"))
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


def is_network_path(path: str, drives: Optional[list] = None) -> bool:
    """Whether ``path`` is on a network drive or share. Those have no recycle bin: a delete there is for good, and
    so is the older file an overwrite replaces. A network path (``\\\\server\\share``) is recognised by its form, a
    mapped drive or a mount by the drive list. Never touches the share, so it cannot hang on a dead one."""
    if path and is_server_path(path):
        return True                                  # a server has no recycle bin either
    if not path or has_scheme(path):
        return False
    p = strip_longpath(path) if IS_WINDOWS else path
    if IS_WINDOWS and p.startswith(chr(92) * 2):
        return True
    try:
        drive = drive_of(p, list_drives() if drives is None else drives)
    except Exception:                                # a failed look at the drives must never stop an operation
        return False
    return drive is not None and drive.kind == "network"


def is_remote_quick(path: str) -> bool:
    """Whether ``path`` is on a network drive, from the drive type alone (one call, no look at the share, no drive list), for places
    that ask for every folder that is shown. A path with a scheme (an archive, a result list) is not."""
    if path and is_server_path(path):
        return True
    if not path or has_scheme(path):
        return False
    if IS_WINDOWS:
        import ctypes
        p = strip_longpath(path)
        if p.startswith(chr(92) * 2):
            return True
        root = os.path.splitdrive(p)[0]
        return bool(root) and ctypes.windll.kernel32.GetDriveTypeW(root + chr(92)) == 4          # DRIVE_REMOTE
    return is_network_path(path)


def disk_usage(path: str) -> Optional[tuple]:
    """``(total, free)`` in bytes, or None. May block on a dead share: call it through ``usage_async``."""
    try:
        u = shutil.disk_usage(path)
        return u.total, u.free
    except OSError:
        return None


def probe_async(paths: list, callback: Callable[[str, Optional[tuple], str], None]) -> None:
    """Like ``usage_async``, and the identity of each volume as well: ``callback(path, usage_or_None, identity)``.
    One daemon thread per path, so a dead share holds only its own row."""
    from .drive_identity import identity_of

    def one(p: str) -> None:
        usage = disk_usage(p)
        callback(p, usage, identity_of(p) if usage else "")

    for p in paths:
        threading.Thread(target=one, args=(p,), daemon=True, name="dossier-probe").start()


def usage_async(paths: list, callback: Callable[[str, Optional[tuple]], None]) -> None:
    """Ask for the usage of each path on its own daemon thread (a hung share holds only its own thread
    and never blocks the application from exiting). ``callback(path, usage_or_None)`` runs on that
    thread: the GUI hands in a dispatching wrapper."""
    for p in paths:
        threading.Thread(target=lambda p=p: callback(p, disk_usage(p)), daemon=True, name="dossier-usage").start()
