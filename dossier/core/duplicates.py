"""Find files with the same content (the engine; the dialogs and what to do with the answer are in the window).

Reading every file of a library to compare it would take hours, so the work is done in three steps that each throw away what cannot
be a duplicate, and only the survivors go on to the next, dearer step:

1. **Size.** Files of different sizes are different. Most files are alone with their size and are done here, without being opened.
2. **The ends.** Of the files that share a size, the first and the last 64 KB are read and compared (a small file is read whole, which
   settles it). Files that differ at the start or the end are different.
3. **Everything.** Only the files that still look identical are read completely (SHA-256), and only those whose digests are equal are
   reported. So a reported group really holds the same bytes.

Links are not followed. A file that cannot be read is counted and left out, never reported as a duplicate. It runs on a thread:
``progress(stage, done, total)`` is called now and then and the ``CancelToken`` stops it between items.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from .checksums import hash_file
from .progress import CancelToken, check
from .search import Criteria, search
from .vfs import FileSystem

END_BYTES = 64 * 1024
KEEP_POLICIES = (("oldest", "the oldest"), ("newest", "the newest"), ("shortest", "the one with the shortest path"))


@dataclass
class Group:
    size: int
    digest: str
    files: list = field(default_factory=list)      # Entry objects, the oldest first

    @property
    def wasted(self) -> int:
        """What the extra copies take: everything but one."""
        return self.size * (len(self.files) - 1)


@dataclass
class Result:
    groups: list = field(default_factory=list)     # biggest waste first
    scanned: int = 0                               # files looked at
    candidates: int = 0                            # files that shared their size with another
    unreadable: int = 0                            # files that could not be read (left out)
    bytes_read: int = 0

    @property
    def wasted(self) -> int:
        return sum(g.wasted for g in self.groups)

    @property
    def copies(self) -> int:
        return sum(len(g.files) for g in self.groups)


def _ends_digest(fs: FileSystem, path: str, size: int) -> tuple:
    """``(digest, complete)``: a hash of the first and the last ``END_BYTES`` (the whole file when it is that small, then ``complete``)."""
    h = hashlib.sha256()
    h.update(str(size).encode())
    with fs.open_read(path) as f:
        head = f.read(END_BYTES)
        h.update(head)
        if size <= 2 * END_BYTES:
            h.update(f.read())
            return h.hexdigest(), True
        f.seek(size - END_BYTES)
        h.update(f.read(END_BYTES))
    return h.hexdigest(), False


def _gather(fs: FileSystem, roots: list, min_size: int, name: str, cancel, progress) -> tuple:
    seen: dict = {}
    scanned = 0
    for root in roots:
        def report(done: int, found: int, base=scanned) -> None:
            progress("Looking at the files", base + done, 0)
        crit = Criteria(root=root, name=name, kinds="files", min_size=max(1, min_size), max_results=5_000_000)
        found = search(fs, crit, cancel, report)
        scanned += found.scanned
        for e in found.entries:
            key = os.path.normcase(os.path.normpath(e.path)) if not fs.case_sensitive else e.path
            seen.setdefault(key, replace(e, name=fs.basename(e.path)))                       # roots may overlap: a file once
    return list(seen.values()), scanned


def find_duplicates(fs: FileSystem, roots: list, *, min_size: int = 1, name: str = "", cancel: Optional[CancelToken] = None,
                    progress: Callable[[str, int, int], None] = lambda stage, done, total: None) -> Result:
    """The groups of identical files below ``roots``. Raises ``Cancelled`` when cancelled."""
    entries, scanned = _gather(fs, list(roots), min_size, name, cancel, progress)
    result = Result(scanned=scanned)

    by_size: dict = {}
    for e in entries:
        by_size.setdefault(e.size, []).append(e)
    sized = [group for group in by_size.values() if len(group) > 1]
    result.candidates = sum(len(g) for g in sized)

    # step 2: the ends of the files
    by_ends: dict = {}
    done = 0
    for group in sized:
        for e in group:
            check(cancel)
            done += 1
            progress("Comparing the start and the end of files", done, result.candidates)
            try:
                digest, complete = _ends_digest(fs, e.path, e.size)
            except (OSError, ValueError, AttributeError):
                result.unreadable += 1
                continue
            result.bytes_read += min(e.size, 2 * END_BYTES)
            by_ends.setdefault((e.size, digest, complete), []).append(e)
    survivors = [(key, group) for key, group in by_ends.items() if len(group) > 1]

    # step 3: whole files, only where the ends agreed and the file is bigger than what was read
    total_bytes = sum(e.size for (size, _d, complete), group in survivors if not complete for e in group)
    read = 0
    final: dict = {}

    def on_bytes(n: int) -> None:
        nonlocal read
        read += n
        progress("Reading whole files that look the same", read, total_bytes)

    for (size, digest, complete), group in survivors:
        if complete:                                         # the whole file was the "ends": nothing more to read
            final.setdefault((size, digest), []).extend(group)
            continue
        for e in group:
            check(cancel)
            before = read
            h = hash_file(fs, e.path, ("sha256",), cancel, on_bytes=on_bytes)
            read = before + e.size                           # a file that failed halfway still counts as passed
            if h.error or "sha256" not in h.digests:
                result.unreadable += 1
                continue
            result.bytes_read += e.size
            final.setdefault((size, h.digests["sha256"]), []).append(e)
    progress("Reading whole files that look the same", total_bytes, total_bytes)

    for (size, digest), files in final.items():
        if len(files) > 1:
            files.sort(key=lambda e: (e.mtime, len(e.path), e.path))
            result.groups.append(Group(size, digest, files))
    result.groups.sort(key=lambda g: (-g.wasted, g.files[0].path))
    return result


def keep_index(group: Group, policy: str) -> int:
    """Which copy of a group to keep under ``policy`` (see ``KEEP_POLICIES``)."""
    files = group.files
    if policy == "newest":
        return max(range(len(files)), key=lambda i: (files[i].mtime, -i))
    if policy == "shortest":
        return min(range(len(files)), key=lambda i: (len(files[i].path), i))
    return min(range(len(files)), key=lambda i: (files[i].mtime, i))             # oldest


def extras(groups: list, policy: str) -> list:
    """The paths to check for removal: every copy but the one ``policy`` keeps, in each group."""
    out = []
    for g in groups:
        keep = keep_index(g, policy)
        out.extend(e.path for i, e in enumerate(g.files) if i != keep)
    return out


def groups_left_empty(groups: list, chosen) -> list:
    """The groups in which every copy is in ``chosen``: removing them all would lose the content."""
    chosen = set(chosen)
    return [g for g in groups if all(e.path in chosen for e in g.files)]
