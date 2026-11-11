"""The planned operations: copies and moves put on a list with Shift+F5 / Shift+F6, reviewed and launched later, together, from any
number of folders (the owner's decisions of 2026-11-11, CLAUDE.md "Planned operations").

An entry keeps the *intention* (which items, from which folder, to which destination, with which options), never a frozen file list:
the plan is made again when it runs, from what is on disk then. An entry marked ``keep`` stays on the list after it runs, with when it
last ran and how it went, and can be run again; a kept copy by default copies only what is missing or changed (``skip_same``), so a
rerun brings the destination up to date without questions. The list is kept in the settings folder until an entry is run or removed;
it is written on purpose by the owner, so it is not opt-in (the resume list is).

Qt-free. A damaged or missing file is an empty list, never an error; a write that fails never stops the program.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Optional

MAX_ENTRIES = 500


@dataclass(frozen=True)
class PlannedEntry:
    kind: str                                    # "copy" or "move"
    sources: tuple                               # the marked items, full paths
    dest: str                                    # where to, as the box would hold it (a folder, or a new name for one item)
    origin: str = ""                             # the folder the items were marked in
    only: str = ""                               # copy only files named like this
    flatten: bool = False
    verify: bool = False
    newer: bool = False                          # an existing file is replaced only by a newer one
    skip_same: bool = False                      # what is there already and the same is left out
    keep: bool = False                           # stays on the list after it runs
    name: str = ""                               # a kept entry's name
    added: float = field(default_factory=time.time)
    last_run: float = 0.0
    last_result: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> dict:
        data = asdict(self)
        data["sources"] = list(self.sources)
        return data

    @property
    def title(self) -> str:
        return "Move" if self.kind == "move" else "Copy"

    def rerun_rule(self) -> str:
        """``missing or changed``, ``newer only`` or ``ask``: what a run does with files that are there already."""
        return "missing or changed" if self.skip_same else "newer only" if self.newer else "ask"

    def kept(self, on: bool, name: str = "") -> "PlannedEntry":
        """Marked to stay (or not). A copy that becomes kept and has no rule yet gets the default: copy what is missing or changed."""
        if not on:
            return replace(self, keep=False)
        rule = {} if (self.skip_same or self.newer or self.kind != "copy") else {"skip_same": True}
        return replace(self, keep=True, name=name or self.name or default_name(self), **rule)


def default_name(entry: PlannedEntry) -> str:
    first = os.path.basename(entry.sources[0].rstrip("\\/")) if entry.sources else "?"
    more = f" and {len(entry.sources) - 1} more" if len(entry.sources) > 1 else ""
    where = os.path.basename(entry.dest.rstrip("\\/")) or entry.dest
    return f"{first}{more} to {where}"


def _entry_from(data) -> Optional[PlannedEntry]:
    if not isinstance(data, dict) or data.get("kind") not in ("copy", "move") or not data.get("sources") or not data.get("dest"):
        return None
    known = {f.name for f in fields(PlannedEntry)}
    values = {k: v for k, v in data.items() if k in known}
    values["sources"] = tuple(str(s) for s in values["sources"] if isinstance(s, str))
    try:
        return PlannedEntry(**values)
    except TypeError:
        return None


class PlannedList:
    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        items = data if isinstance(data, list) else []
        return [e for e in (_entry_from(d) for d in items) if e is not None][:MAX_ENTRIES]

    def _save(self, entries: list) -> None:
        try:
            if not entries:
                if os.path.exists(self.path):
                    os.remove(self.path)
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            part = self.path + ".part"
            with open(part, "w", encoding="utf-8") as f:
                json.dump([e.to_json() for e in entries], f, ensure_ascii=False, indent=1)
            os.replace(part, self.path)
        except OSError:
            pass

    def add(self, entry: PlannedEntry) -> None:
        entries = [e for e in self.load() if e.id != entry.id]
        entries.append(entry)
        self._save(entries[-MAX_ENTRIES:])

    def update(self, entry: PlannedEntry) -> None:
        """Put ``entry`` in place of the one with its id (where it was in the list); a gone entry is not brought back."""
        entries = self.load()
        self._save([entry if e.id == entry.id else e for e in entries])

    def remove(self, entry_id: str) -> None:
        self._save([e for e in self.load() if e.id != entry_id])

    def move(self, entry_id: str, delta: int) -> None:
        """Up (-1) or down (+1) in the running order."""
        entries = self.load()
        i = next((n for n, e in enumerate(entries) if e.id == entry_id), None)
        j = (i if i is not None else 0) + delta
        if i is None or not 0 <= j < len(entries):
            return
        entries[i], entries[j] = entries[j], entries[i]
        self._save(entries)

    def clear(self) -> None:
        self._save([])

    def get(self, entry_id: str) -> Optional[PlannedEntry]:
        return next((e for e in self.load() if e.id == entry_id), None)
