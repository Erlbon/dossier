"""The size of folder trees, on request (the Size column shows DIR until asked).

A tree is walked with the file system's own listing, links are not followed (a link to a big folder does not count
as that folder, and a loop cannot trap the walk), a folder that cannot be read is counted and skipped, and the
walk stops promptly on cancel. Several top folders are walked at once.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .progress import Cancelled, CancelToken, check

WORKERS = 3


@dataclass
class TreeSize:
    size: int = 0           # bytes of all files below
    files: int = 0
    folders: int = 0        # folders below (not counting the top one)
    unreadable: int = 0     # folders that could not be read: their contents are not in the size


def tree_size(fs, path: str, cancel: Optional[CancelToken] = None,
              on_bytes: Optional[Callable[[int], None]] = None) -> TreeSize:
    """Walk ``path``. ``on_bytes(n)`` is told about every few files so a screen can show the total growing."""
    total = TreeSize()
    stack = [path]
    pending = 0
    while stack:
        check(cancel)
        here = stack.pop()
        try:
            entries = fs.list(here)
        except OSError:
            total.unreadable += 1
            continue
        for e in entries:
            if e.is_link:
                continue
            if e.is_dir:
                total.folders += 1
                stack.append(e.path)
            else:
                total.size += e.size
                total.files += 1
                pending += e.size
        if on_bytes is not None and pending:
            on_bytes(pending)
            pending = 0
    return total


def folder_sizes(fs, paths: Sequence[str], cancel: Optional[CancelToken] = None,
                 progress: Optional[Callable[[int, int, int, str], None]] = None, workers: int = WORKERS) -> dict:
    """``{path: TreeSize}`` for each folder. ``progress(done, total, bytes_so_far, name_of_the_one_just_started)``
    is called from worker threads. A cancel returns what was finished by then."""
    results: dict = {}
    lock = threading.Lock()
    state = {"done": 0, "bytes": 0}
    total = len(paths)

    def grow(n: int) -> None:
        with lock:
            state["bytes"] += n

    def one(path: str) -> None:
        if cancel is not None and cancel.cancelled:
            return
        if progress is not None:
            progress(state["done"], total, state["bytes"], fs.basename(path.rstrip("\\/")) or path)
        try:
            result = tree_size(fs, path, cancel, grow)
        except Cancelled:
            return
        with lock:
            results[path] = result
            state["done"] += 1
        if progress is not None:
            progress(state["done"], total, state["bytes"], "")

    if workers <= 1 or total <= 1:
        for path in paths:
            one(path)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, total), thread_name_prefix="dossier-sizes") as pool:
            for future in [pool.submit(one, p) for p in paths]:
                future.result()
    return results
