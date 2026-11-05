"""Manifests: a list of every file below a folder with its size, time and checksum, written as CSV and compared later.

A manifest lets two copies of a folder be compared when they are on different computers with no network between them: make one on each
side, carry the small file across, compare the two. It is also how to check a copy after it was made.

The CSV has one row per file: ``RelPath`` (below the folder, with ``/``; a ``\\`` in an older manifest is read as ``/``), ``Length``,
``LastWriteUtc`` (ISO 8601) and ``SHA256`` (or ``ERROR: ...`` for a file that could not be read). Nothing is written next to the files.

``diff`` tells what is only on one side, what differs, and which of the one-sided files have their content somewhere on the other side
under another name (renamed or moved), which is the difference between "missing" and "filed elsewhere".
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

from .progress import CancelToken, check
from .vfs import FileSystem, natural_key

CHUNK = 1024 * 1024
HEADER = ("RelPath", "Length", "LastWriteUtc", "SHA256")
ERROR = "ERROR: "

# statuses of a diff row
ONLY_A, ONLY_B, ELSEWHERE_A, ELSEWHERE_B, DIFFERENT, UNREADABLE = (
    "only_a", "only_b", "only_a_content_elsewhere", "only_b_content_elsewhere", "different", "unreadable")
STATUSES = (ONLY_A, ONLY_B, ELSEWHERE_A, ELSEWHERE_B, DIFFERENT, UNREADABLE)


class BadManifest(ValueError):
    """A file that is not a manifest, with a sentence saying why."""


@dataclass
class Item:
    rel: str                                  # below the folder, with "/"
    size: int
    mtime: float                              # seconds since 1970, UTC
    digest: str = ""                          # lower-case hex; empty when ``error``
    error: str = ""


@dataclass
class Progress:
    files: int = 0
    bytes: int = 0
    total_files: int = 0
    total_bytes: int = 0


def _utc(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _parse_utc(text: str) -> float:
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def walk_files(fs: FileSystem, root: str, cancel: Optional[CancelToken] = None) -> Iterator[tuple]:
    """``(rel, Entry)`` for every file below ``root``, in natural order; links are not followed, unreadable folders are skipped."""
    stack = [""]
    while stack:
        check(cancel)
        rel = stack.pop()
        here = fs.join(root, *rel.split("/")) if rel else root
        try:
            entries = sorted(fs.list(here), key=lambda e: natural_key(e.name))
        except OSError:
            continue
        folders = []
        for e in entries:
            if e.is_link:
                continue
            path = f"{rel}/{e.name}" if rel else e.name
            if e.is_dir:
                folders.append(path)
            else:
                yield path, e
        stack.extend(reversed(folders))


def build(fs: FileSystem, root: str, cancel: Optional[CancelToken] = None,
          progress: Callable[[Progress], None] = lambda p: None) -> list:
    """An ``Item`` for every file below ``root``. Counts first (so progress has a total), then reads every file once."""
    files = list(walk_files(fs, root, cancel))
    state = Progress(total_files=len(files), total_bytes=sum(e.size for _r, e in files))
    progress(state)
    items = []
    for rel, e in files:
        check(cancel)
        h = hashlib.sha256()
        item = Item(rel, e.size, e.mtime)
        remote = fs.sha256_on_server(e.path) if hasattr(fs, "sha256_on_server") else None
        if remote:                                    # worked out on the server itself (it allows commands): nothing is read here
            item.digest = remote
            state.bytes += e.size
            items.append(item)
            state.files += 1
            continue
        try:
            with fs.open_read(e.path) as f:
                while True:
                    check(cancel)
                    block = f.read(CHUNK)
                    if not block:
                        break
                    h.update(block)
                    state.bytes += len(block)
            item.digest = h.hexdigest()
        except OSError as err:
            item.error = err.strerror or str(err)
        items.append(item)
        state.files += 1
        if state.files % 50 == 0:
            progress(state)
    progress(state)
    return items


def to_csv(items) -> str:
    out = io.StringIO(newline="")
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(HEADER)
    for it in items:
        w.writerow((it.rel, it.size, _utc(it.mtime), it.digest if not it.error else ERROR + it.error))
    return out.getvalue()


def write(items, path: str) -> None:
    """The manifest as a UTF-8 CSV (with a byte order mark, so a spreadsheet reads the names right)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(to_csv(items))


