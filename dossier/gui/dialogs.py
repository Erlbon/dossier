"""The questions and messages of the commander, in one place so tests can replace them."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..core.progress import RateMeter, human_duration
from ..core.sizefmt import human_size
from .owned_dialog import OwnedDialog


BYTES_SHOWN = 1 << 20          # below this a progress total is a count of steps, not bytes


def stem_length(name: str, is_dir: bool = False) -> int:
    """How much of ``name`` a rename box selects: all of a folder's name, a file's name without its extension (``report`` of
    ``report.pdf``; all of ``.gitignore``, whose dot starts the name)."""
    dot = name.rfind(".")
    return len(name) if is_dir or dot <= 0 else dot


def _size(n: float) -> str:
    return human_size(n, long=True, whole_from=10)


DOT = "  " + chr(0xB7) + "  "


class _ProgressWindow(OwnedDialog):
    """The window of a ``ProgressBox``. Esc and the close button cancel, as Cancel does; closing it because the work is over does not."""

    def __init__(self, parent: Optional[QWidget], on_cancel: Callable[[], None]) -> None:
        super().__init__(parent)
        self._on_cancel = on_cancel
        self.ending = False

    def reject(self) -> None:
        if not self.ending:
            self._on_cancel()
        super().reject()


def _line(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setWordWrap(True)                        # labels word-wrap (house rule)
    return label


def _bar(parent: QWidget) -> QProgressBar:
    bar = QProgressBar(parent)
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    return bar


class ProgressBox:
    """A progress box that only appears when the work takes a moment (spec: slow things show progress): what is being done, a bar
    for the file when a big one is copied (with its own speed and time left), a bar for the whole job with the bytes done, what
    remains, the speed and the time left, and Pause (when the window can pause the work) and Cancel (decided 2026-11-06, option R).
    Big files go one at a time, so "this file" is one file; small files go several at once and get no file bar."""

    detail = ""                  # the item being worked on, set by the window
    plan_bytes = None            # the bytes the plan moves; the bar's own total also counts reading back and flushing

    def __init__(self, parent: Optional[QWidget], title: str, on_cancel: Callable[[], None],
                 on_pause: Optional[Callable[[], None]] = None) -> None:
        dlg = self._dlg = _ProgressWindow(parent, on_cancel)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(440)                   # the text changes all the time: keep the box from jumping in size
        layout = QVBoxLayout(dlg)
        self._top, self._file_label, self._job_label, self._speed_label = (_line(dlg) for _ in range(4))
        self._file_bar, self._bar = _bar(dlg), _bar(dlg)
        for widget in (self._top, self._file_label, self._file_bar, self._job_label, self._bar, self._speed_label):
            layout.addWidget(widget)
        for widget in (self._file_label, self._file_bar, self._job_label, self._speed_label):
            widget.hide()
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.pause_button: Optional[QPushButton] = None
        if on_pause is not None:
            self.pause_button = QPushButton("Pause", dlg)
            self.pause_button.clicked.connect(on_pause)
            buttons.addWidget(self.pause_button)
        cancel = QPushButton("Cancel", dlg)
        cancel.clicked.connect(dlg.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._title = title
        self._top.setText(title)
        self._meter, self._file_meter = RateMeter(), RateMeter()
        self._file_name: Optional[str] = None
        self._file_at = (0, 0)
        self._paused = False
        self._speed = ""
        self._closed = False
        self._timer = QTimer(dlg)                  # shown only when the work takes a moment
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._show)
        self._timer.start()

    def _show(self) -> None:
        if not self._closed:
            self._dlg.show()

    def indeterminate(self) -> None:
        """The work has no known size: the bar just moves."""
        self._bar.setRange(0, 0)

    def update(self, done: int, total: int) -> None:
        if total > 0:
            self._bar.setValue(min(1000, int(1000 * done / total)))
        self._top.setText(self._title + (chr(10) + self.detail if self.detail else ""))
        nominal = self.plan_bytes or total
        if total > 0 and nominal >= BYTES_SHOWN:       # a count of items has no speed worth showing
            got = int(nominal * min(done, total) / total) if self.plan_bytes else done
            self._meter.add(got)
            self._job_label.setText(self._job_line(got, nominal))
            self._job_label.show()
            self._speed = self._speed_line(self._meter, got, nominal)
        self._show_speed()

    @staticmethod
    def _job_line(done: int, total: int) -> str:
        return DOT.join(["Whole job", f"{_size(done)} of {_size(total)}", f"{_size(max(0, total - done))} remaining"])

    @staticmethod
    def _speed_line(meter: RateMeter, done: int, total: int) -> str:
        rate = meter.speed()
        if rate <= 0:
            return ""
        left = human_duration(meter.seconds_left(done, total))
        return DOT.join([f"{_size(rate)}/s"] + ([f"{left} left"] if left else []))

    def _show_speed(self) -> None:
        text = "Paused" if self._paused else self._speed
        self._speed_label.setText(text)
        self._speed_label.setVisible(bool(text))

    def status_text(self, done: int, total: int) -> str:
        """What the box says of the whole job: the item, the size done of the whole and what remains, then speed and time left."""
        lines = [self._title] + ([self.detail] if self.detail else []) + [self._job_line(done, total)]
        speed = self._speed_line(self._meter, done, total)
        return chr(10).join(lines + ([speed] if speed else []))

    def text(self) -> str:
        """Everything the box says about the whole job, line by line (the file's line is ``file_text``)."""
        parts = [self._top.text()] + [w.text() for w in (self._job_label, self._speed_label) if not w.isHidden()]
        return chr(10).join(p for p in parts if p)

    # the file bar --------------------------------------------------------------------------------------------------------------------
    def set_file(self, name: str, done: int, size: int) -> None:
        """A big file is being copied: its own bar, bytes, speed and time left."""
        if name != self._file_name:
            self._file_name = name
            self._file_meter.reset()               # a new file: its own speed, not the last one's
        self._file_meter.add(done)
        if size > 0:
            self._file_bar.setValue(min(1000, int(1000 * done / size)))
        self._file_at = (done, size)
        self._show_file()
        self._file_label.show()
        self._file_bar.show()

    def _show_file(self) -> None:
        done, size = self._file_at
        speed = "" if self._paused else self._speed_line(self._file_meter, done, size)     # paused: no speed that is not there
        self._file_label.setText(DOT.join(["This file", f"{_size(done)} of {_size(size)}"] + ([speed] if speed else [])))

    def clear_file(self) -> None:
        """No big file now (small ones, or other steps): no file bar."""
        self._file_name = None
        self._file_label.hide()
        self._file_bar.hide()

    def file_shown(self) -> bool:
        return not self._file_bar.isHidden()

    def file_text(self) -> str:
        return self._file_label.text()

    # pause ---------------------------------------------------------------------------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        """Say whether the work is paused (the button turns into Resume)."""
        self._paused = paused
        if self.pause_button is not None:
            self.pause_button.setText("Resume" if paused else "Pause")
        self._show_speed()
        if self._file_name is not None:
            self._show_file()

    def close(self) -> None:
        self._closed = True
        self._timer.stop()
        self._dlg.ending = True                    # the work is over: closing is not a cancel
        self._dlg.close()
        self._dlg.deleteLater()


class Dialogs:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent

    def info(self, title: str, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok, self.parent)
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good

    def confirm(self, title: str, text: str, ok_label: str = "OK") -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self.parent)
        ok = box.addButton(ok_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(ok)
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
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
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
        return check.isChecked() if box.clickedButton() is ok else None

    def ask_transfer(self, title: str, text: str, ok_label: str, dest: str, verify: bool, move: bool, local: bool = True):
        """The F5 / F6 box: a ``TransferAnswer`` (where to, verify, the options), or None when cancelled."""
        from .transfer_dialog import TransferDialog
        dlg = TransferDialog(self.parent, title, text, ok_label, dest, verify, move, local_completion=local)
        return dlg.answer() if dlg.exec() == QDialog.DialogCode.Accepted else None

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
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
        return "continue" if box.clickedButton() is go else "discard" if box.clickedButton() is drop else "later"

    def ask_save(self, name: str) -> str:
        """Unsaved changes on closing: ``save``, ``discard`` or ``cancel``."""
        box = QMessageBox(QMessageBox.Icon.Question, "Unsaved changes", f"Save the changes to {name}?", parent=self.parent)
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
        return "save" if box.clickedButton() is save else "discard" if box.clickedButton() is discard else "cancel"

    def ask_changed_on_disk(self, name: str) -> Optional[str]:
        """The file changed under the editor: ``overwrite`` it, ``reload`` it, or None to cancel."""
        box = QMessageBox(QMessageBox.Icon.Warning, "File changed", f"{name} was changed by another program after "
                          "you opened it.", parent=self.parent)
        over = box.addButton("Overwrite with my version", QMessageBox.ButtonRole.DestructiveRole)
        reload_ = box.addButton("Reload from disk", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
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

    def ask_name(self, title: str, label: str, default: str, is_dir: bool = False) -> Optional[str]:
        """A name, with the part before the extension selected, so typing keeps the extension (F2, as in Explorer)."""
        dlg = QInputDialog(self.parent)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setTextValue(default)
        edit = dlg.findChild(QLineEdit)
        if edit is not None:
            select = QTimer(dlg)                                 # once the box is shown (showing it selects the whole text)
            select.setSingleShot(True)
            select.timeout.connect(lambda: edit.setSelection(0, stem_length(default, is_dir)))
            select.start(0)
        return dlg.textValue() if dlg.exec() == QDialog.DialogCode.Accepted else None

    def show_diff(self, title: str, header: str, rows: list) -> None:
        """Two text files side by side, in a window of its own (not modal: the commander stays usable)."""
        from .text_diff import TextDiffWindow
        win = TextDiffWindow(self.parent, title, header, rows)
        win.show()

    def ask_unpack_many(self, count: int, here: str) -> Optional[str]:
        """Several archives to unpack: ``each`` into a folder of its own name beside it, ``here`` all into ``here``, or None."""
        box = QMessageBox(QMessageBox.Icon.Question, "Unpack", f"Unpack {count} archives:", parent=self.parent)
        each = box.addButton("Each into a Folder of Its Own Name", QMessageBox.ButtonRole.AcceptRole)
        into = box.addButton(f"All into {here}", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(each)
        box.exec()
        box.deleteLater()
        return "each" if box.clickedButton() is each else "here" if box.clickedButton() is into else None

    def ask_mark(self, title: str, pattern: str) -> Optional[tuple]:
        """Mark by Pattern: ``(pattern, criteria)`` (size, date, attributes), or None when cancelled."""
        from .mark_dialog import ask_mark
        return ask_mark(self.parent, title, pattern)

    def ask_program(self, title: str, current: str = "") -> Optional[str]:
        """A program file to start, or None when cancelled."""
        path, _filter = QFileDialog.getOpenFileName(self.parent, title, current, "Programs (*.exe *.bat *.cmd *.com);;All files (*)")
        return path or None

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
        box.exec()
        box.deleteLater()                                      # freed once the answer has been read, not kept by the window for good
        return buttons.get(box.clickedButton(), "skip")

    def make_progress(self, title: str, on_cancel: Callable[[], None], on_pause: Optional[Callable[[], None]] = None) -> ProgressBox:
        return ProgressBox(self.parent, title, on_cancel, on_pause)
