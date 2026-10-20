"""The opt-in slowness log of the window: the menu actions, the heartbeat, and what the user last did (by name)."""
from __future__ import annotations

import os

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

from ..core.stallwatch import StallWatch
from ..core.worker import JobState


class _LastInput(QObject):
    """Remembers what the user last did, as a name: which key (never the letter typed) or a mouse click."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = ""

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            printable = bool(event.text()) and event.text().isprintable() and not (
                mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
            self.text = "a typed character" if printable else QKeySequence(int(mods.value) | key).toString()
        elif kind == QEvent.Type.MouseButtonPress:
            self.text = "a mouse click"
        return False


class StallLogMixin:
    """Part of ``MainWindow``: switching the log on and off, opening and deleting it."""

    # the slowness log (opt-in) --------------------------------------------------------------------------
    @property
    def stall_log_path(self) -> str:
        return os.path.join(os.path.dirname(self.settings.fileName()), "slowness.log")

    def _stall_context(self) -> str:
        parts = []
        if getattr(self, "_last_input", None) is not None and self._last_input.text:
            parts.append("last input: " + self._last_input.text)
        waiting = sum(1 for j in self._jobs if j.state is JobState.QUEUED)
        if self._jobs:
            parts.append(f"operations: 1 running{', ' + str(waiting) + ' waiting' if waiting else ''}")
        parts.append(f"marked: {len(self.selection)}")
        return "  |  ".join(parts)

    def set_stall_log(self, on: bool) -> None:
        """Start or stop watching the window for stalls. Off by default; nothing is recorded while it is off."""
        self.settings.setValue("debug/stall_log", "true" if on else "false")
        watch = getattr(self, "_stall_watch", None)
        if watch is not None:
            watch.stop()
            self._stall_watch = None
            self._heartbeat.stop()
            QApplication.instance().removeEventFilter(self._last_input)
        if on:
            self._last_input = _LastInput(self)
            QApplication.instance().installEventFilter(self._last_input)
            self._stall_watch = StallWatch(self.stall_log_path, context=self._stall_context)
            self._heartbeat = QTimer(self)
            self._heartbeat.setInterval(40)
            self._heartbeat.timeout.connect(self._stall_watch.beat)
            self._stall_watch.start()
            self._heartbeat.start()

    def open_stall_log(self) -> None:
        if not os.path.isfile(self.stall_log_path):
            self.dialogs.info("Slowness Log", "Nothing has been recorded yet. Switch on Record Slow Moments, use "
                                              "the program, and the moments it stalls for more than 200 ms are written here.")
            return
        self.edit_file(self.stall_log_path)

    def delete_stall_log(self) -> None:
        if not os.path.isfile(self.stall_log_path):
            self._say("There is no slowness log")
            return
        if self.dialogs.confirm("Delete the Slowness Log", "Delete the record of slow moments?", "Delete"):
            for editor in list(self.editors):
                if os.path.normcase(editor.doc.path) == os.path.normcase(self.stall_log_path):
                    editor.close()
            try:
                os.remove(self.stall_log_path)
                self._say("Slowness log deleted")
            except OSError as e:
                self.dialogs.info("Slowness Log", f"Could not delete it: {e.strerror or e}")
