"""Compare two folders (and two files): what is only on one side, what is newer, what differs.

The two folders are walked side by side. Only the differences are listed (``include_same`` adds the rest). A folder that exists on both
sides is entered, not listed; a folder that exists on one side only is one row (it stands for everything in it). How two files with
the same name are told apart is the owner's choice:

* ``size``       the sizes are equal;
* ``size_time``  the sizes are equal and the modified times agree (to ``tolerance`` seconds, and optionally allowing exactly one hour
                 of difference, which is what summer time does to the times on a FAT drive);
* ``content``    the bytes are compared (only when the sizes are equal; a different size is a different file).

Nothing is changed; ``core/sync.py`` turns the answer into plans. It runs on a thread: ``progress(stage, done, total)`` is called now and
then and the ``CancelToken`` stops it between items. Links are not followed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .progress import CancelToken, check
from .vfs import Entry, FileSystem, natural_key

BY = (("size_time", "Size and time"), ("size", "Size only"), ("content", "Content (reads the files)"))
ONLY_LEFT, ONLY_RIGHT, LEFT_NEWER, RIGHT_NEWER, DIFFERENT, TYPE, SAME = (
    "only_left", "only_right", "left_newer", "right_newer", "different", "type", "same")
STATUS_TEXT = {ONLY_LEFT: "Only on the left", ONLY_RIGHT: "Only on the right", LEFT_NEWER: "Newer on the left",
               RIGHT_NEWER: "Newer on the right", DIFFERENT: "Different, same time", TYPE: "File on one side, folder on the other",
               SAME: "Same"}
CHUNK = 1024 * 1024
HOUR = 3600.0


@dataclass
class Row:
    rel: str                                  # the path below the two folders, always with "/"
    left: Optional[Entry] = None
    right: Optional[Entry] = None
    status: str = SAME

    @property
    def is_dir(self) -> bool:
        return bool((self.left and self.left.is_dir) or (self.right and self.right.is_dir))

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass
class CompareResult:
    rows: list = field(default_factory=list)
    scanned: int = 0                          # items looked at on both sides
    same: int = 0                             # files that are alike
    unreadable: int = 0                       # folders that could not be read

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)


def _time_relation(a: float, b: float, tolerance: float, ignore_hour: bool) -> int:
    """0 when the two times agree, 1 when ``a`` is newer, -1 when ``b`` is newer."""
    d = a - b
    if abs(d) <= tolerance:
        return 0
    if ignore_hour and abs(abs(d) - HOUR) <= tolerance:
        return 0
    return 1 if d > 0 else -1


def same_content(fs: FileSystem, a: str, b: str, cancel: Optional[CancelToken] = None) -> bool:
    """Whether two files hold the same bytes (stops at the first difference). A file that cannot be read is not the same."""
    try:
        with fs.open_read(a) as fa, fs.open_read(b) as fb:
            while True:
                check(cancel)
                x, y = fa.read(CHUNK), fb.read(CHUNK)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def first_difference(fs: FileSystem, a: str, b: str, cancel: Optional[CancelToken] = None) -> int:
    """The byte position where two files first differ, or -1 when they are identical (a shorter file differs where it ends)."""
    pos = 0
    with fs.open_read(a) as fa, fs.open_read(b) as fb:
        while True:
            check(cancel)
            x, y = fa.read(CHUNK), fb.read(CHUNK)
            if x != y:
                for i in range(min(len(x), len(y))):
                    if x[i] != y[i]:
                        return pos + i
                return pos + min(len(x), len(y))
            if not x:
                return -1
            pos += len(x)


def _file_status(fs: FileSystem, left: Entry, right: Entry, by: str, tolerance: float, ignore_hour: bool, cancel) -> str:
    rel = _time_relation(left.mtime, right.mtime, tolerance, ignore_hour)
    newer = LEFT_NEWER if rel > 0 else RIGHT_NEWER if rel < 0 else DIFFERENT
    if by == "size":
        return SAME if left.size == right.size else newer
    if by == "content":
        if left.size != right.size:
            return newer
        return SAME if same_content(fs, left.path, right.path, cancel) else newer
    if left.size == right.size:
        return SAME if rel == 0 else newer
    return newer


def compare_trees(fs: FileSystem, left_root: str, right_root: str, *, recursive: bool = True, by: str = "size_time",
                  tolerance: float = 2.0, ignore_hour: bool = True, include_same: bool = False,
                  cancel: Optional[CancelToken] = None,
                  progress: Callable[[str, int, int], None] = lambda stage, done, total: None) -> CompareResult:
    """The differences between two folders. Raises ``Cancelled`` when cancelled."""
    result = CompareResult()
    fold = (lambda n: n) if fs.case_sensitive else (lambda n: n.lower())
    stack = [""]
    while stack:
        check(cancel)
        rel = stack.pop()
        sides = []
        for root in (left_root, right_root):
            here = fs.join(root, *rel.split("/")) if rel else root
            try:
                listing = {fold(e.name): e for e in fs.list(here) if not e.is_link}
            except OSError:
                result.unreadable += 1
                listing = {}
            sides.append(listing)
        left, right = sides
        for key in sorted(set(left) | set(right), key=natural_key):
            check(cancel)
            l, r = left.get(key), right.get(key)
            name = (l or r).name
            path = f"{rel}/{name}" if rel else name
            result.scanned += 1
            if l is not None and r is not None:
                if l.is_dir and r.is_dir:
                    if recursive:
                        stack.append(path)
                    continue
                if l.is_dir != r.is_dir:
                    result.rows.append(Row(path, l, r, TYPE))
                    continue
                status = _file_status(fs, l, r, by, tolerance, ignore_hour, cancel)
                if status == SAME:
                    result.same += 1
                    if not include_same:
                        continue
                result.rows.append(Row(path, l, r, status))
            else:
                result.rows.append(Row(path, l, r, ONLY_LEFT if l is not None else ONLY_RIGHT))
            if result.scanned % 200 == 0:
                progress("Comparing the folders", result.scanned, 0)
    progress("Comparing the folders", result.scanned, result.scanned)
    result.rows.sort(key=lambda row: [natural_key(part) for part in row.rel.split("/")])
    return result
