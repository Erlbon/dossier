"""The line under the panels where commands are typed (spec C4)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLineEdit


class CommandLine(QLineEdit):
    """A line edit with this session's history on Up and Down (kept in memory only: what a user types
    is theirs, and a history file is opt-in), Esc to clear and give the panel back its focus, and Tab
    to go back to the panel."""

    escape_pressed = pyqtSignal()
    tab_pressed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history: list = []
        self._pos = 0
        self._draft = ""
        self.setPlaceholderText("Type a command, or just start typing in a panel")
        self.setClearButtonEnabled(False)

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._pos = len(self.history)

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.clear()
            self._pos = len(self.history)
            self.escape_pressed.emit()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.tab_pressed.emit()
        elif key == Qt.Key.Key_Up and self.history:
            if self._pos == len(self.history):
                self._draft = self.text()
            self._pos = max(0, self._pos - 1)
            self.setText(self.history[self._pos])
        elif key == Qt.Key.Key_Down and self.history:
            self._pos = min(len(self.history), self._pos + 1)
            self.setText(self._draft if self._pos == len(self.history) else self.history[self._pos])
        else:
            super().keyPressEvent(event)
