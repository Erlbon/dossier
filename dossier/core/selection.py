"""The shared selection (spec section 3, decided 2026-10-19: one selection for all windows).

Paths are stored by identity key (``platform.path_key``), not inside any window, so the
selection survives navigation and every window, the status bar and the MCP server read
the same set.
"""
from __future__ import annotations

from typing import Callable, Iterable

from .platform import path_key

Observer = Callable[["SelectionStore"], None]


class SelectionStore:
    def __init__(self) -> None:
        self._items: dict[str, str] = {}      # identity key -> path as first selected
        self._saved: dict[str, dict[str, str]] = {}
        self._observers: list[Observer] = []

    # observers ------------------------------------------------------------
    def subscribe(self, fn: Observer) -> Callable[[], None]:
        """Call ``fn(store)`` after every change. Returns a function that unsubscribes."""
        self._observers.append(fn)
        return lambda: self._observers.remove(fn) if fn in self._observers else None

    def _changed(self) -> None:
        for fn in list(self._observers):
            fn(self)

    # reading --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, path: str) -> bool:
        return path_key(path) in self._items

    def paths(self) -> list[str]:
        """Selected paths in a stable order (sorted by identity key)."""
        return [self._items[k] for k in sorted(self._items)]

    # changing -------------------------------------------------------------
    def add(self, paths: Iterable[str]) -> None:
        before = len(self._items)
        for p in paths:
            self._items.setdefault(path_key(p), p)
        if len(self._items) != before:
            self._changed()

    def remove(self, paths: Iterable[str]) -> None:
        before = len(self._items)
        for p in paths:
            self._items.pop(path_key(p), None)
        if len(self._items) != before:
            self._changed()

    def toggle(self, path: str) -> bool:
        """Flip one item; returns True if it is now selected."""
        key = path_key(path)
        if key in self._items:
            del self._items[key]
            now = False
        else:
            self._items[key] = path
            now = True
        self._changed()
        return now

    def set(self, paths: Iterable[str]) -> None:
        new = {path_key(p): p for p in paths}
        if new != self._items:
            self._items = new
            self._changed()

    def clear(self) -> None:
        if self._items:
            self._items = {}
            self._changed()

    def invert(self, universe: Iterable[str]) -> None:
        """Select what is not selected among ``universe`` (e.g. the items of one folder)."""
        universe_map = {path_key(p): p for p in universe}
        kept = {k: v for k, v in self._items.items() if k not in universe_map}
        flipped = {k: v for k, v in universe_map.items() if k not in self._items}
        self._items = {**kept, **flipped}
        self._changed()

    # named selections (S6) -----------------------------------------------
    def save(self, name: str) -> None:
        self._saved[name] = dict(self._items)

    def recall(self, name: str, combine: bool = False) -> None:
        saved = self._saved[name]
        if combine:
            self._items = {**self._items, **saved}
        else:
            self._items = dict(saved)
        self._changed()

    def saved_names(self) -> list[str]:
        return sorted(self._saved)
