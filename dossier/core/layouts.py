"""Folder layouts: a column choice, view mode, thumbnail size and sort order that belong to a folder (and maybe its subfolders).

A *rule* names one folder and a scope: ``only`` (this folder alone) or ``tree`` (this folder and everything below it). When a folder is
shown the rule for exactly that folder wins (either scope), else the nearest parent folder with a ``tree`` rule, else there is no rule
and the owner's ordinary choice (the default) is used. Only folders the owner explicitly set are in the store; it is not a history.
Archives, search results and the Home page (anything with ``://``) never have a rule.

The store is plain data (JSON in the settings file) and knows nothing about Qt.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from .columns import KEYS, LEGACY_KEYS, PROTECTED, newly_hidden

SCOPES = ("only", "tree")
MODES = ("details", "icons")
MAX_RULES = 500
SORT_KEYS = ("name", "size", "modified", "type", "created", "accessed")


@dataclass
class Layout:
    hidden: list = field(default_factory=list)       # column names that are off
    order: list = field(default_factory=list)        # column names, left to right
    mode: str = "details"
    size: int = 128                                  # thumbnail size in pixels
    sort: str = "name"
    desc: bool = False
    known: list = field(default_factory=lambda: list(KEYS), compare=False)   # the columns that existed when this was saved

    def cleaned(self) -> "Layout":
        """The same layout with only known columns, Name and Type always shown, every column present in the order."""
        off = set(self.hidden) | newly_hidden(self.known)      # a column added since this was saved starts hidden
        hidden = [k for k in KEYS if k in off and k not in PROTECTED]
        order = [k for k in self.order if k in KEYS]
        order = list(dict.fromkeys(order)) + [k for k in KEYS if k not in order]
        return Layout(hidden, order, self.mode if self.mode in MODES else "details", int(self.size or 128),
                      self.sort if self.sort in SORT_KEYS else "name", bool(self.desc), list(KEYS))


@dataclass
class Rule:
    path: str
    scope: str
    layout: Layout


def has_rules_for(path: str) -> bool:
    """Whether ``path`` is a real folder path a rule can apply to."""
    return bool(path) and "://" not in path and os.path.isabs(path)


def key_of(path: str) -> str:
    """The path as the store keys it: normalised, case-insensitive on Windows, no trailing separator."""
    return os.path.normcase(os.path.normpath(path))


def _parent_key(key: str) -> str:
    parent = os.path.dirname(key)
    return "" if parent == key else parent


class LayoutStore:
    def __init__(self, rules: Optional[list] = None) -> None:
        self._rules: dict = {}
        for rule in rules or []:
            self._rules[key_of(rule.path)] = rule

    def __len__(self) -> int:
        return len(self._rules)

    def rules(self) -> list:
        return list(self._rules.values())

    def exact(self, path: str) -> Optional[Rule]:
        return self._rules.get(key_of(path)) if has_rules_for(path) else None

    def find(self, path: str) -> Optional[Rule]:
        """The rule in force for ``path``: its own, else the nearest parent's ``tree`` rule, else None."""
        if not has_rules_for(path) or not self._rules:
            return None
        key = key_of(path)
        own = self._rules.get(key)
        if own is not None:
            return own
        parent = _parent_key(key)
        while parent:
            rule = self._rules.get(parent)
            if rule is not None and rule.scope == "tree":
                return rule
            parent = _parent_key(parent)
        return None

    def set(self, path: str, scope: str, layout: Layout) -> Optional[Rule]:
        if not has_rules_for(path) or scope not in SCOPES:
            return None
        rule = Rule(os.path.normpath(path), scope, layout.cleaned())
        self._rules[key_of(path)] = rule
        while len(self._rules) > MAX_RULES:                  # the oldest go first (dicts keep their order)
            self._rules.pop(next(iter(self._rules)))
        return rule

    def remove(self, path: str) -> bool:
        return self._rules.pop(key_of(path), None) is not None

    def clear(self) -> None:
        self._rules.clear()

    # storage -----------------------------------------------------------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps([{"path": r.path, "scope": r.scope, **r.layout.__dict__} for r in self._rules.values()], ensure_ascii=False)

    @classmethod
    def from_json(cls, text) -> "LayoutStore":
        """A damaged or foreign text is an empty store, never an error."""
        store = cls()
        try:
            items = json.loads(text) if isinstance(text, str) and text.strip() else []
        except ValueError:
            return store
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            try:
                layout = Layout(list(item.get("hidden") or []), list(item.get("order") or []), str(item.get("mode", "details")),
                                int(item.get("size", 128)), str(item.get("sort", "name")), bool(item.get("desc", False)),
                                list(item.get("known") or LEGACY_KEYS))
            except (TypeError, ValueError):
                continue
            store.set(item["path"], str(item.get("scope", "only")), layout)
        return store
