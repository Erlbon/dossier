"""The line under the panels where commands are typed (spec C4)."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLineEdit, QListWidget, QListWidgetItem

POPUP_ROWS = 10
MAX_HISTORY = 500                      # commands kept in memory for Up and the history list: a window open for weeks stays small


class ChoicePopup(QListWidget):
    """A short list that drops from the command line: Up and Down move, Enter or Tab or a click chooses, Esc closes. Any other key
    closes it and goes on to the line, so typing is never swallowed."""

    chosen = pyqtSignal(str)

    def __init__(self, owner: QLineEdit) -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.itemClicked.connect(lambda item: self._choose(item))

    def show_choices(self, items: list, current: int = 0, texts: list = None) -> None:
        """``items`` are what comes back when one is chosen; ``texts`` (the same length) are what the rows show."""
        self.clear()
        for i, item in enumerate(items):
            row = QListWidgetItem(texts[i] if texts else item)
            row.setData(Qt.ItemDataRole.UserRole, item)
            row.setToolTip(item)
            self.addItem(row)
        rows = min(len(items), POPUP_ROWS)
        height = self.sizeHintForRow(0) * rows + 2 * self.frameWidth() + 2 if items else 0
        width = max(self.owner.width() // 2, min(max(self.sizeHintForColumn(0) + 24, 200), self.owner.width()))
        origin = self.owner.mapToGlobal(self.owner.rect().bottomLeft())
        screen = QApplication.screenAt(origin)
        if screen is not None and origin.y() + height > screen.availableGeometry().bottom():          # no room below: above the line
            origin = self.owner.mapToGlobal(self.owner.rect().topLeft())
            origin.setY(origin.y() - height)
        self.setGeometry(origin.x(), origin.y(), width, height)
        self.setCurrentRow(max(0, min(current, len(items) - 1)))
        self.show()
        self.setFocus()

    def _choose(self, item) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        self.hide()
        self.owner.setFocus()
        self.chosen.emit(value)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            if self.currentItem() is not None:
                self._choose(self.currentItem())
        elif key == Qt.Key.Key_Escape:
            self.hide()
            self.owner.setFocus()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End):
            super().keyPressEvent(event)
        else:                                                       # typing: close, and let the line have the key
            self.hide()
            self.owner.setFocus()
            QApplication.sendEvent(self.owner, event)


class CommandLine(QLineEdit):
    """A line edit with this session's history on Up and Down (kept in memory only: what a user types is theirs, and a history file is
    opt-in), a list of the history under Ctrl+Down, completion of names under Ctrl+Space (the window finds the names on a thread and
    hands them to ``apply_completion``), Esc to clear and give the panel back its focus, and Tab to go back to the panel."""

    escape_pressed = pyqtSignal()
    tab_pressed = pyqtSignal()
    complete_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history: list = []
        self._pos = 0
        self._draft = ""
        self._range = (0, 0)                      # the part of the line a chosen completion replaces
        self._completion = None
        self.popup = ChoicePopup(self)
        self.popup.chosen.connect(self._chosen)
        self.setPlaceholderText("Type a command, or just start typing in a panel")
        self.setClearButtonEnabled(False)

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
            del self.history[:-MAX_HISTORY]
        self._pos = len(self.history)

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False

    # history list ----------------------------------------------------------------------------------------------------------------------
    def history_choices(self) -> list:
        """The history, newest first, each command once; with something typed, only the commands that contain it."""
        typed = self.text().strip().lower()
        seen: dict = {}
        for entry in reversed(self.history):
            if entry not in seen and (not typed or typed in entry.lower()):
                seen[entry] = True
        return list(seen)

    def show_history(self) -> int:
        """Drop the history list. Returns how many rows it has (0: nothing to show, no list)."""
        choices = self.history_choices()
        if not choices:
            return 0
        self._range = (0, len(self.text()))
        self._completion = None
        self.popup.show_choices(choices)
        return len(choices)

    # completion ------------------------------------------------------------------------------------------------------------------------
    def apply_completion(self, completion, text: str) -> int:
        """Put what ``completion`` found into the line. ``text`` is the line it was made for: if it has changed meanwhile nothing is done.
        Returns how many names fit (0 when none, or when the line changed)."""
        if text != self.text() or not completion.items:
            return 0
        self._completion = completion
        start, end = completion.start, completion.end
        if len(completion.items) == 1:
            body = completion.items[0]
            self._put(start, end, completion.render(body, closing=not body.endswith(os.sep)))
            return 1
        typed = self.text()[start:end].lstrip("\"'")
        common = completion.common()
        if len(common) > len(typed):
            end = self._put(start, end, completion.render(common))
        self._range = (start, end)
        shown = [os.path.basename(i.rstrip(os.sep + "/")) + (os.sep if i.endswith(os.sep) else "") or i for i in completion.items]
        self.popup.show_choices(completion.items, 0, shown)
        return len(completion.items)

    def _put(self, start: int, end: int, replacement: str) -> int:
        """Replace ``text[start:end]``; the cursor goes after it. Returns where the replacement ends."""
        whole = self.text()
        self.setText(whole[:start] + replacement + whole[end:])
        self.setCursorPosition(start + len(replacement))
        return start + len(replacement)

    def _chosen(self, value: str) -> None:
        if self._completion is None:                       # from the history: the whole line
            self.setText(value)
            self.setCursorPosition(len(value))
            self._pos = len(self.history)
            return
        start, end = self._range
        self._put(start, end, self._completion.render(value, closing=not value.endswith(os.sep)))

    # keys ------------------------------------------------------------------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and not (event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if key == Qt.Key.Key_Escape:
            self.clear()
            self._pos = len(self.history)
            self.escape_pressed.emit()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.tab_pressed.emit()
        elif ctrl and key == Qt.Key.Key_Space:
            self.complete_requested.emit()
        elif ctrl and key == Qt.Key.Key_Down:
            self.show_history()
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