def read(path: str) -> list:
    """The items of a manifest file. Accepts this module's files and the same four columns made by hand (any order, ``\\`` or ``/``)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.reader(f)
        try:
            head = [h.strip() for h in next(rows)]
        except StopIteration:
            raise BadManifest("the file is empty")
        missing = [h for h in HEADER if h not in head]
        if missing:
            raise BadManifest(f"not a manifest: the columns {', '.join(missing)} are missing")
        at = {h: head.index(h) for h in HEADER}
        items = []
        for n, row in enumerate(rows, 2):
            if not row:
                continue
            try:
                rel = row[at["RelPath"]].replace("\\", "/").strip("/")
                size = int(row[at["Length"]])
                value = row[at["SHA256"]].strip()
            except (IndexError, ValueError):
                raise BadManifest(f"row {n} cannot be read")
            item = Item(rel, size, _parse_utc(row[at["LastWriteUtc"]]))
            if value.upper().startswith("ERROR"):
                item.error = value.split(":", 1)[-1].strip() or "unreadable"
            else:
                item.digest = value.lower()
            items.append(item)
    return items


@dataclass
class DiffRow:
    rel: str
    status: str
    size: Optional[int] = None                # on side A (B for only_b rows)
    other_size: Optional[int] = None          # on side B, for "different"
    elsewhere: list = field(default_factory=list)     # the other side's paths that hold this content


@dataclass
class Diff:
    rows: list = field(default_factory=list)
    same: int = 0
    files_a: int = 0
    files_b: int = 0
    bytes_a: int = 0
    bytes_b: int = 0

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    def bytes_of(self, status: str) -> int:
        return sum(r.size or 0 for r in self.rows if r.status == status)

    def summary(self) -> dict:
        return {"files_a": self.files_a, "files_b": self.files_b, "bytes_a": self.bytes_a, "bytes_b": self.bytes_b, "same": self.same,
                **{s: self.count(s) for s in STATUSES}, "bytes_only_a": self.bytes_of(ONLY_A), "bytes_only_b": self.bytes_of(ONLY_B)}


def diff(a: list, b: list, case_sensitive: bool = True) -> Diff:
    """Compare two manifests by path and checksum. Size and time are not trusted to say two files are the same: only the checksum is."""
    fold = (lambda s: s) if case_sensitive else (lambda s: s.lower())
    by_a = {fold(i.rel): i for i in a}
    by_b = {fold(i.rel): i for i in b}
    where_a, where_b = {}, {}
    for i in a:
        if i.digest:
            where_a.setdefault(i.digest, []).append(i.rel)
    for i in b:
        if i.digest:
            where_b.setdefault(i.digest, []).append(i.rel)
    out = Diff(files_a=len(a), files_b=len(b), bytes_a=sum(i.size for i in a), bytes_b=sum(i.size for i in b))
    for key, ia in by_a.items():
        ib = by_b.get(key)
        if ib is None:
            elsewhere = where_b.get(ia.digest, []) if ia.digest else []
            out.rows.append(DiffRow(ia.rel, ELSEWHERE_A if elsewhere else ONLY_A, ia.size, None, elsewhere[:5]))
        elif ia.error or ib.error:
            out.rows.append(DiffRow(ia.rel, UNREADABLE, ia.size, ib.size))
        elif ia.digest == ib.digest:
            out.same += 1
        else:
            out.rows.append(DiffRow(ia.rel, DIFFERENT, ia.size, ib.size))
    for key, ib in by_b.items():
        if key not in by_a:
            elsewhere = where_a.get(ib.digest, []) if ib.digest else []
            out.rows.append(DiffRow(ib.rel, ELSEWHERE_B if elsewhere else ONLY_B, ib.size, None, elsewhere[:5]))
    out.rows.sort(key=lambda r: [natural_key(p) for p in r.rel.split("/")])
    return out


def diff_csv(d: Diff) -> str:
    out = io.StringIO(newline="")
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(("RelPath", "Status", "Length", "OtherLength", "ContentElsewhere"))
    for r in d.rows:
        w.writerow((r.rel, r.status, "" if r.size is None else r.size, "" if r.other_size is None else r.other_size, " | ".join(r.elsewhere)))
    return out.getvalue()
