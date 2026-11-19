"""Remembered folder states: what a folder held at one moment, kept by hand, compared with later (card 65).

A state is a manifest (``core/manifest.py``: every file below the folder with size, time and SHA-256) saved in Dossier's own folder, never
in the user's. Each state is two files with one id: ``<id>.csv`` (the manifest) and ``<id>.json`` (which folder, when, how many files), so
the list of states is read without opening the big files. ``compare`` tells what was added, removed, changed and moved since.

A file whose time changed but whose checksum did not is the same file: it is counted (``touched``), not listed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from . import manifest
from .vfs import natural_key

ADDED, REMOVED, CHANGED, MOVED = "added", "removed", "changed", "moved"
STATUSES = (ADDED, CHANGED, MOVED, REMOVED)
STATUS_TEXT = {ADDED: "Added", REMOVED: "Removed", CHANGED: "Changed", MOVED: "Moved"}
FOLDER_NAME = "folder-states"


@dataclass
class State:
    id: str
    folder: str
    when: float                      # seconds since 1970, UTC
    files: int
    bytes: int
    csv_path: str = ""

    def to_json(self) -> dict:
        return {"folder": self.folder, "when": self.when, "files": self.files, "bytes": self.bytes}


def states_dir(settings_folder: str) -> str:
    return os.path.join(settings_folder, FOLDER_NAME)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _make_id(folder: str, when: float) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(os.path.normpath(folder))).strip("-")[:30] or "folder"
    key = hashlib.sha1(os.path.normcase(os.path.normpath(folder)).encode("utf-8", "replace")).hexdigest()[:8]
    return f"{name}-{key}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(when))}"


def save_state(directory: str, folder: str, items: list, when: Optional[float] = None) -> State:
    """Keep ``items`` (a ``manifest.build`` result for ``folder``) in ``directory``. A second state in the same second gets a number."""
    when = time.time() if when is None else when
    os.makedirs(directory, exist_ok=True)
    base = _make_id(folder, when)
    state_id, n = base, 1
    while os.path.exists(os.path.join(directory, state_id + ".json")):
        n += 1
        state_id = f"{base}-{n}"
    csv_path = os.path.join(directory, state_id + ".csv")
    manifest.write(items, csv_path)
    state = State(state_id, folder, when, len(items), sum(i.size for i in items), csv_path)
    tmp = os.path.join(directory, state_id + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_json(), f)
    os.replace(tmp, os.path.join(directory, state_id + ".json"))      # the .json is written last: a state without it does not exist
    return state


def list_states(directory: str, folder: str = "") -> list:
    """The remembered states, newest first; only those of ``folder`` when it is given."""
    out = []
    try:
        names = os.listdir(directory)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                data = json.load(f)
            state = State(name[:-5], str(data["folder"]), float(data["when"]), int(data["files"]), int(data.get("bytes", 0)),
                          os.path.join(directory, name[:-5] + ".csv"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not os.path.exists(state.csv_path):
            continue
        if folder and not _same(state.folder, folder):
            continue
        out.append(state)
    out.sort(key=lambda s: s.when, reverse=True)
    return out


def load_items(state: State) -> list:
    return manifest.read(state.csv_path)


def forget_state(state: State) -> None:
    """Delete one remembered state (both its files)."""
    for ext in (".json", ".csv"):
        try:
            os.remove(os.path.splitext(state.csv_path)[0] + ext)
        except FileNotFoundError:
            pass


@dataclass
class Change:
    rel: str                         # the path now (for removed: the path it had)
    status: str
    size: int = 0                    # now (for removed: before)
    old_size: Optional[int] = None   # before, for changed
    mtime: float = 0.0               # now
    old_rel: str = ""                # moved: where it was

    @property
    def exists(self) -> bool:
        return self.status != REMOVED


@dataclass
class Changes:
    rows: list = field(default_factory=list)
    same: int = 0                    # alike and not listed
    touched: int = 0                 # same content, another time: counted in ``same``
    files_before: int = 0
    files_now: int = 0

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)


def _changed(old: manifest.Item, new: manifest.Item) -> bool:
    if old.error or new.error or not old.digest or not new.digest:       # no checksum to trust: size and time have to do
        return old.size != new.size or abs(old.mtime - new.mtime) > 2
    return old.digest != new.digest


def compare(old: list, new: list, case_sensitive: bool = True) -> Changes:
    """What happened between the manifest ``old`` and the manifest ``new`` of the same folder."""
    fold = (lambda s: s) if case_sensitive else (lambda s: s.lower())
    old_by = {fold(i.rel): i for i in old}
    new_by = {fold(i.rel): i for i in new}
    out = Changes(files_before=len(old), files_now=len(new))
    gone, fresh = [], []
    for key, o in old_by.items():
        n = new_by.get(key)
        if n is None:
            gone.append(o)
        elif _changed(o, n):
            out.rows.append(Change(n.rel, CHANGED, n.size, o.size, n.mtime))
        else:
            out.same += 1
            if abs(o.mtime - n.mtime) > 2:
                out.touched += 1
    for key, n in new_by.items():
        if key not in old_by:
            fresh.append(n)
    by_digest: dict = {}
    for o in gone:
        if o.digest and not o.error:
            by_digest.setdefault(o.digest, []).append(o)
    left = []
    for n in fresh:
        pool = by_digest.get(n.digest) if n.digest and not n.error else None
        if pool:
            same_name = [o for o in pool if o.rel.rsplit("/", 1)[-1] == n.rel.rsplit("/", 1)[-1]]
            o = (same_name or pool)[0]
            pool.remove(o)
            out.rows.append(Change(n.rel, MOVED, n.size, None, n.mtime, o.rel))
        else:
            left.append(n)
    moved_from = {c.old_rel for c in out.rows if c.status == MOVED}
    for n in left:
        out.rows.append(Change(n.rel, ADDED, n.size, None, n.mtime))
    for o in gone:
        if o.rel not in moved_from:
            out.rows.append(Change(o.rel, REMOVED, o.size))
    out.rows.sort(key=lambda r: [natural_key(p) for p in r.rel.split("/")])
    return out
