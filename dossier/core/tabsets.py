"""Saved tab sets: a name for the folders of a panel's tabs, to open again with one click. Qt-free.

A set is the list of the tabs' folders and which tab was in front. It is kept in the settings like the folder layouts: only what the
owner saved by name, nothing is remembered on its own. A set is not tied to a panel: it can be opened into either one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

MAX_SETS = 50
MAX_TABS = 40


@dataclass
class TabSet:
    name: str
    paths: list = field(default_factory=list)
    active: int = 0

    def cleaned(self) -> "TabSet":
        """At most ``MAX_TABS`` folders, none empty, and an ``active`` that points at one of them."""
        paths = [str(p) for p in self.paths if p][:MAX_TABS]
        active = self.active if isinstance(self.active, int) and 0 <= self.active < len(paths) else 0
        return TabSet(self.name.strip(), paths, active)


class TabSetStore:
    def __init__(self) -> None:
        self._sets: dict = {}

    def __len__(self) -> int:
        return len(self._sets)

    def names(self) -> list:
        return sorted(self._sets, key=str.casefold)

    def get(self, name: str) -> Optional[TabSet]:
        return self._sets.get(name)

    def save(self, name: str, paths: list, active: int = 0) -> Optional[TabSet]:
        """Keep ``paths`` under ``name`` (an earlier set of that name is replaced). None when the name or the list is empty."""
        tab_set = TabSet(name or "", list(paths), active).cleaned()
        if not tab_set.name or not tab_set.paths:
            return None
        self._sets.pop(tab_set.name, None)                      # a replaced set moves to the end: the oldest go first when it is full
        self._sets[tab_set.name] = tab_set
        while len(self._sets) > MAX_SETS:
            self._sets.pop(next(iter(self._sets)))
        return tab_set

    def forget(self, name: str) -> bool:
        return self._sets.pop(name, None) is not None

    def clear(self) -> None:
        self._sets.clear()

    def to_json(self) -> str:
        return json.dumps([{"name": s.name, "paths": s.paths, "active": s.active} for s in self._sets.values()], ensure_ascii=False)

    @classmethod
    def from_json(cls, text) -> "TabSetStore":
        """A damaged or foreign text is an empty store, never an error."""
        store = cls()
        try:
            items = json.loads(text) if isinstance(text, str) and text.strip() else []
        except ValueError:
            return store
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("paths"), list):
                store.save(item["name"], item["paths"], item.get("active", 0))
        return store
