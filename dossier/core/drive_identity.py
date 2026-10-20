"""Which drive is it, really? The letter says nothing: a USB stick can come back as E: or F:, and E: can be another stick.

Identity = the volume GUID plus the volume serial (Windows). The serial changes when a volume is reformatted; the GUID names
the volume. Neither is a checksum of the contents: they only tell drives apart. ``identity_of`` talks to the drive, so it is
called on a worker thread. ``DriveMemory`` compares what a root holds now with what it held before; it does no I/O of its own
(the owner's opt-in storage is handed in as two functions), so it can run on the window's thread.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from typing import Callable, Optional

from .lights import CHANGED, OK


def identity_of(root: str) -> str:
    """``GUID|SERIAL`` of the volume mounted at ``root``, or an empty string when unknown (not Windows, not ready, denied)."""
    if sys.platform != "win32":
        return ""
    try:
        k32 = ctypes.windll.kernel32
        mount = root if root.endswith(chr(92)) else root + chr(92)
        guid = ctypes.create_unicode_buffer(64)
        if not k32.GetVolumeNameForVolumeMountPointW(mount, guid, 64):
            return ""
        serial = ctypes.c_ulong(0)
        if not k32.GetVolumeInformationW(mount, None, 0, ctypes.byref(serial), None, None, None, 0):
            return ""
        return f"{guid.value}|{serial.value:08X}"
    except (OSError, AttributeError, ValueError):
        return ""


class DriveMemory:
    """What each drive root held the last time we looked."""

    def __init__(self, load: Callable[[], dict] = lambda: {}, save: Optional[Callable[[dict], None]] = None,
                 persist: Callable[[], bool] = lambda: False) -> None:
        self._lock = threading.Lock()
        self._load, self._save, self._persist = load, save, persist
        self._seen: dict = {}
        self._flagged: dict = {}               # root -> note, kept for the whole session
        self._loaded = False

    def _ensure(self) -> None:
        if not self._loaded:
            self._loaded = True
            if self._persist():
                self._seen = dict(self._load())

    def judge(self, root: str, identity: str) -> tuple:
        """``(status, note)`` for a drive root and what it holds now. Remembers the answer."""
        if not identity:
            return OK, ""
        key = root.rstrip(chr(92) + "/").lower()
        with self._lock:
            self._ensure()
            before = self._seen.get(key)
            note = ""
            status = OK
            if before is not None and before != identity:
                moved_from = next((k for k, v in self._seen.items() if v == identity and k != key), None)
                if moved_from is not None:
                    note = f"seen before as {moved_from.upper()}"
                    del self._seen[moved_from]
                else:
                    self._flagged[key] = "this letter held another drive before"
            elif before is None:
                moved_from = next((k for k, v in self._seen.items() if v == identity and k != key), None)
                if moved_from is not None:
                    note = f"seen before as {moved_from.upper()}"
                    del self._seen[moved_from]
            self._seen[key] = identity
            if key in self._flagged:                # flagged earlier this session: stays flagged until the program restarts
                status, note = CHANGED, self._flagged[key]
            if self._persist() and self._save is not None:
                self._save(dict(self._seen))
            return status, note

    def forget(self) -> None:
        """Delete everything remembered, here and in storage."""
        with self._lock:
            self._seen.clear()
            self._flagged.clear()
            if self._save is not None:
                self._save({})
