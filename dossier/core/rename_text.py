"""Rename by editing the names as text (Tools > Batch Rename > Edit the Names as Text).

The names of the chosen items are written one per line; the user edits them in a text editor and saves; the lines are read back and
matched to the items by position. The idea is massren's (github.com/laurent22/massren), written in our own way. Nothing here
touches Qt, and nothing renames: the result is a ``Plan`` (``plan_text_renames``) that runs like any other rename plan, so it is shown,
its conflicts are handled and Ctrl+Z puts it back.

What is refused, with nothing renamed: a different number of lines than were written, an emptied line (a rename never deletes),
a name that cannot be a file name here, and a folder that changed while the text was open (an item added, gone or renamed).
Lines that start with ``//`` are the header and are ignored when read; a file name cannot start with two slashes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .ops import Kind, Op, Plan, _check_sources_writable, _stat, check_name
from .platform import is_case_only_change, path_key
from .vfs import FileSystem

COMMENT = "//"
HEADER = (
    "Edit the names below, one item per line, then save the file and close it.",
    "Lines are matched to the items by position, so do not add, remove or reorder lines.",
    "A line left alone changes nothing. A line cannot be emptied: deleting is not done here.",
    "Lines that start with // (like these) are ignored.",
)


class RenameTextError(Exception):
    """The text cannot be used; the message says why in plain words. Nothing has been renamed."""


@dataclass(frozen=True)
class Snapshot:
    """What was written: the items (in text order) and every name in their folder at that moment."""
    folder: str
    paths: tuple              # the items, in the order of the lines
    listing: frozenset        # the names in the folder when the text was written
    names: tuple = ()         # the items' names, in the order of the lines


def _names_in(fs: FileSystem, folder: str) -> frozenset:
    return frozenset(fs.basename(e.path) for e in fs.list(folder) if e.name != "..")


def snapshot(fs: FileSystem, paths: Sequence[str]) -> Snapshot:
    """Take note of the items and of their folder, which must be one folder. Reads the disk: call on a thread."""
    paths = tuple(paths)
    if not paths:
        raise RenameTextError("There is nothing to rename.")
    folders = {path_key(fs.dirname(p)) for p in paths}
    if len(folders) != 1:
        raise RenameTextError("The items are not all in one folder.")
    folder = fs.dirname(paths[0])
    if any(chr(10) in fs.basename(p) or chr(13) in fs.basename(p) for p in paths):
        raise RenameTextError("A name with a line break in it cannot be shown one to a line. Rename that item on its own first.")
    return Snapshot(folder, paths, _names_in(fs, folder), tuple(fs.basename(p) for p in paths))


def render(snap: Snapshot, header: bool = True) -> str:
    """The text to edit: the header (when asked for), then one name per line."""
    lines = [f"{COMMENT} {h}" for h in HEADER] if header else []
    return chr(10).join(lines + list(snap.names)) + chr(10)


def parse(text: str, snap: Snapshot) -> list:
    """The edited names, one for each item. Raises ``RenameTextError`` when the line count changed or a line is empty."""
    lines = [ln.rstrip(chr(13)) for ln in text.split(chr(10))]
    if lines and lines[-1] == "":
        lines.pop()                                    # the newline that ends the file
    lines = [ln for ln in lines if not ln.startswith(COMMENT)]
    count = len(snap.paths)
    if len(lines) != count:
        raise RenameTextError(f"There were {count} name{'s' if count != 1 else ''} and now there are {len(lines)} line"
                              f"{'s' if len(lines) != 1 else ''}. Nothing was renamed. Edit the names in place: do not add or "
                              "remove lines.")
    empty = [i + 1 for i, ln in enumerate(lines) if not ln.strip()]
    if empty:
        raise RenameTextError("Line " + ", ".join(str(n) for n in empty[:8]) + " is empty. Nothing was renamed. "
                              "Deleting files is not done here: use Delete (F8).")
    return lines


def check_unchanged(fs: FileSystem, snap: Snapshot) -> None:
    """Raise ``RenameTextError`` when the folder is not as it was when the text was written. Reads the disk: call on a thread."""
    try:
        now = _names_in(fs, snap.folder)
    except OSError as e:
        raise RenameTextError(f"The folder could not be read: {e.strerror or e}. Nothing was renamed.") from e
    if now != snap.listing:
        added = sorted(now - snap.listing)[:3]
        gone = sorted(snap.listing - now)[:3]
        detail = ""
        if added:
            detail += " New: " + ", ".join(added) + "."
        if gone:
            detail += " Gone: " + ", ".join(gone) + "."
        raise RenameTextError("The folder changed while you were editing." + detail + " Nothing was renamed. Start again.")


def pairs_from(snap: Snapshot, names: Sequence[str]) -> list:
    """``(path, new_name)`` for the lines that differ from the item's name. Raises for a name that cannot be a file name."""
    bad = []
    pairs = []
    for i, (path, old, new) in enumerate(zip(snap.paths, snap.names, names)):
        if new == old:
            continue
        why = check_name(new)
        if why:
            bad.append(f"Line {i + 1} ({new}): {why}")
        else:
            pairs.append((path, new))
    if bad:
        raise RenameTextError(chr(10).join(bad[:8]) + chr(10) + "Nothing was renamed.")
    return pairs


