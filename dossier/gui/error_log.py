"""The opt-in error log of the window (core/error_log.py): the Help menu's switch, opening and deleting it."""
from __future__ import annotations

import os

from ..core.error_log import ErrorLog
from ..core.version import APP_NAME, APP_VERSION
from .log_files import delete_log, open_log


class ErrorLogMixin:
    """Part of ``MainWindow``. ``self.error_log.write(...)`` may be called from anywhere: it does nothing while the log is off."""

    @property
    def error_log_path(self) -> str:
        return os.path.join(os.path.dirname(self.settings.fileName()), "errors.log")

    @property
    def error_log(self) -> ErrorLog:
        log = getattr(self, "_error_log", None)
        if log is None:
            log = self._error_log = ErrorLog(self.error_log_path, f"{APP_NAME} {APP_VERSION}", on_error=self._error_caught)
        return log

    def _error_caught(self, text: str) -> None:
        """Any thread: an error in the program was written down; the status line says so."""
        self.dispatcher(lambda: self._say(f"Something went wrong ({text}); it is in Help > Error Log"))

    def set_error_log(self, on: bool) -> None:
        """Start or stop writing errors down. Off by default; nothing is recorded while it is off."""
        self.settings.setValue("debug/error_log", "true" if on else "false")
        self.error_log.start() if on else self.error_log.stop()

    def open_error_log(self) -> None:
        open_log(self, self.error_log_path, "Error Log", "Nothing has been recorded yet. Switch on Record Errors, and failed copies, "
                                                         "moves and deletes, a network that went away and errors in Dossier itself "
                                                         "are written here.")

    def delete_error_log(self) -> None:
        delete_log(self, self.error_log_path, "Error Log", "Delete the record of errors?",
                   remove=lambda _path: self.error_log.delete())
