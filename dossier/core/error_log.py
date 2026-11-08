"""A log of what went wrong (opt-in, off by default): failed copies, moves and deletes, a network that went away
in the middle, and errors in the program itself.

Nothing is written while it is off. When it is on, each entry is a separator, the time and what happened:
for an operation its title and, for each item that failed, where it came from, where it was going and the
error; for an error in the program the full traceback. A crash Python cannot report (inside Qt) is written
by faulthandler. Unlike the slowness log this one holds file names and folders: that is what makes it useful.
The file is capped (the oldest entries go first), and the user can open and delete it from the Help menu.

The newest entry is at the bottom. No Qt here.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from typing import Callable, Optional

from redactor_common.core.crash_log import ENTRY_SEPARATOR, format_start_marker, trim_if_oversized

MAX_BYTES = 2_000_000


class _Handler(logging.Handler):
    """The program's own warnings and errors (``log.exception`` in the worker and elsewhere) go into the log."""

    def __init__(self, log: "ErrorLog") -> None:
        super().__init__(logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info:
            text += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        self._log.write(f"{record.levelname.capitalize()} in {record.name}", text)


class ErrorLog:
    """``start()`` and ``stop()`` switch it on and off; ``write()`` does nothing while it is off. Safe from any thread."""

    def __init__(self, path: str, app_label: str = "", on_error: Optional[Callable[[str], None]] = None) -> None:
        self.path = path
        self.app_label = app_label
        self.on_error = on_error            # told (on whatever thread) when an error in the program was caught, to say so
        self._lock = threading.Lock()
        self._on = False
        self._fault_file = None
        self._fault_before = False
        self._handler = _Handler(self)
        self._hooks: Optional[tuple] = None

    @property
    def on(self) -> bool:
        return self._on

    def start(self) -> None:
        if self._on:
            return
        self._on = True
        self._append(format_start_marker(self.app_label))     # and faulthandler takes the file
        logging.getLogger("dossier").addHandler(self._handler)
        self._hooks = (sys.excepthook, threading.excepthook)
        sys.excepthook = self._excepthook
        threading.excepthook = self._thread_hook

    def stop(self) -> None:
        if not self._on:
            return
        self._on = False
        logging.getLogger("dossier").removeHandler(self._handler)
        if self._hooks is not None:
            sys.excepthook, threading.excepthook = self._hooks
            self._hooks = None
        self._close_faulthandler()

    def write(self, title: str, text: str = "") -> None:
        """One entry: the time, ``title`` and ``text`` below it. Never raises: a full or read-only disk must not stop the program."""
        if not self._on:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"\n{text.rstrip()}" if text.strip() else ""
        self._append(f"\n{ENTRY_SEPARATOR}\n{stamp}  {title}{body}\n")

    def delete(self) -> None:
        """Remove the file. faulthandler keeps it open, which Windows will not delete: it lets go first, and takes the new file at
        the next entry (opening it now would make an empty file at once)."""
        with self._lock:
            self._close_faulthandler()
            os.remove(self.path)

    # internals -------------------------------------------------------------------------------------------
    def _append(self, text: str) -> None:
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(text)
                trim_if_oversized(self.path, MAX_BYTES)
            except OSError:
                pass
            if self._on and self._fault_file is None:
                self._open_faulthandler()                    # after a delete

    def _excepthook(self, exc_type, exc_value, exc_tb) -> None:
        """An error nobody caught. Written down, and the program carries on (without a hook PyQt would end it on the spot)."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        self.write("Error in the program", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        if self.on_error is not None:
            try:
                self.on_error(f"{exc_type.__name__}: {exc_value}")
            except Exception:  # noqa: BLE001 - saying so must never make a second error
                pass

    def _thread_hook(self, args) -> None:
        if args.exc_type is SystemExit:
            return
        self._excepthook(args.exc_type, args.exc_value, args.exc_traceback)

    def _open_faulthandler(self) -> None:
        self._fault_before = faulthandler.is_enabled()          # someone else's (a console run, pytest) comes back afterwards
        try:
            self._fault_file = open(self.path, "a", encoding="utf-8")
            faulthandler.enable(file=self._fault_file)
        except (OSError, RuntimeError, ValueError):
            self._fault_file = None

    def _close_faulthandler(self) -> None:
        if self._fault_file is None:
            return
        try:
            faulthandler.disable()
            self._fault_file.close()
            if self._fault_before and sys.__stderr__ is not None:
                faulthandler.enable(file=sys.__stderr__)
        except (OSError, RuntimeError, ValueError):
            pass
        self._fault_file = None


def failed_items(result) -> str:
    """The lines of the items of an operation that failed: ``from -> to: error``, every one of them."""
    lines = []
    for r in getattr(result, "failed", None) or []:
        src, dst = r.op.src or "", r.op.dst or ""
        where = f"{src} -> {dst}" if src and dst else (src or dst)
        lines.append(f"  {where}: {r.error}")
    return "\n".join(lines)
