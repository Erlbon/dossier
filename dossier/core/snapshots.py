"""Earlier versions that are already folders (card 67B): the snapshots a NAS, ZFS or btrfs keeps next to the files.

Qt-free, no system calls and no rights needed: a snapshot is only a folder to look in. For a path, every folder above it (and the folder
itself) is tried for these places:

- ``#snapshot`` (Synology, seen over SMB; its folders are named like ``GMT+01-2026.11.18-01.00.00``);
- ``.snapshot`` and ``~snapshot`` (NetApp, QNAP and others);
- ``.zfs/snapshot`` (ZFS; the ``.zfs`` folder is usually hidden and not listed, but opens by name);
- ``.snapshots/<n>/snapshot`` (btrfs with snapper; ``.snapshots/<n>/info.xml`` holds the date, in UTC).

Each snapshot that holds the same relative path gives one ``Moment`` (when, the snapshot's name, the item's path inside it). A snapshot
without the item is left out. Newest first. The layouts are only folder names, so the same code works on every system.
All disk access is here and slow on a network share: run ``find_earlier_versions`` on a thread.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

NAS_NAMES = ("#snapshot", ".snapshot", "~snapshot")
KIND_NAS = "NAS snapshot"
KIND_ZFS = "ZFS snapshot"
KIND_BTRFS = "btrfs snapshot"
WHERE_TEXT = "NAS snapshot folders (#snapshot, .snapshot), ZFS snapshots (.zfs/snapshot) and btrfs snapshots (.snapshots)"

_DATE_TIME = re.compile(r"(\d{4})[-.](\d{2})[-.](\d{2})(?:[-_ T.]+(\d{2})[.:]?(\d{2})(?:[.:]?(\d{2}))?)?")
_COMPACT = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?:[-_T]?(\d{2})(\d{2})(\d{2})?)?(?!\d)")


@dataclass(frozen=True)
class Moment:
    when: float            # seconds since 1970; from the snapshot's name or file, else the snapshot folder's modification time
    name: str              # the snapshot's name as the system gave it (snapper: its number and description)
    kind: str              # KIND_NAS, KIND_ZFS or KIND_BTRFS
    path: str              # the item inside the snapshot
    folder: str            # the snapshot's own folder


@dataclass
class Found:
    moments: list = field(default_factory=list)
    kinds_seen: set = field(default_factory=set)      # kinds of snapshot folder that exist above the item (even if none holds it)
    inside_snapshot: bool = False                     # the item already is in a snapshot: nothing to look for


def _parts(path: str) -> list:
    return [p for p in re.split(r"[\\/]+", path) if p]


def is_inside_snapshot(path: str) -> bool:
    """Whether ``path`` lies in (or is) a snapshot folder, by its name alone (no disk access): nothing there can be changed."""
    parts = [p.lower() for p in _parts(path)]
    for i, p in enumerate(parts):
        if p in NAS_NAMES or p == ".zfs":
            return True
        if p == ".snapshots" and i + 1 < len(parts) and parts[i + 1].isdigit():
            return True
    return False


def _valid(y: int, mo: int, d: int, h: int, mi: int, s: int) -> bool:
    return 1970 <= y <= 2200 and 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and s < 60


def parse_moment(name: str) -> Optional[float]:
    """The time a snapshot's name states (as local time; a zone such as ``GMT+01`` is read as the clock the NAS showed), or None."""
    for pattern in (_DATE_TIME, _COMPACT):
        m = pattern.search(name)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            h, mi, s = (int(g) if g else 0 for g in m.group(4, 5, 6))
            if _valid(y, mo, d, h, mi, s):
                try:
                    return datetime(y, mo, d, h, mi, s).timestamp()
                except (ValueError, OverflowError, OSError):
                    return None
    return None


def _snapper_info(folder: str) -> tuple:
    """(utc time or None, description) from ``<n>/info.xml``."""
    try:
        root = ET.parse(os.path.join(folder, "info.xml")).getroot()
    except (OSError, ET.ParseError):
        return None, ""
    when = None
    text = (root.findtext("date") or "").strip()
    m = _DATE_TIME.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi, s = (int(g) if g else 0 for g in m.group(4, 5, 6))
        if _valid(y, mo, d, h, mi, s):
            try:
                when = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp()
            except (ValueError, OverflowError, OSError):
                when = None
    return when, (root.findtext("description") or "").strip()


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _children(folder: str) -> list:
    """Names of the folders in ``folder`` (empty when it is not there or cannot be read)."""
    try:
        with os.scandir(folder) as it:
            return sorted(e.name for e in it if e.is_dir())
    except OSError:
        return []


def _candidates(above: str) -> list:
    """(kind, [(snapshot name, snapshot folder)]) for each snapshot place that exists under ``above``."""
    out = []
    for name in NAS_NAMES:
        base = os.path.join(above, name)
        if os.path.isdir(base):
            out.append((KIND_NAS, [(c, os.path.join(base, c)) for c in _children(base)]))
    zfs = os.path.join(above, ".zfs", "snapshot")
    if os.path.isdir(zfs):
        out.append((KIND_ZFS, [(c, os.path.join(zfs, c)) for c in _children(zfs)]))
    snaps = os.path.join(above, ".snapshots")
    if os.path.isdir(snaps):
        out.append((KIND_BTRFS, [(c, os.path.join(snaps, c)) for c in _children(snaps)
                                 if os.path.isdir(os.path.join(snaps, c, "snapshot"))]))
    return out


def find_earlier_versions(path: str, cancel: Optional[Callable[[], bool]] = None) -> Found:
    """The moments that hold ``path`` (a file or a folder), newest first. ``cancel()`` true stops the search early."""
    found = Found()
    path = os.path.abspath(path)
    if is_inside_snapshot(path):
        found.inside_snapshot = True
        return found
    seen: set = set()
    above = path
    while True:
        above = os.path.dirname(above)
        if not above:
            break
        try:
            rel = os.path.relpath(path, above)
        except ValueError:                       # another drive
            break
        if rel == ".":                           # ``path`` is a root: nothing above it
            break
        for kind, snapshots in _candidates(above):
            found.kinds_seen.add(kind)
            for name, root in snapshots:
                if cancel is not None and cancel():
                    return _finish(found)
                if (kind, name) in seen:
                    continue
                inside = os.path.join(root, "snapshot", rel) if kind == KIND_BTRFS else os.path.join(root, rel)
                if not os.path.lexists(inside):
                    continue
                seen.add((kind, name))
                when, label = None, name
                if kind == KIND_BTRFS:
                    when, desc = _snapper_info(root)
                    label = f"{name}  {desc}" if desc else name
                if when is None:
                    when = parse_moment(name)
                if when is None:
                    when = _mtime(root)
                found.moments.append(Moment(when, label, kind, inside, root))
        parent = os.path.dirname(above)
        if parent == above:
            break
        # keep going up: the share's own #snapshot sits at the top, a btrfs subvolume's .snapshots at its root
    return _finish(found)


def _finish(found: Found) -> Found:
    found.moments.sort(key=lambda m: (m.when, m.name), reverse=True)
    return found


def nothing_found_text(found: Found, shown: str) -> str:
    """The message when no moment was found: where it looked, in kinds."""
    if found.inside_snapshot:
        return f"{shown} is already in an earlier version (a snapshot folder). Copy it out to bring it back."
    if found.kinds_seen:
        kinds = ", ".join(sorted(found.kinds_seen))
        return f"{kinds} folders were found above {shown}, but none of the snapshots holds it."
    return f"No earlier versions were found for {shown}. Looked for {WHERE_TEXT}."
