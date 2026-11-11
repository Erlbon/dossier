"""The F5 / F6 box: what is copied or moved, to where (the other panel's folder, which can be changed), and how.

The destination can be a folder below it (``backup`` means ``backup`` inside the other panel's folder), a typed path (made when it is
missing), or for one item a new name (copy as). The options are those of the spec's F3: only files whose names match a pattern,
everything into one folder (flatten, copies only), and keep the newer file when one is already there. The window reads ``answer()``
and plans again when it differs from the plan the box was shown for.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QDir
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtWidgets import (QCheckBox, QCompleter, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QPlainTextEdit,
                             QVBoxLayout)

from .owned_dialog import OwnedDialog

ONLY_HINT = "*.jpg;*.png   or  *.log !debug*   (empty: everything)"


@dataclass
class TransferAnswer:
    dest: str                       # as typed: the window works out what it means
    verify: bool = False
    only: str = ""                  # copy only files matching this
    flatten: bool = False           # every file straight into the destination
    newer: bool = False             # an existing file is replaced only by a newer one, else left
    skip_same: bool = False         # a file already there and the same is left out (copy plan step 5, "finish the job")


class TransferDialog(OwnedDialog):
    def __init__(self, parent, title: str, summary: str, ok_label: str, dest: str, verify: bool, move: bool,
                 local_completion: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit(summary)
        text.setReadOnly(True)
        text.setMaximumHeight(170)
        layout.addWidget(text)
        form = QFormLayout()
        self.dest = QLineEdit(dest)
        self.dest.setToolTip("A folder (made when it is missing), a folder name inside the other panel's folder, "
                             "or for one item a new name")
        if local_completion:
            model = QFileSystemModel(self.dest)                  # reads folders on its own thread: typing never waits for a disk
            model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
            model.setRootPath("")
            completer = QCompleter(model, self.dest)
            self.dest.setCompleter(completer)
        form.addRow("Move to" if move else "Copy to", self.dest)
        layout.addLayout(form)
        how = QGroupBox("Options")
        f = QFormLayout(how)
        self.only = QLineEdit(how)
        self.only.setPlaceholderText(ONLY_HINT)
        self.flatten = QCheckBox("Put every file straight into the destination (no folders)", how)
        self.skip_same = QCheckBox("Skip what is already there and the same (size and time; with Verify on, the content)")
        self.skip_same.setToolTip("To finish a copy that stopped: only what is missing or changed is copied, with no questions")
        self.newer = QCheckBox("Where a file is there already, replace it only with a newer one")
        self.verify = QCheckBox("Verify the copies afterwards (reads everything back and compares it)")
        self.verify.setChecked(verify)
        self.skip_same.setParent(how)
        if move:                                                  # a move takes everything as it is
            self.only.hide()
            self.flatten.hide()
            self.skip_same.hide()
        else:
            f.addRow("Only files named", self.only)
            f.addRow("", self.flatten)
            f.addRow("", self.skip_same)
        f.addRow("", self.newer)
        f.addRow("", self.verify)
        layout.addWidget(how)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.addButton(ok_label, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Enter means Copy (or Move). Set only once the box is in the dialog: a default set before that is lost, and Qt then made
        # Cancel (the first button) the default, so the first Enter cancelled and F5 had to be pressed again (2026-11-11).
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)
        ok.setDefault(True)
        self.dest.setFocus()
        self.dest.selectAll()

    def answer(self) -> TransferAnswer:
        return TransferAnswer(self.dest.text().strip(), self.verify.isChecked(), self.only.text().strip(), self.flatten.isChecked(),
                              self.newer.isChecked(), self.skip_same.isChecked() and not self.skip_same.isHidden())

    def _accept(self) -> None:
        if not self.dest.text().strip():
            self.problem.setText("Say where to.")
            return
        self.accept()