def plan_text_renames(fs: FileSystem, pairs: Sequence[tuple]) -> Plan:
    """The rename plan for ``(path, new_name)`` pairs, in an order that works: a name taken by another item of the batch is
    freed first, and a swap or a ring (a to b, b to a) goes through a temporary name. A name taken by an item outside the batch, or
    wanted twice, is a conflict as in every plan."""
    ops: list = []
    warnings: list = []
    blocking: list = []
    skipped: list = []
    taken: set = set()
    _check_sources_writable(fs, [p for p, _n in pairs], "rename", blocking)
    work = []                                          # [src, dst, is_dir, size, mtime]
    for src, new_name in pairs:
        why = check_name(new_name)
        if why:
            blocking.append(f"{fs.basename(src)}: {why}")
            continue
        e = _stat(fs, src)
        if e is None:
            warnings.append(f"no longer there, left out: {src}")
            skipped.append(src)
            continue
        if fs.basename(src) == new_name:
            skipped.append(src)
            continue
        work.append([src, fs.join(fs.dirname(src), new_name), e.is_dir, e.size, e.mtime])
    if blocking:
        return Plan("Rename", (), tuple(warnings), tuple(blocking), tuple(skipped))
    sources = {path_key(w[0]) for w in work}
    via_temp = 0
    while work:
        free = next((w for w in work if path_key(w[1]) not in sources or path_key(w[1]) == path_key(w[0])), None)
        if free is None:                               # only rings are left: move one item aside, its turn comes again
            ring = _on_a_ring(work)
            tmp = _temporary_name(fs, ring[0], sources | taken)
            ops.append(Op(Kind.RENAME, ring[0], tmp, is_dir=ring[2], size=ring[3], src_mtime=ring[4]))
            sources.discard(path_key(ring[0]))
            sources.add(path_key(tmp))
            ring[0] = tmp
            via_temp += 1
            continue
        work.remove(free)
        src, dst, is_dir, size, mtime = free
        sources.discard(path_key(src))
        conflict = ""
        existing = None if path_key(src) == path_key(dst) or is_case_only_change(src, dst) else _stat(fs, dst)
        if path_key(dst) in taken:
            conflict = "two items in this batch would get the same name"
        elif existing is not None and path_key(dst) not in _vacated(ops):
            conflict = "a folder is in the way" if existing.is_dir else "already exists"
        extra = {"conflict": conflict}
        if existing is not None and conflict:
            extra.update(dst_is_dir=existing.is_dir, dst_mtime=existing.mtime, dst_size=existing.size)
        taken.add(path_key(dst))
        ops.append(Op(Kind.RENAME, src, dst, is_dir=is_dir, size=size, src_mtime=mtime, **extra))
    if via_temp:
        warnings.append(f"{via_temp} name{'s swap or go round' if via_temp != 1 else ' goes'} in a ring: done through temporary names, "
                        "and Ctrl+Z puts every name back")
    return Plan("Rename", tuple(ops), tuple(warnings), tuple(blocking), tuple(skipped))


def _on_a_ring(work: list) -> list:
    """An item that is part of a ring: follow "its new name is the old name of ..." from the first until a name comes round again."""
    by_source = {path_key(w[0]): w for w in work}
    seen: list = []
    item = work[0]
    while item not in seen:
        seen.append(item)
        item = by_source[path_key(item[1])]            # every item is blocked, so its target is another item's source
    return item


def _vacated(ops: list) -> set:
    """The names that an earlier step of the plan has already moved away from."""
    return {path_key(op.src) for op in ops}


def _temporary_name(fs: FileSystem, path: str, avoid: set) -> str:
    folder = fs.dirname(path)
    n = 0
    while True:
        n += 1
        candidate = fs.join(folder, f"dossier-rename-{n}.tmp")
        if path_key(candidate) not in avoid and _stat(fs, candidate) is None:
            return candidate
