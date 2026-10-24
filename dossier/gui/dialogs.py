"""The questions and messages of the commander, in one place so tests can replace them."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QDialog, QFileDialog, QInputDialog, QCheckBox, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                             QVBoxLayout, QWidget)

from ..core.progress import RateMeter, human_duration
from ..core.sizefmt import human_size
from .owned_dialog import OwnedDialog


BYTES_SHOWN = 1 << 20          # below this a progress total is a count of steps, not bytes


def _size(n: float) -> str:
    return human_size(n, long=True, whole_from=10)


class ProgressBox:
    """A progress dialog that only appears when the work takes a moment (spec: slow things show
    progress). Wraps QProgressDialog so the rest of the code never touches it."""

    def __init__(self, parent: QWidget, title: str, on_cancel: Callable[[], None]) -> None:
        self._dlg = QProgressDialog(title, "Cancel", 0, 1000, parent)
        self._dlg.setWindowTitle(title)
        self._dlg.setMinimumDuration(400)
        self._dlg.setMinimumWidth(440)             # the text changes all the time: keep the box from jumping in size
        self._dlg.setAutoClose(False)
        self._dlg.setAutoReset(False)
        self._dlg.setLabelText(title)
        label = self._dlg.findChild(QWidget, "qt_progress_label") or None
        if label is not None and hasattr(label, "setWordWrap"):
            label.setWordWrap(True)          # labels word-wrap (house rule)
        self._dlg.canceled.connect(on_cancel)
        self._dlg.setValue(0)
        self._title = title
        self._meter = RateMeter()

    def indeterminate(self) -> None:
        """The work has no known size: the bar just moves."""
        self._dlg.setRange(0, 0)

    detail = ""                  # the item being worked on, set by the window
    plan_bytes = None            # the bytes the plan moves; the bar's own total also counts reading back and flushing

    def update(self, done: int, total: int) -> None:
        if total > 0:
            self._dlg.setValue(min(1000, int(1000 * done / total)))
        nominal = self.plan_bytes or total
        if total > 0 and nominal >= BYTES_SHOWN:       # a count of items has no speed worth showing
            got = int(nominal * min(done, total) / total) if self.plan_bytes else done
            self._meter.add(got)
            self._dlg.setLabelText(self.status_text(got, nominal))
        elif self.detail:
            self._dlg.setLabelText(self._title + chr(10) + self.detail)

    def status_text(self, done: int, total: int) -> str:
        """What the box says: the item, the size done of the whole and what remains, then speed and time left."""
        dot = "  " + chr(0xB7) + "  "
        lines = [self._title]
        if self.detail:
            lines.append(self.detail)
        lines.append(dot.join([f"{_size(done)} of {_size(total)}", f"{_size(max(0, total - done))} remaining"]))
        rate = self._meter.speed()
        if rate > 0:
            parts = [f"{_size(rate)}/s"]
            left = human_duration(self._meter.seconds_left(done, total))
            if left:
                parts.append(f"{left} left")
            lines.append(dot.join(parts))
        return chr(10).join(lines)

    def close(self) -> None:
        self._dlg.canceled.disconnect()
        self._dlg.close()
        self._dlg.deleteLater()


class Dialogs:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent

    def info(self, title: str, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, self.parent)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()

    def confirm(self, title: str, text: str, ok_label: str = "OK") -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self.parent)
        ok = box.addButton(ok_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return box.clickedButton() is ok

    def confirm_transfer(self, title: str, text: str, ok_label: str, verify: bool) -> Optional[bool]:
        """Confirm a copy or move with the choice to read the copies back and compare them. Returns None when
        cancelled, otherwise whether to verify."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self.parent)
        check = QCheckBox("Verify the copies afterwards (reads everything back and compares it)")
        check.setChecked(verify)
        box.setCheckBox(check)
        ok = box.addButton(ok_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return check.isChecked() if box.clickedButton() is ok else None

    def ask_resume(self, lines: list) -> str:
        """Unfinished operations from the last run: ``continue`` them, ``discard`` the list, or ``later`` (leave it)."""
        shown = lines[:8] + ([f"and {len(lines) - 8} more"] if len(lines) > 8 else [])
        box = QMessageBox(QMessageBox.Icon.Question, "Unfinished operations",
                          "These were not finished when the program was closed:" + chr(10) * 2 + chr(10).join(shown) + chr(10) * 2 +
                          "Continue them? What was already copied is not copied again.", parent=self.parent)
        go = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        drop = box.addButton("Discard the list", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(go)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return "continue" if box.clickedButton() is go else "discard" if box.clickedButton() is drop else "later"

    def ask_save(self, name: str) -> str:
        """Unsaved changes on closing: ``save``, ``discard`` or ``cancel``."""
        box = QMessageBox(QMessageBox.Icon.Question, "Unsaved changes", f"Save the changes to {name}?", parent=self.parent)
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return "save" if box.clickedButton() is save else "discard" if box.clickedButton() is discard else "cancel"

    def ask_changed_on_disk(self, name: str) -> Optional[str]:
        """The file changed under the editor: ``overwrite`` it, ``reload`` it, or None to cancel."""
        box = QMessageBox(QMessageBox.Icon.Warning, "File changed", f"{name} was changed by another program after "
                          "you opened it.", parent=self.parent)
        over = box.addButton("Overwrite with my version", QMessageBox.ButtonRole.DestructiveRole)
        reload_ = box.addButton("Reload from disk", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return "overwrite" if box.clickedButton() is over else "reload" if box.clickedButton() is reload_ else None

    def ask_save_path(self, default: str) -> Optional[str]:
        path, _filter = QFileDialog.getSaveFileName(self.parent, "Save As", default)
        return path or None

    def show_output(self, title: str, text: str) -> None:
        """The captured output of a command, in a resizable read-only box."""
        dlg = OwnedDialog(self.parent)
        dlg.setWindowTitle(title)
        dlg.resize(760, 420)
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        layout = QVBoxLayout(dlg)
        layout.addWidget(edit)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def ask_text(self, title: str, label: str, default: str = "") -> Optional[str]:
        text, ok = QInputDialog.getText(self.parent, title, label, text=default)
        return text if ok else None

    def ask_conflicts(self, rows: list, where: str = "") -> Optional[dict]:
        """One answer per conflict: {step number: Resolution}, or None to cancel."""
        from .conflict_dialog import ConflictDialog
        dlg = ConflictDialog(self.parent, rows, where)
        return dlg.answers() if dlg.exec() == QDialog.DialogCode.Accepted else None

    def ask_error(self, text: str) -> str:
        """A file could not be copied or moved: ``retry``, ``skip``, ``skip_all`` or ``abort``."""
        box = QMessageBox(QMessageBox.Icon.Warning, "Could not finish", text, parent=self.parent)
        buttons = {box.addButton("Try again", QMessageBox.ButtonRole.AcceptRole): "retry",
                   box.addButton("Skip", QMessageBox.ButtonRole.RejectRole): "skip",
                   box.addButton("Skip all errors", QMessageBox.ButtonRole.RejectRole): "skip_all",
                   box.addButton("Stop", QMessageBox.ButtonRole.DestructiveRole): "abort"}
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)       # freed after use, not kept by the window for good
        box.exec()
        return buttons.get(box.clickedButton(), "skip")

    def make_progress(self, title: str, on_cancel: Callable[[], None]) -> ProgressBox:
        return ProgressBox(self.parent, title, on_cancel)
