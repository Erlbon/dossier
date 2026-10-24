"""Settings > Quarantine..., Tools > Move to Quarantine / Put Back from Quarantine, Go > Quarantine Folder: the window for ``core/quarantine.py``.

A file moved to the quarantine keeps its place in the folder tree and can be put back; nothing is deleted. Moving is an ordinary move plan
(conflict dialog, progress, Cancel, Ctrl+Z on one drive), planned on a thread and confirmed once with the folder it goes to.
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                             QVBoxLayout)

from ..core import quarantine
from ..core.ops import Kind
from ..core.platform import IS_WINDOWS
from .background import run_in_background

KEY_MODE, KEY_FOLDER = "quarantine/mode", "quarantine/folder"


def read_settings(settings) -> quarantine.Settings:
    return quarantine.Settings(str(settings.value(KEY_MODE, quarantine.DRIVE) or quarantine.DRIVE),
                               str(settings.value(KEY_FOLDER, "") or "")).cleaned()


def write_settings(settings, values: quarantine.Settings) -> None:
    values = values.cleaned()
    settings.setValue(KEY_MODE, values.mode)
    settings.setValue(KEY_FOLDER, values.folder)


class QuarantineDialog(QDialog):
    def __init__(self, parent, values: quarantine.Settings, example: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quarantine")
        self.setMinimumWidth(560)
        self.example = example
        layout = QVBoxLayout(self)
        note = QLabel("The quarantine is where you move files you want out of the way without deleting them: a damaged zip, an empty file, "
                      "a leftover. A file keeps its place in the folder tree there, so it can be put back. Nothing is deleted or overwritten, "
                      "and the quarantine is never emptied for you.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.on_drive = QRadioButton("On each drive, in " + os.path.join("<drive>:" + os.sep if IS_WINDOWS else "<drive>" + os.sep, *quarantine.SUBFOLDER)
                                     + "  (default: moving stays on the drive, so it is instant)")
        self.one_folder = QRadioButton("One folder for everything (each drive gets a folder of its own inside it)")
        (self.one_folder if values.mode == quarantine.FOLDER else self.on_drive).setChecked(True)
        layout.addWidget(self.on_drive)
        layout.addWidget(self.one_folder)
        row = QHBoxLayout()
        self.folder = QLineEdit(values.folder)
        self.folder.setPlaceholderText("the folder, for example E:" + os.sep + "Quarantine")
        self.browse = QPushButton("Browse...")
        self.browse.setAutoDefault(False)
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(self.browse)
        form = QFormLayout()
        form.addRow("Folder", row)
        layout.addLayout(form)
        self.shown = QLabel()
        self.shown.setWordWrap(True)
        layout.addWidget(self.shown)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.defaults = QPushButton("Back to the default")
        self.defaults.setAutoDefault(False)
        buttons.addButton(self.defaults, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.defaults.clicked.connect(self._reset)
        layout.addWidget(buttons)
        for widget in (self.on_drive, self.one_folder):
            widget.toggled.connect(self._changed)
        self.folder.textChanged.connect(self._changed)
        self._changed()

    def values(self) -> quarantine.Settings:
        return quarantine.Settings(quarantine.FOLDER if self.one_folder.isChecked() else quarantine.DRIVE, self.folder.text()).cleaned()

    def _reset(self) -> None:
        self.on_drive.setChecked(True)
        self.folder.clear()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose the quarantine folder", self.folder.text())
        if path:
            self.folder.setText(os.path.normpath(path))
            self.one_folder.setChecked(True)

    def _changed(self, *_args) -> None:
        self.folder.setEnabled(self.one_folder.isChecked())
        self.browse.setEnabled(self.one_folder.isChecked())
        values = self.values()
        if self.one_folder.isChecked() and not self.folder.text().strip():
            self.shown.setText("Choose the folder, or the default (a folder on each drive) is used.")
            return
        try:
            where = quarantine.destination(self.example, values) if self.example else ""
        except quarantine.QuarantineError:
            where = ""
        self.shown.setText(f"For example, {self.example}{chr(10)}goes to {where}" if where else "")


class QuarantineMixin:
    """Part of ``MainWindow``."""

    def quarantine_settings(self) -> quarantine.Settings:
        return read_settings(self.settings)

    def open_quarantine_settings(self) -> None:
        panel = self.active
        example = ""
        if not panel.is_home and not panel.path.startswith(("zip:", "flat:", "found:")) and "://" not in panel.path:
            entry = panel.current_entry()
            example = entry.path if entry is not None and entry.name != ".." else os.path.join(panel.path, "example.txt")
        dialog = QuarantineDialog(self, self.quarantine_settings(), example)
        self._show_quarantine_dialog(dialog)
        if dialog.result() == QDialog.DialogCode.Accepted:
            write_settings(self.settings, dialog.values())
            self._say("Quarantine: " + ("on each drive, in " + os.path.join("<drive>", *quarantine.SUBFOLDER) if dialog.values().mode == quarantine.DRIVE
                                        else "all in " + dialog.values().folder))

    def _show_quarantine_dialog(self, dialog) -> None:           # a seam for tests
        dialog.exec()

    # moving ----------------------------------------------------------------------------------------------------------------------------
    def move_to_quarantine(self) -> None:
        paths = self._local_targets()
        if not paths:
            self._say("Move to quarantine: mark items or put the cursor on one, on a drive of this computer")
            return
        settings = self.quarantine_settings()
        self._plan_in_background("Preparing the quarantine", lambda watch: quarantine.plan_quarantine(self.fs, paths, settings),
                                 lambda plan: self._quarantine_planned(plan, paths))

    def _quarantine_planned(self, plan, paths: list) -> None:
        moves = [op for op in plan.ops if op.kind in (Kind.MOVE, Kind.FINISH_MOVE)]
        if plan.blocking or not moves:
            self._nothing_to_move("Move to Quarantine", plan)
            return
        where = os.path.dirname(moves[0].dst)
        left_out = [w for w in plan.warnings if w.startswith("left out")]
        text = (f"Move {len([o for o in plan.ops if o.kind is Kind.MOVE]):,} item(s) to the quarantine folder?{chr(10)}{chr(10)}{where}{chr(10)}{chr(10)}"
                "They keep their place in the folder tree there and nothing is deleted. Tools > Put Back from Quarantine brings them back."
                + (f"{chr(10)}{chr(10)}{len(left_out)} item(s) are left out (already in the quarantine, or not on a drive of this computer)." if left_out else ""))
        if not self.dialogs.confirm("Move to Quarantine", text, "Move"):
            return
        ready = self._settle(plan)
        if ready is not None:
            self._run(ready, unmark=paths)

    def _nothing_to_move(self, title: str, plan) -> None:
        """Say why a quarantine plan cannot run: what blocks it, or what was left out."""
        reasons = list(plan.blocking) + list(plan.warnings)
        self.dialogs.info(title, chr(10).join(reasons[:8]) if reasons else "Nothing to move.")

    def put_back_from_quarantine(self) -> None:
        paths = self._local_targets()
        if not paths:
            self._say("Put back: mark items or put the cursor on one, in the quarantine folder")
            return
        settings = self.quarantine_settings()
        self._plan_in_background("Preparing to put back", lambda watch: quarantine.plan_put_back(self.fs, paths, settings),
                                 lambda plan: self._put_back_planned(plan, paths))

    def _put_back_planned(self, plan, paths: list) -> None:
        if plan.blocking or not [o for o in plan.ops if o.kind in (Kind.MOVE, Kind.FINISH_MOVE)]:
            self._nothing_to_move("Put Back", plan)
            return
        ready = self._settle(plan)                                 # a name already taken where it belongs is asked about, never replaced
        if ready is not None:
            self._run(ready, unmark=paths)

    def show_quarantine_folder(self) -> None:
        panel = self.active
        if panel.is_home or "://" in panel.path:
            self._say("Open a folder on a drive first: the quarantine is the one of that drive")
            return
        settings, here = self.quarantine_settings(), panel.real_folder()

        def work(progress, cancel):
            root = quarantine.root_for(here, settings)
            return root if os.path.isdir(root) else ""

        def done(root) -> None:
            if not root:
                self._say("Nothing has been quarantined here yet")
            else:
                panel.set_folder(root)
        run_in_background(self, self.cmd_runner, "Looking for the quarantine", work, on_result=done, tracked=self._size_jobs,
                          failed_title="Quarantine")
