"""A short list of the copies, moves and deletes that were started, kept on disk so they can be continued after a restart.

It is opt-in (Settings > Copy and Move) because it names folders and files. What is kept is the *intention*, not the plan: what was
asked for (copy, move or delete), the items, and where they were going. After a restart the plan is made again from what is still
there: a source that was already moved is gone and drops out by itself, a file that was copied completely is recognised as identical to
its source and skipped, and a half-written file never carries its final name (it is written as ``name.dossier-part`` and renamed at the
end), so nothing half done is ever mistaken for done. An entry is taken off the list when its operation finishes or the owner cancels
it; it stays when the program is closed or killed while the operation is running or waiting.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

MAX_ENTRIES = 50
KINDS = ("copy", "move", "delete")


@dataclass
class Entry:
    kind: str                                   # copy | move | delete
    sources: list
    dest: str = ""                              # the folder the items were going to (copy, move)
    to_trash: bool = True                       # delete: to the recycle bin (False: for good)
    title: str = ""
    started: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def describe(self) -> str:
        n = len(self.sources)
        items = f"{n} item{'s' if n != 1 else ''}"
        if self.kind == "delete":
            return f"Delete {items}" + ("" if self.to_trash else " permanently")
        return f"{'Move' if self.kind == 'move' else 'Copy'} {items} to {self.dest}"


def _entry_from(data) -> Optional[Entry]:
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return None
    sources = [str(s) for s in data.get("sources", []) if s] if isinstance(data.get("sources"), list) else []
    if not sources:
        return None
    return Entry(data["kind"], sources, str(data.get("dest", "")), bool(data.get("to_trash", True)), str(data.get("title", "")),
                 float(data.get("started", 0) or 0), str(data.get("id") or uuid.uuid4().hex))


class Journal:
    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> list:
        """Every entry; a missing, empty or damaged file is an empty list (never an error)."""
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
                json.dump([e.__dict__ for e in entries], f, ensure_ascii=False)
            os.replace(part, self.path)
        except OSError:
            pass                                 # a list that cannot be written must never stop a copy

    def add(self, entry: Entry) -> None:
        entries = [e for e in self.load() if e.id != entry.id]
        entries.append(entry)
        self._save(entries[-MAX_ENTRIES:])

    def remove(self, entry_id: str) -> None:
        entries = self.load()
        kept = [e for e in entries if e.id != entry_id]
        if len(kept) != len(entries):
            self._save(kept)

    def clear(self) -> None:
        self._save([])


def skip_identical(plan, fs):
    """Settle the clashes that are only the leftovers of the interrupted run: a file at the destination with the same size and (to the
    second) the same time as its source is the copy that was already made, so it is skipped. Every other clash stays for the owner."""
    from .ops import Resolution, conflict_rows
    same = {row.index: Resolution.SKIP for row in conflict_rows(plan, fs) if row.identical}
    return plan.resolve_each(same, fs) if same else plan
