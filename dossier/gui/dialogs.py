"""The questions and messages of the commander, in one place so tests can replace them."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtWidgets import QInputDialog, QMessageBox, QProgressDialog, QWidget

from ..core.ops import Resolution


class ProgressBox:
    """A progress dialog that only appears when the work takes a moment (spec: slow things show
    progress). Wraps QProgressDialog so the rest of the code never touches it."""

    def __init__(self, parent: QWidget, title: str, on_cancel: Callable[[], None]) -> None:
        self._dlg = QProgressDialog(title, "Cancel", 0, 1000, parent)
        self._dlg.setWindowTitle(title)
        self._dlg.setMinimumDuration(400)
        self._dlg.setAutoClose(False)
        self._dlg.setAutoReset(False)
        self._dlg.setLabelText(title)
        label = self._dlg.findChild(QWidget, "qt_progress_label") or None
        if label is not None and hasattr(label, "setWordWrap"):
            label.setWordWrap(True)          # labels word-wrap (house rule)
        self._dlg.canceled.connect(on_cancel)
        self._dlg.setValue(0)

    def update(self, done: int, total: int) -> None:
        if total > 0:
            self._dlg.setValue(min(1000, int(1000 * done / total)))

    def close(self) -> None:
        self._dlg.canceled.disconnect()
        self._dlg.close()
        self._dlg.deleteLater()


class Dialogs:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent

    def info(self, title: str, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, self.parent)
        box.exec()

    def confirm(self, title: str, text: str, ok_label: str = "OK") -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self.parent)
        ok = box.addButton(ok_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    def ask_text(self, title: str, label: str, default: str = "") -> Optional[str]:
        text, ok = QInputDialog.getText(self.parent, title, label, text=default)
        return text if ok else None

    def ask_conflict(self, text: str) -> Optional[Resolution]:
        """One answer for every conflict of the plan; None means cancel."""
        box = QMessageBox(QMessageBox.Icon.Warning, "Items already exist", text, parent=self.parent)
        choices = {}
        for res in (Resolution.OVERWRITE, Resolution.OVERWRITE_IF_NEWER, Resolution.SKIP, Resolution.KEEP_BOTH):
            choices[box.addButton(res.value.capitalize(), QMessageBox.ButtonRole.AcceptRole)] = res
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return choices.get(box.clickedButton())

    def make_progress(self, title: str, on_cancel: Callable[[], None]) -> ProgressBox:
        return ProgressBox(self.parent, title, on_cancel)
