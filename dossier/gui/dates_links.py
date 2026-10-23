"""Tools > Change Dates and Attributes... and Tools > New Link...: the windows for ``core/filetimes.py`` and ``core/links.py``.

The dates dialog is a plan-then-apply screen: what is chosen on the left of each row is turned into a plan on a thread, the table shows
every item's old and new values, and nothing is written until Apply. The window then writes the plan on a thread with progress and Cancel.
The link dialog only collects the answers; the window makes the link on a thread and, if that is refused, opens the dialog again with
the reason, so nothing typed is lost.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHeaderView)

from ..core import filetimes as ft
from ..core import links
from ..core.platform import IS_WINDOWS
from .background import run_in_background

MAX_ROWS = 2000
RULES = ((ft.SET, "Set to"), (ft.SHIFT, "Shift by"), (ft.COPY_FIELD, "Copy from another date of the item"),
         (ft.FROM_FILE, "Take the date of a file"), (ft.FROM_EXIF, "Photo date taken"))
FIELD_NAMES = {"modified": "Modified", "accessed": "Last opened", "created": "Created"}
FLAG_NAMES = {"readonly": "Read-only", "hidden": "Hidden", "system": "System", "archive": "Archive"}
WAIT = 300                                          # ms after the last change before the preview is made again


def moment_text(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
    except (OverflowError, OSError, ValueError):
        return ""


class DatesDialog(QDialog):
    """Choose what to change, see old and new for every item, press Apply. ``plan`` is the answer (empty when cancelled)."""

    def __init__(self, win, paths: list, has_folders: bool = False) -> None:
        super().__init__(win)
        self.win = win
        self.paths = list(paths)
        self._closed = False
        self.plan: list = []
        self._latest: list = []
        self._serial = 0
        self._job = None
        self.setWindowTitle("Change Dates and Attributes")
        self.setMinimumSize(760, 520)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        row = QHBoxLayout()
        self.date_boxes = {}
        for name in ft.FIELDS:
            box = QCheckBox(FIELD_NAMES[name])
            box.setChecked(name == "modified")
            if name == "created" and not ft.CAN_SET_CREATED:
                box.setEnabled(False)
                box.setToolTip("Only Windows has a creation date that a program can set")
            box.toggled.connect(self.schedule)
            self.date_boxes[name] = box
            row.addWidget(box)
        row.addStretch(1)
        form.addRow("Change", row)

        self.rule_box = QComboBox()
        for kind, text in RULES:
            self.rule_box.addItem(text, kind)
        self.rule_box.currentIndexChanged.connect(self._rule_changed)
        self.value = QLineEdit()
        self.value.textChanged.connect(self.schedule)
        self.now_button = QPushButton("Now")
        self.now_button.setAutoDefault(False)
        self.now_button.clicked.connect(lambda: self.value.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.choose_button = QPushButton("Choose...")
        self.choose_button.setAutoDefault(False)
        self.choose_button.clicked.connect(self._choose_file)
        self.source_field = QComboBox()
        for name in ft.FIELDS:
            self.source_field.addItem(FIELD_NAMES[name], name)
        self.source_field.currentIndexChanged.connect(self.schedule)
        value_row = QHBoxLayout()
        for w in (self.rule_box, self.value, self.source_field, self.now_button, self.choose_button):
            value_row.addWidget(w)
        value_row.setStretch(1, 1)
        form.addRow("New value", value_row)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addRow("", self.hint)

        flags_row = QHBoxLayout()
        self.flag_boxes = {}
        for name in ft.FLAGS:
            box = QCheckBox(FLAG_NAMES[name])
            box.setTristate(True)
            box.setCheckState(Qt.CheckState.PartiallyChecked)               # "leave as it is"
            box.setToolTip("Filled square: leave as it is. Tick: switch on. Empty: switch off.")
            if name not in ft.supported_flags():
                box.setEnabled(False)
                box.setToolTip("This system has no such attribute")
            box.stateChanged.connect(self.schedule)
            self.flag_boxes[name] = box
            flags_row.addWidget(box)
        flags_row.addStretch(1)
        form.addRow("Attributes", flags_row)

        self.inside = QCheckBox("Include what is inside folders")
        self.inside.toggled.connect(self.schedule)
        self.folders_too = QCheckBox("Change the folders' own dates and attributes")
        self.folders_too.setChecked(True)
        self.folders_too.toggled.connect(self.schedule)
        self.inside.setVisible(has_folders)                                 # whether there are folders is known from the list: no disk here
        self.folders_too.setVisible(has_folders)
        both = QVBoxLayout()
        both.addWidget(self.inside)
        both.addWidget(self.folders_too)
        form.addRow("", both)
        layout.addLayout(form)

        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSortingEnabled(True)                                  # every header resizes and sorts (the owner's rule)
        self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox()
        self.apply_button = QPushButton("Apply")
        buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self._apply)
        self.apply_button.setEnabled(False)                                 # until there is a preview with something to change
        self.summary.setText("Choose what to change.")
        layout.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.replan)
        self._rule_changed()

    # what is chosen --------------------------------------------------------------------------------------------------------------------
    def rule_kind(self) -> str:
        return self.rule_box.currentData()

    def _rule_changed(self) -> None:
        kind = self.rule_kind()
        self.value.setVisible(kind in (ft.SET, ft.SHIFT, ft.FROM_FILE))
        self.now_button.setVisible(kind == ft.SET)
        self.choose_button.setVisible(kind == ft.FROM_FILE)
        self.source_field.setVisible(kind in (ft.COPY_FIELD, ft.FROM_FILE))
        self.value.setPlaceholderText({ft.SET: "2024-05-17 10:30", ft.SHIFT: "+2h, -1d, 1d2h30m", ft.FROM_FILE: "the file or folder to take it from"}.get(kind, ""))
        self.hint.setText({ft.SET: "Every item gets this moment (local time).",
                           ft.SHIFT: "Every date moves later (+) or earlier (-) by this much, each from its own value.",
                           ft.COPY_FIELD: "Each item's chosen dates become this date of the same item: for example Created from Modified.",
                           ft.FROM_FILE: "Every item gets this date of the file you name.",
                           ft.FROM_EXIF: "Each photo gets the date it was taken, read from the picture. Items without one are listed and left alone."}[kind])
        self.schedule()

    def _choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Take the date of this file")
        if path:
            self.value.setText(path)

    def chosen(self) -> tuple:
        """``(rule, dates, on, off, error)`` as typed; ``error`` is a sentence when the typing is not (yet) usable."""
        dates = [n for n, box in self.date_boxes.items() if box.isChecked() and box.isEnabled()]
        on = [n for n, b in self.flag_boxes.items() if b.checkState() == Qt.CheckState.Checked and b.isEnabled()]
        off = [n for n, b in self.flag_boxes.items() if b.checkState() == Qt.CheckState.Unchecked and b.isEnabled()]
        kind, text = self.rule_kind(), self.value.text().strip()
        rule, error = None, ""
        try:
            if dates:
                if kind == ft.SET:
                    rule = ft.Rule(ft.SET, when=ft.parse_moment(text))
                elif kind == ft.SHIFT:
                    rule = ft.Rule(ft.SHIFT, seconds=ft.parse_duration(text))
                elif kind == ft.COPY_FIELD:
                    rule = ft.Rule(ft.COPY_FIELD, source_field=self.source_field.currentData())
                elif kind == ft.FROM_FILE:
                    rule = ft.Rule(ft.FROM_FILE, source=text, source_field=self.source_field.currentData()) if text else None
                    if rule is None:
                        error = "Name the file to take the date from"
                else:
                    rule = ft.Rule(ft.FROM_EXIF)
        except ft.TimeError as e:
            error = str(e)
        if not dates and not on and not off:
            error = "Choose a date or an attribute to change"
        return rule, dates, on, off, error

    # the preview -----------------------------------------------------------------------------------------------------------------------
    def schedule(self, *_args) -> None:
        if hasattr(self, "timer"):
            self.timer.start(WAIT)

    def replan(self) -> None:
        rule, dates, on, off, error = self.chosen()
        self._serial += 1
        serial = self._serial
        if self._job is not None:
            self._job.cancel()
        if error or (rule is None and not on and not off):
            self.show_plan([], dates, error or "Choose what to change")
            return
        paths, recursive, folders = list(self.paths), self.inside.isChecked(), self.folders_too.isChecked()

        def work(progress, cancel):
            progress(0, 0)
            return ft.plan_both(paths, rule, dates, set_on=on, set_off=off, recursive=recursive, include_folders=folders, cancel=cancel)

        def done(plan) -> None:
            if serial == self._serial and plan is not None and not self._closed:
                self.show_plan(plan, dates, "")
        self._job = run_in_background(self.win, self.win.cmd_runner, "Preparing the preview", work, on_result=done, tracked=self.win._size_jobs,
                                      indeterminate=True, partial_on_cancel=True, failed_title="Change Dates and Attributes")

    def show_plan(self, plan: list, dates: list, message: str) -> None:
        self._latest = plan
        shown = [c for c in plan if c.changes or c.problem]
        flags = any(c.flags_change for c in plan)
        columns = ["Name"]
        for name in ft.FIELDS:
            if name in dates:
                columns += [f"{FIELD_NAMES[name]} now", f"{FIELD_NAMES[name]} after"]
        if flags:
            columns += ["Attributes now", "Attributes after"]
        columns.append("Note")
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHeaderLabels(columns)
        try:
            base = os.path.commonpath([os.path.dirname(p) for p in self.paths]) if self.paths else ""
        except ValueError:
            base = ""
        for c in shown[:MAX_ROWS]:
            cells = [os.path.relpath(c.path, base) if base else c.path]
            for name in ft.FIELDS:
                if name in dates:
                    cells += ["" if c.problem else moment_text(getattr(c.old, name)), "" if c.problem else moment_text(getattr(c.new, name))]
            if flags:
                cells += [", ".join(c.old_flags) or "none", ", ".join(c.new_flags) or "none"] if not c.problem else ["", ""]
            cells.append(("cannot change: " + c.problem) if c.problem else "")
            item = QTreeWidgetItem(cells)
            item.setToolTip(0, c.path)
            self.table.addTopLevelItem(item)
        for i in range(len(columns)):
            self.table.resizeColumnToContents(i)
        self.table.setSortingEnabled(True)
        will = sum(1 for c in plan if c.changes)
        problems = sum(1 for c in plan if c.problem)
        stays = len(plan) - will - problems
        if message:
            self.summary.setText(message)
        else:
            parts = [f"{will:,} item{'s' if will != 1 else ''} will change"]
            if stays:
                parts.append(f"{stays:,} stay as they are")
            if problems:
                parts.append(f"{problems:,} cannot be changed")
            more = f" Only the first {MAX_ROWS:,} are listed here; all are changed." if len(shown) > MAX_ROWS else ""
            self.summary.setText(", ".join(parts) + f". Nothing is written until you press Apply.{more}")
        self.apply_button.setEnabled(will > 0)

    def done(self, result: int) -> None:
        self._closed = True
        self.timer.stop()
        if self._job is not None:
            self._job.cancel()
        super().done(result)

    def _apply(self) -> None:
        self.timer.stop()
        self.plan = [c for c in self._latest if c.changes]
        if self._job is not None:
            self._job.cancel()
        self.accept()


class LinkDialog(QDialog):
    """Kind, what it points to, where it goes and what it is called. ``answer()`` is ``(kind, target, link_path, relative)``."""

    EXPLAIN = {links.SYMLINK: "Holds a path to a file or a folder anywhere. On Windows it needs Developer Mode (or an administrator).",
               links.JUNCTION: "Shows another folder of this computer as if it were here. Needs no special right. Windows only.",
               links.HARDLINK: "A second name for the same file on the same drive. Both names are equal; the data goes when the last name does."}

    def __init__(self, win, target: str, folder: str, target_is_dir: bool, preset: Optional[dict] = None, error: str = "") -> None:
        super().__init__(win)
        self.setWindowTitle("New Link")
        self.setMinimumWidth(560)
        preset = preset or {}
        layout = QVBoxLayout(self)
        self.error = QLabel(error)
        self.error.setWordWrap(True)
        self.error.setVisible(bool(error))
        layout.addWidget(self.error)
        kinds = QHBoxLayout()
        self.radios = {}
        for kind in links.KINDS:
            radio = QRadioButton({links.SYMLINK: "Symbolic link", links.JUNCTION: "Junction", links.HARDLINK: "Hard link"}[kind])
            if kind == links.JUNCTION and not IS_WINDOWS:
                radio.setEnabled(False)
                radio.setToolTip("Junctions exist only on Windows")
            if kind == links.JUNCTION and not target_is_dir:
                radio.setEnabled(False)
                radio.setToolTip("A junction can only show a folder")
            if kind == links.HARDLINK and target_is_dir:
                radio.setEnabled(False)
                radio.setToolTip("A hard link cannot be made for a folder")
            radio.toggled.connect(self._kind_changed)
            self.radios[kind] = radio
            kinds.addWidget(radio)
        kinds.addStretch(1)
        wanted = preset.get("kind", links.SYMLINK)
        self.radios[wanted if self.radios[wanted].isEnabled() else links.SYMLINK].setChecked(True)
        layout.addLayout(kinds)
        self.explain = QLabel()
        self.explain.setWordWrap(True)
        layout.addWidget(self.explain)
        form = QFormLayout()
        self.target = QLineEdit(preset.get("target", target))
        self.folder = QLineEdit(preset.get("folder", folder))
        self._target_is_dir = target_is_dir
        self._default_name = links.default_link_name(target, self.kind(), target_is_dir)
        self.name = QLineEdit(preset.get("name", self._default_name))
        form.addRow("Points to", self.target)
        form.addRow("Make in", self.folder)
        form.addRow("Name", self.name)
        layout.addLayout(form)
        self.relative = QCheckBox("Store a relative path (the link keeps working when both are moved together)")
        self.relative.setChecked(bool(preset.get("relative", False)))
        layout.addWidget(self.relative)
        buttons = QDialogButtonBox()
        make = QPushButton("Make link")
        buttons.addButton(make, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        make.clicked.connect(self.accept)
        layout.addWidget(buttons)
        self._kind_changed()

    def kind(self) -> str:
        return next((k for k, r in self.radios.items() if r.isChecked()), links.SYMLINK)

    def _kind_changed(self, *_args) -> None:
        if not hasattr(self, "relative"):                          # the radio buttons are set before the rest of the dialog exists
            return
        kind = self.kind()
        self.explain.setText(self.EXPLAIN[kind])
        self.relative.setEnabled(kind == links.SYMLINK)
        fresh = links.default_link_name(self.target.text(), kind, self._target_is_dir)
        if self.name.text() == self._default_name:                 # the name was not typed over: it follows the kind (a hard link keeps the extension)
            self.name.setText(fresh)
        self._default_name = fresh

    def answer(self) -> tuple:
        folder, name = self.folder.text().strip(), self.name.text().strip()
        return self.kind(), self.target.text().strip(), os.path.join(folder, name), self.relative.isChecked() and self.kind() == links.SYMLINK


class DatesLinksMixin:
    """Part of ``MainWindow``."""

    def _items_for(self, what: str) -> Optional[list]:
        """The marked items (or the one under the cursor) on a drive of this computer, or None with the reason said."""
        paths = self._local_targets()
        if not paths:
            self._say(f"{what}: mark items or put the cursor on one, on a drive of this computer (not inside an archive, on a server, or on the Home page)")
            return None
        return paths

    # dates -----------------------------------------------------------------------------------------------------------------------------
    def change_dates(self) -> None:
        paths = self._items_for("Change dates")
        if paths is None:
            return
        wanted = set(paths)
        panel = self.active
        has_folders = any(e is not None and e.path in wanted and e.is_dir for e in (panel.model.entry_at(r) for r in range(panel.model.entry_count())))
        dialog = DatesDialog(self, paths, has_folders)
        self._show_dates_dialog(dialog)
        if dialog.plan:
            self._apply_dates(dialog.plan)

    def _show_dates_dialog(self, dialog) -> None:         # a seam for tests
        dialog.exec()

    def _apply_dates(self, plan: list) -> None:
        def work(progress, cancel):
            return ft.apply(plan, cancel, progress)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            if result is None:
                self._say("Stopped: what was already changed stays changed")
                return
            self._say(f"Changed {result.done:,} item{'s' if result.done != 1 else ''}" + (f", {len(result.failed)} failed" if result.failed else ""))
            if result.failed:
                lines = [f"{os.path.basename(p)}: {why}" for p, why in result.failed[:8]]
                more = [f"and {len(result.failed) - 8} more"] if len(result.failed) > 8 else []
                self.dialogs.info("Change Dates and Attributes", chr(10).join(lines + more))
        run_in_background(self, self.cmd_runner, "Changing dates", work, on_result=finished, tracked=self._size_jobs,
                          partial_on_cancel=True, failed_title="Change Dates and Attributes")

    # links -----------------------------------------------------------------------------------------------------------------------------
    def new_link(self) -> None:
        paths = self._items_for("New link")
        if paths is None:
            return
        if len(paths) != 1:
            self._say("Put the cursor on the one item to link to (unmark the others)")
            return
        entry = self.active.current_entry()
        is_dir = bool(entry is not None and entry.path == paths[0] and entry.is_dir)
        self._link_flow(paths[0], self._folder_for_new_file(), is_dir, None, "")

    def _link_flow(self, target: str, folder: str, is_dir: bool, preset, error: str) -> None:
        dialog = LinkDialog(self, target, folder, is_dir, preset, error)
        self._show_link_dialog(dialog)
        if dialog.result() != QDialog.DialogCode.Accepted:
            return
        kind, where, link, relative = dialog.answer()
        values = {"kind": kind, "target": where, "folder": dialog.folder.text().strip(), "name": dialog.name.text().strip(), "relative": relative}

        def work(progress, cancel):
            try:
                links.create(kind, where, link, relative=relative)
            except links.LinkError as e:
                return str(e)
            return ""

        def finished(problem) -> None:
            if problem:
                self._link_flow(target, folder, is_dir, values, problem)
                return
            self._say(f"Made {links.KIND_NAMES[kind].lower()}: {link}")
            for panel in (self.left, self.right):
                panel.refresh()
        run_in_background(self, self.cmd_runner, "Making the link", work, on_result=finished, tracked=self._size_jobs, failed_title="New Link")

    def _show_link_dialog(self, dialog) -> None:          # a seam for tests
        dialog.exec()
