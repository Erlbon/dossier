"""Find Duplicate Files: choose where to look, run it on a thread, then go through the groups and remove the extra copies.

The engine is ``core/duplicates.py`` (size, then the ends, then the whole file). Here is the window part: an options dialog, a result
dialog that shows each group of identical files with a check box per copy, and what to do with the checked ones. Deleting is never done
here: the checked files go through the ordinary Delete command (its confirmation, the recycle bin, progress, the queue), and a group can
never be emptied: at least one copy of every group is always left.
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..core import duplicates as dup
from ..core.listings import FOUND_PREFIX, ResultSet
from ..core.sizefmt import human_size
from .owned_dialog import OwnedDialog
from .background import run_in_background
from .zip_edit import zip_parts


class DuplicatesOptionsDialog(OwnedDialog):
    def __init__(self, parent, here: str, other: str = "", min_kb: int = 1) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find Duplicate Files")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files are duplicates when they hold exactly the same bytes, whatever they are called. Nothing is changed "
                                "by the search; you choose what to remove afterwards."))
        form = QFormLayout()
        self.here = QCheckBox(f"This panel's folder and everything below it:  {here}")
        self.here.setChecked(True)
        self.other = QCheckBox(f"The other panel's folder and everything below it:  {other}" if other else "The other panel's folder")
        self.other.setEnabled(bool(other))
        self.other.setToolTip("Finds files that are in both places (a copy you made, a backup)." if other else "The other panel is not on a folder.")
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setSuffix(" KB")
        self.min_kb.setSpecialValueText("Every size (not empty files)")
        self.min_kb.setValue(min_kb)
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("every name; or for example  *.jpg;*.png")
        form.addRow("Look in", self.here)
        form.addRow("", self.other)
        form.addRow("Ignore files smaller than", self.min_kb)
        form.addRow("Only files named", self.pattern)
        layout.addLayout(form)
        self.problem = QLabel()
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.go = buttons.addButton("Find", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._here, self._other = here, other

    def _accept(self) -> None:
        if not self.roots():
            self.problem.setText("Choose at least one folder to look in.")
            return
        self.accept()

    def roots(self) -> list:
        out = []
        if self.here.isChecked() and self._here:
            out.append(self._here)
        if self.other.isChecked() and self._other and self._other != self._here:
            out.append(self._other)
        return out

    def min_size(self) -> int:
        return self.min_kb.value() * 1024

    def name(self) -> str:
        return self.pattern.text().strip()


class DuplicatesResultDialog(OwnedDialog):
    """The groups with a check box per copy. ``action`` is ``delete``, ``mark``, ``tab`` or ``""`` (closed); ``paths`` the checked files."""

    def __init__(self, parent, result: dup.Result) -> None:
        super().__init__(parent)
        self.result = result
        self.action = ""
        self.paths: list = []
        self.setWindowTitle("Duplicate Files")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        n = len(result.groups)
        self.summary = QLabel(f"{n:,} group{'s' if n != 1 else ''} of identical files: {result.copies:,} files, "
                              f"{human_size(result.wasted)} taken by the extra copies. {result.scanned:,} files were looked at"
                              + (f"; {result.unreadable} could not be read." if result.unreadable else "."))
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["File", "Folder", "Modified"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._changed)
        layout.addWidget(self.tree, 1)
        self._tops: list = []                          # (the group's tree item, its Group)
        self._busy = True                              # the tree is being filled: its changes are not the owner's
        for group in result.groups:
            top = QTreeWidgetItem(self.tree, [f"{group.files[0].name}   -   {len(group.files)} copies of {human_size(group.size)}, "
                                              f"{human_size(group.wasted)} wasted"])
            top.setFirstColumnSpanned(True)
            self._tops.append((top, group))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for e in group.files:
                when = datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M") if e.mtime else ""
                child = QTreeWidgetItem(top, [e.name, os.path.dirname(e.path), when])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setData(0, Qt.ItemDataRole.UserRole, e.path)
            top.setExpanded(True)
        for column, width in ((0, 380), (1, 360)):
            self.tree.setColumnWidth(column, width)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("In every group keep"))
        self.policy = QComboBox()
        for key, text in dup.KEEP_POLICIES:
            self.policy.addItem(text, key)
        pick.addWidget(self.policy)
        self.check_others = QPushButton("Check the Others")
        self.check_others.setAutoDefault(False)
        self.check_others.clicked.connect(self.check_extras)
        self.clear = QPushButton("Uncheck All")
        self.clear.setAutoDefault(False)
        self.clear.clicked.connect(self.uncheck_all)
        pick.addWidget(self.check_others)
        pick.addWidget(self.clear)
        pick.addStretch(1)
        layout.addLayout(pick)
        self.counts = QLabel()
        layout.addWidget(self.counts)
        buttons = QHBoxLayout()
        self.delete_button = QPushButton("Delete Checked...")
        self.mark_button = QPushButton("Mark Checked in the Panels")
        self.tab_button = QPushButton("Show All in a Tab")
        close = QPushButton("Close")
        for b in (self.delete_button, self.mark_button, self.tab_button, close):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        close.clicked.connect(self.reject)
        self.delete_button.clicked.connect(lambda: self._finish("delete"))
        self.mark_button.clicked.connect(lambda: self._finish("mark"))
        self.tab_button.clicked.connect(lambda: self._finish("tab"))
        layout.addLayout(buttons)
        self._busy = False
        self._changed()

    # checking ------------------------------------------------------------------------------------------------------------------
    def _children(self, top):
        return [top.child(i) for i in range(top.childCount())]

    def checked_paths(self) -> list:
        return [c.data(0, Qt.ItemDataRole.UserRole) for top, _g in self._tops for c in self._children(top)
                if c.checkState(0) == Qt.CheckState.Checked]

    def check_extras(self) -> None:
        wanted = set(dup.extras(self.result.groups, self.policy.currentData()))
        self._busy = True
        try:
            for top, _g in self._tops:
                for c in self._children(top):
                    c.setCheckState(0, Qt.CheckState.Checked if c.data(0, Qt.ItemDataRole.UserRole) in wanted else Qt.CheckState.Unchecked)
        finally:
            self._busy = False
        self._changed()

    def uncheck_all(self) -> None:
        self._busy = True
        try:
            for top, _g in self._tops:
                for c in self._children(top):
                    c.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._busy = False
        self._changed()

    def _changed(self, *_args) -> None:
        if self._busy:
            return
        paths = set(self.checked_paths())
        emptied = dup.groups_left_empty(self.result.groups, paths)
        size = sum(e.size for g in self.result.groups for e in g.files if e.path in paths)
        text = f"{len(paths):,} checked, {human_size(size)} can be freed."
        if emptied:
            text += f"  {len(emptied)} group{'s have' if len(emptied) != 1 else ' has'} every copy checked: leave at least one copy unchecked."
        self.counts.setText(text)
        self.delete_button.setEnabled(bool(paths) and not emptied)
        self.mark_button.setEnabled(bool(paths))

    def _finish(self, action: str) -> None:
        self.action = action
        self.paths = self.checked_paths()
        self.accept()


class DuplicatesMixin:
    """Part of ``MainWindow``."""

    def _disk_folder_of(self, panel) -> str:
        """The folder on a disk that ``panel`` stands in, or "" for the Home page and for archives."""
        if panel.is_home or zip_parts(panel.path) is not None:
            return ""
        return panel.real_folder()

    def _ask_duplicates_options(self, dlg) -> bool:          # seams for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_duplicates_result(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def find_duplicate_files(self, panel=None, folder: str = "") -> None:
        """Commands > Find Duplicate Files: choose where to look, search on a thread, then go through the groups."""
        panel = panel or self.active
        here = folder or self._disk_folder_of(panel)
        if not here:
            self._say("Open a folder first: duplicates are looked for inside a folder")
            return
        other = self._disk_folder_of(self.other) if self.other is not panel else ""
        try:
            min_kb = int(self.settings.value("duplicates/min_kb", 1))
        except (TypeError, ValueError):
            min_kb = 1
        dlg = DuplicatesOptionsDialog(self, here, other, min_kb)
        if not self._ask_duplicates_options(dlg):
            return
        self.settings.setValue("duplicates/min_kb", dlg.min_kb.value())
        roots, min_size, name = dlg.roots(), dlg.min_size(), dlg.name()
        state = {"stage": "", "done": 0, "total": 0}

        def work(progress, cancel):
            def report(stage: str, done: int, total: int) -> None:
                state.update(stage=stage, done=done, total=total)
                progress(done, 0)
            return dup.find_duplicates(self.fs, roots, min_size=min_size, name=name, cancel=cancel, progress=report)

        def detail() -> str:
            if state["total"]:
                return f"{state['stage']}: {state['done']:,} of {state['total']:,}" if state["total"] < 1_000_000 else \
                    f"{state['stage']}: {human_size(state['done'])} of {human_size(state['total'])}"
            return f"{state['stage']}: {state['done']:,}"

        run_in_background(self, self.cmd_runner, "Finding duplicate files", work, on_result=self._duplicates_found,
                          tracked=self._size_jobs, detail=detail, indeterminate=True, failed_title="Find Duplicate Files")

    def _duplicates_found(self, result: dup.Result) -> None:
        if not result.groups:
            self.dialogs.info("Find Duplicate Files", f"No duplicates: {result.scanned:,} files were looked at"
                              + (f"; {result.unreadable} could not be read." if result.unreadable else "."))
            return
        dlg = DuplicatesResultDialog(self, result)
        if not self._ask_duplicates_result(dlg) or not dlg.action:
            return
        self.duplicates_action(result, dlg.action, dlg.paths)

    def duplicates_action(self, result: dup.Result, action: str, paths: list) -> None:
        if action == "tab":
            entries = [e for g in result.groups for e in g.files]
            title = f"Duplicates: {len(result.groups):,} groups ({human_size(result.wasted)} wasted)"
            origin = os.path.dirname(entries[0].path)
            panel = self.active
            panel.new_tab(self.fs.found.store.add(ResultSet(title, origin, entries)))
            return
        if not paths:
            return
        if action == "mark":
            self.selection.add(paths)
            self._say(f"{len(paths):,} duplicate file{'s' if len(paths) != 1 else ''} marked: press F8 to delete them")
            return
        if action == "delete":
            if dup.groups_left_empty(result.groups, paths):
                self.dialogs.info("Delete Duplicates", "Every copy of some file is checked. At least one copy of each group must stay.")
                return
            with self._acting_on(self.active, paths):
                self.delete()
