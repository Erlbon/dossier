"""Indicator lights of the Home page: is this drive or location reachable, and is it the one we saw last time?

The states (docs/home-and-servers-review.md, section 9):
  ok         green, filled dot       readable now (a drive that answered, a location that listed)
  unchecked  grey, hollow dot        saved or mounted, nothing asked yet
  failed     red, cross              the last attempt failed or the drive is not ready
  changed    amber, diamond          a different drive than last time under this letter

Nothing here touches a disk or a network. ``LightBoard`` only remembers what other code found out (a panel that
listed a folder, a drive that answered), so the Home page can show it at once and never pings anything.
"""
from __future__ import annotations

import threading
from typing import Optional

OK = "ok"
UNCHECKED = "unchecked"
FAILED = "failed"
CHANGED = "changed"
STATES = (OK, UNCHECKED, FAILED, CHANGED)

TEXT = {OK: "Connected", UNCHECKED: "Not checked yet", FAILED: "Not available",
        CHANGED: "A different drive than last time"}

LIT_KINDS = ("fixed", "removable", "optical", "other", "network", "netloc")    # Home entries that get a light
LIMIT = 500


def key_of(path: str) -> str:
    """The key a path is remembered under: no case, no trailing separator."""
    return path.replace("/", chr(92)).rstrip(chr(92)).lower() if path[1:2] == ":" else path.rstrip("/").lower()


class LightBoard:
    """What is known about places, shared by the panels. Thread safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict = {}

    def record(self, path: str, status: str, note: str = "") -> None:
        with self._lock:
            if len(self._seen) >= LIMIT:
                self._seen.clear()                    # a fresh start beats an unbounded table
            self._seen[key_of(path)] = (status, note)

    def get(self, path: str) -> Optional[tuple]:
        """``(status, note)`` or None when nothing is known."""
        with self._lock:
            return self._seen.get(key_of(path))

    def status(self, path: str, default: str = UNCHECKED) -> str:
        found = self.get(path)
        return found[0] if found else default


def describe(status: str, note: str = "") -> str:
    """The tooltip of a light."""
    text = TEXT.get(status, "")
    return f"{text}: {note}" if note and text else text or note
