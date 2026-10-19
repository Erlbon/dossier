"""The shared selection (spec section 3, decided 2026-10-19: one selection for all windows).

Paths are stored by identity key (``platform.path_key``), not inside any window, so the
selection survives navigation and every window, the status bar and the MCP server read
the same set.

Threads: changes may come from a worker thread (an operation finishing) and are guarded by a
lock. Observers are told about changes through ``dispatch``: give it the GUI's dispatcher and
they always run on the GUI thread, once per burst of changes. Without a dispatcher they run
at once, in the changing thread (fine for tests and the Qt-free core).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Iterable, Optional

from .platform import has_scheme, path_key

log = logging.getLogger(__name__)

Observer = Callable[["SelectionStore"], None]
Dispatcher = Callable[[Callable[[], None]], None]


class SelectionStore:
    def __init__(self, dispatch: Optional[Dispatcher] = None) -> None:
        self._items: dict[str, str] = {}      # identity key -> path as first selected
        self._saved: dict[str, dict[str, str]] = {}
        self._observers: list[Observer] = []
        self._lock = threading.RLock()
        self._dispatch = dispatch
        self._pending = False
        self._sorted: Optional[list[str]] = None

    # observers ------------------------------------------------------------
    def subscribe(self, fn: Observer) -> Callable[[], None]:
        """Call ``fn(store)`` after changes. Returns a function that unsubscribes."""
        with self._lock:
            self._observers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._observers:
                    self._observers.remove(fn)

        return unsubscribe

    def _changed(self) -> None:
        """Call with the lock held, after changing ``_items``."""
        self._sorted = None
        if self._dispatch is None:
            self._notify()
        elif not self._pending:
            self._pending = True
            self._dispatch(self._deliver)

    def _deliver(self) -> None:
        with self._lock:
            self._pending = False
        self._notify()

    def _notify(self) -> None:
        with self._lock:
            observers = list(self._observers)
        for fn in observers:
            try:
                fn(self)
            except Exception:  # one broken observer must not silence the others
                log.exception("selection observer failed")

    # reading --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, path: str) -> bool:
        return path_key(path) in self._items

    def paths(self) -> list[str]:
        """Selected paths in a stable order (sorted by identity key). A fresh list each call."""
        with self._lock:
            if self._sorted is None:
                self._sorted = [self._items[k] for k in sorted(self._items)]
            return list(self._sorted)

    # changing -------------------------------------------------------------
    def add(self, paths: Iterable[str]) -> None:
        with self._lock:
            before = len(self._items)
            for p in paths:
                self._items.setdefault(path_key(p), p)
            if len(self._items) != before:
                self._changed()

    def remove(self, paths: Iterable[str]) -> None:
        with self._lock:
            before = len(self._items)
            for p in paths:
                self._items.pop(path_key(p), None)
            if len(self._items) != before:
                self._changed()

    def toggle(self, path: str) -> bool:
        """Flip one item; returns True if it is now selected."""
        key = path_key(path)
        with self._lock:
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
        with self._lock:
            if new != self._items:
                self._items = new
                self._changed()

    def clear(self) -> None:
        with self._lock:
            if self._items:
                self._items = {}
                self._changed()

    def invert(self, universe: Iterable[str]) -> None:
        """Select what is not selected among ``universe`` (e.g. the items of one folder)."""
        universe_map = {path_key(p): p for p in universe}
        with self._lock:
            kept = {k: v for k, v in self._items.items() if k not in universe_map}
            flipped = {k: v for k, v in universe_map.items() if k not in self._items}
            new = {**kept, **flipped}
            if new != self._items:
                self._items = new
                self._changed()

    # the selection follows the files -------------------------------------
    def remap(self, mapping: dict) -> None:
        """Items that were moved or renamed keep their place in the selection under the new
        path, and so does everything that was inside a moved folder."""
        if not mapping:
            return
        pairs = list(mapping.items())
        with self._lock:
            new_items: dict[str, str] = {}
            for path in self._items.values():
                new_items.setdefault(path_key(_follow(path, pairs)), _follow(path, pairs))
            if new_items != self._items:
                self._items = new_items
                self._changed()

    def remove_missing(self, fs) -> list:
        """Drop local items that no longer exist (after an operation, a refresh or a change made
        by another program). Returns what was dropped. Virtual paths are left alone. Checks every
        item on disk, so run it from a worker job for a large selection."""
        with self._lock:
            candidates = [p for p in self._items.values() if not has_scheme(p)]
        gone = []
        for p in candidates:
            try:
                fs.stat(p)
            except (FileNotFoundError, NotADirectoryError):
                gone.append(p)
            except OSError:
                pass        # unreadable is not the same as gone
        if gone:
            self.remove(gone)
        return gone

    # named selections (S6) -----------------------------------------------
    def save(self, name: str) -> None:
        with self._lock:
            self._saved[name] = dict(self._items)

    def recall(self, name: str, combine: bool = False) -> None:
        with self._lock:
            try:
                saved = self._saved[name]
            except KeyError:
                raise KeyError(f"no saved selection named {name!r}") from None
            if combine:
                self._items = {**self._items, **saved}
            else:
                self._items = dict(saved)
            self._changed()

    def saved_names(self) -> list[str]:
        with self._lock:
            return sorted(self._saved)


def _follow(path: str, pairs: list) -> str:
    """``path`` after the moves in ``pairs`` (old path, new path). Local paths are compared as the system
    compares them; a path of a virtual system (``sftp://h/a``) is compared exactly, with forward slashes."""
    for old, new in pairs:
        if has_scheme(old) or has_scheme(path):
            if path == old:
                return new
            prefix = old.rstrip("/") + "/"
            if path.startswith(prefix):
                return new.rstrip("/") + "/" + path[len(prefix):]
            continue
        norm = os.path.normpath(path)
        old_norm = os.path.normpath(old)
        folded, old_folded = os.path.normcase(norm), os.path.normcase(old_norm)
        if folded == old_folded:
            return new
        if folded.startswith(old_folded.rstrip(os.sep) + os.sep):
            return os.path.join(new, norm[len(old_norm.rstrip(os.sep)) + 1:])
    return path
