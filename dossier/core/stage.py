"""Staging: copying items out of an archive or off a server into a temporary folder, so another program can be handed real files.

Dragging a file from a panel into Explorer or another program works by handing it a list of files on a drive. Items inside a zip or on a
server are not on a drive, so they are copied here first. Because the program that takes the drop waits for it, the amount is limited
(``LIMIT``): a drag of more than that is refused up front, and a folder that turns out bigger while it is copied stops the copy. The
temporary folders are named ``dossier-drag-...`` in the system's temp folder and are removed when the window closes, and old ones left by
a crash when the program starts.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from typing import Optional, Sequence

from .progress import CancelToken, check
from .vfs import FileSystem

LIMIT = 64 * 1024 * 1024
PREFIX = "dossier-drag-"
STALE_AFTER = 24 * 3600


class TooBig(Exception):
    """The items to stage are more than ``LIMIT`` bytes."""


def stage_root() -> str:
    """The temporary folder of this run (not made until used)."""
    return os.path.join(tempfile.gettempdir(), f"{PREFIX}{os.getpid()}")


def _copy_tree(fs: FileSystem, src: str, dst: str, budget: list, cancel: Optional[CancelToken]) -> None:
    check(cancel)
    entry = fs.stat(src)
    if entry.is_dir:
        os.makedirs(dst, exist_ok=True)
        for child in fs.list(src):
            if child.name != "..":
                _copy_tree(fs, child.path, os.path.join(dst, child.name), budget, cancel)
        return
    budget[0] -= entry.size
    if budget[0] < 0:
        raise TooBig(f"more than {LIMIT // (1024 * 1024)} MB")
    with fs.open_read(src) as source, open(dst, "wb") as target:
        shutil.copyfileobj(source, target, 256 * 1024)
    if entry.mtime:
        os.utime(dst, (entry.mtime, entry.mtime))


def stage(fs: FileSystem, paths: Sequence[str], cancel: Optional[CancelToken] = None, limit: int = LIMIT) -> list:
    """Copy ``paths`` into a new folder under ``stage_root()`` and return the local paths, in the same order. Raises ``TooBig``."""
    os.makedirs(stage_root(), exist_ok=True)
    folder = tempfile.mkdtemp(dir=stage_root())
    budget = [limit]
    out = []
    taken: set = set()
    for path in paths:
        name = fs.basename(path.rstrip("/" + chr(92))) or "item"
        base, ext = os.path.splitext(name)
        n = 1
        while name.lower() in taken:
            n += 1
            name = f"{base} ({n}){ext}"
        taken.add(name.lower())
        target = os.path.join(folder, name)
        _copy_tree(fs, path, target, budget, cancel)
        out.append(target)
    return out


def known_size(entries) -> int:
    """The bytes of the files among ``entries`` (folders count as 0: their size is not known until they are read)."""
    return sum(e.size for e in entries if not e.is_dir)


def clean_up(now: Optional[float] = None, *, everything: bool = False) -> int:
    """Remove this run's staging folder (``everything``) and the staging folders older than a day that a crash left. Returns how many went."""
    root = tempfile.gettempdir()
    gone = 0
    mine = stage_root()
    for name in os.listdir(root) if os.path.isdir(root) else []:
        path = os.path.join(root, name)
        if not name.startswith(PREFIX) or not os.path.isdir(path):
            continue
        old = (now or time.time()) - os.path.getmtime(path) > STALE_AFTER
        if (everything and path == mine) or old:
            shutil.rmtree(path, ignore_errors=True)
            gone += 1
    return gone
