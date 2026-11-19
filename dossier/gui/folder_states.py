"""Remember This Folder's State and What Changed Since...: keep what a folder held, and list what was added, changed, moved or removed later.

The engine is ``core/folder_states.py`` on top of ``core/manifest.py``. A state is kept in Dossier's own settings folder, never in the
user's folder. Both commands read and hash files, so both run on a thread. The result is a list with a check box per file that still
exists (removed files are shown but are gone, so there is nothing to act on); the checked files can be marked in the panels, shown in a
tab, or deleted through the ordinary Delete command.
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout)

from ..core import folder_states as fstates
from ..core import manifest
from ..core.listings import ResultSet
from ..core.sizefmt import human_size
from ..core.vfs import Entry
from .background import run_in_background
from .owned_dialog import OwnedDialog


def _when(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _files(n: int) -> str:
    return f"{n:,} file{'s' if n != 1 else ''}"


class StatePickerDialog(OwnedDialog):
    """Choose which remembered state to compare with (newest first), or forget some. ``chosen`` is the state; ``forgotten`` the ones forgotten."""

    def __init__(self, parent, folder: str, states: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("What Changed Since...")
        self.setMinimumWidth(520)
        self.chosen = None
        self.forgotten: list = []
        self._confirm = parent.dialogs.confirm if hasattr(parent, "dialogs") else (lambda *a: True)
        layout = QVBoxLayout(self)
        label = QLabel(f"Compare {folder} as it is now with the state you remembered:")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list = QListWidget()
        for s in states:
            row = QListWidgetItem(f"{_when(s.when)}     {_files(s.files)}, {human_size(s.bytes)}")
            row.setData(Qt.ItemDataRole.UserRole, s)
            self.list.addItem(row)
        if states:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self._go())
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.go = QPushButton("Compare")
        self.forget = QPushButton("Forget This State")
        self.forget.setToolTip("Deletes the remembered state from Dossier's own folder. Your folder is not touched.")
        cancel = QPushButton("Cancel")
        for b in (self.go, self.forget, cancel):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        self.go.setDefault(True)
        self.go.clicked.connect(self._go)
        self.forget.clicked.connect(self._forget)
        cancel.clicked.connect(self.reject)
        layout.addLayout(buttons)
        self.list.currentRowChanged.connect(self._enable)
        self._enable()

    def _enable(self, *_args) -> None:
        have = self.list.currentItem() is not None
        self.go.setEnabled(have)
        self.forget.setEnabled(have)

    def _current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _go(self) -> None:
        state = self._current()
        if state is not None:
            self.chosen = state
            self.accept()

    def _forget(self) -> None:
        state = self._current()
        if state is None:
            return
        if not self._confirm("Forget This State", f"Forget the state from {_when(state.when)} ({_files(state.files)})? "
                             "Only Dossier's own copy is deleted.", "Forget"):
            return
        self.forgotten.append(state)
        self.list.takeItem(self.list.currentRow())
        self._enable()


class ChangesDialog(OwnedDialog):
    """What changed. ``action`` is ``mark``, ``tab``, ``delete`` or ``""``; ``rels`` are the checked files (paths below the folder)."""

    def __init__(self, parent, changes: fstates.Changes, state: fstates.State) -> None:
        super().__init__(parent)
        self.changes = changes
        self.action = ""
        self.rels: list = []
        self.setWindowTitle("What Changed Since...")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        counts = ", ".join(f"{changes.count(k):,} {fstates.STATUS_TEXT[k].lower()}" for k in fstates.STATUSES if changes.count(k))
        text = (counts or "Nothing has changed") + f" since {_when(state.when)}.  {_files(changes.files_now)} now, {_files(changes.files_before)} then"
        text += f"; {changes.touched:,} with a new time but the same content are not listed." if changes.touched else "."
        self.summary = QLabel(text)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        show = QHBoxLayout()
        show.addWidget(QLabel("Show"))
        self.filters: dict = {}
        for key in fstates.STATUSES:
            if changes.count(key):
                box = QCheckBox(f"{fstates.STATUS_TEXT[key]} ({changes.count(key):,})")
                box.setChecked(True)
                box.toggled.connect(self._filter)
                show.addWidget(box)
                self.filters[key] = box
        show.addStretch(1)
        layout.addLayout(show)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["File", "What happened", "Size", "Modified"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.items: list = []                                  # (tree item, Change)
        self._busy = True
        for row in changes.rows:
            what = fstates.STATUS_TEXT[row.status]
            if row.status == fstates.MOVED:
                what += f" from {row.old_rel}"
            elif row.status == fstates.CHANGED and row.old_size is not None:
                what += f" ({human_size(row.old_size)} before)"
            elif row.status == fstates.REMOVED:
                what += " (gone, nothing to act on)"
            item = QTreeWidgetItem(self.tree, [row.rel, what, human_size(row.size), _when(row.mtime) if row.exists else ""])
            if row.exists:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.items.append((item, row))
        self.tree.itemChanged.connect(self._changed)
        for column, width in ((0, 340), (1, 300), (2, 90)):
            self.tree.setColumnWidth(column, width)
        layout.addWidget(self.tree, 1)

        pick = QHBoxLayout()
        self.check_all = QPushButton("Check All That Exist")
        self.clear = QPushButton("Uncheck All")
        for b in (self.check_all, self.clear):
            b.setAutoDefault(False)
            pick.addWidget(b)
        pick.addStretch(1)
        self.check_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        self.clear.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        layout.addLayout(pick)
        self.counts = QLabel()
        layout.addWidget(self.counts)
        buttons = QHBoxLayout()
        self.mark_button = QPushButton("Mark Checked in the Panel")
        self.tab_button = QPushButton("Show Checked in a Tab")
        self.delete_button = QPushButton("Delete Checked...")
        close = QPushButton("Close")
        for b in (self.mark_button, self.tab_button, self.delete_button, close):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        close.clicked.connect(self.reject)
        self.mark_button.clicked.connect(lambda: self._finish("mark"))
        self.tab_button.clicked.connect(lambda: self._finish("tab"))
        self.delete_button.clicked.connect(lambda: self._finish("delete"))
        layout.addLayout(buttons)
        self._busy = False
        self._changed()

    def checked_rels(self) -> list:
        return [row.rel for item, row in self.items if row.exists and item.checkState(0) == Qt.CheckState.Checked]

    def _set_all(self, state) -> None:
        self._busy = True
        try:
            for item, row in self.items:
                if row.exists and not item.isHidden():
                    item.setCheckState(0, state)
        finally:
            self._busy = False
        self._changed()

    def _changed(self, *_args) -> None:
        if self._busy:
            return
        rels = set(self.checked_rels())
        size = sum(row.size for _item, row in self.items if row.rel in rels)
        self.counts.setText(f"{len(rels):,} checked, {human_size(size)}.")
        for b in (self.mark_button, self.tab_button, self.delete_button):
            b.setEnabled(bool(rels))

    def _filter(self, *_args) -> None:
        shown = {k for k, box in self.filters.items() if box.isChecked()}
        for item, row in self.items:
            item.setHidden(row.status not in shown)

    def _finish(self, action: str) -> None:
        self.action = action
        self.rels = self.checked_rels()
        self.accept()


class FolderStatesMixin:
    """Part of ``MainWindow``."""

    def _folder_states_dir(self) -> str:
        return fstates.states_dir(os.path.dirname(self.settings.fileName()))

    def _ask_state_picker(self, dlg) -> bool:                  # seams for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_changes_result(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _state_folder(self) -> str:
        here = self._disk_folder_of(self.active)
        if not here:
            self._say("Open a folder first: a state is remembered for a folder")
        return here

    # remember ---------------------------------------------------------------------------------------------------------------------
    def remember_folder_state(self) -> None:
        """Tools > Compare > Remember This Folder's State: every file below the folder with size, time and checksum, kept in Dossier's folder."""
        here = self._state_folder()
        if not here:
            return
        directory = self._folder_states_dir()
        shown = {"done": 0, "total": 0, "files": 0, "all": 0}

        def work(progress, cancel):
            def report(p: manifest.Progress) -> None:
                shown.update(done=p.bytes, total=p.total_bytes, files=p.files, all=p.total_files)
                progress(p.bytes, p.total_bytes)
            items = manifest.build(self.fs, here, cancel=cancel, progress=report)
            return fstates.save_state(directory, here, items)

        def detail() -> str:
            return f"{shown['files']:,} of {shown['all']:,} files, {human_size(shown['done'])} of {human_size(shown['total'])}"

        run_in_background(self, self.cmd_runner, "Remembering the state of the folder", work, on_result=self._state_remembered,
                          tracked=self._size_jobs, detail=detail, failed_title="Remember This Folder's State")

    def _state_remembered(self, state: fstates.State) -> None:
        self._say(f"State remembered: {_files(state.files)}, {human_size(state.bytes)}. Use Tools > Compare > What Changed Since... later")

    # compare ----------------------------------------------------------------------------------------------------------------------
    def what_changed_since(self) -> None:
        """Tools > Compare > What Changed Since...: choose a remembered state of this folder; the list says what was added, changed, moved, removed."""
        here = self._state_folder()
        if not here:
            return
        directory = self._folder_states_dir()
        run_in_background(self, self.cmd_runner, "Looking for remembered states", lambda progress, cancel: fstates.list_states(directory, here),
                          on_result=lambda states: self._states_listed(here, states), tracked=self._size_jobs, indeterminate=True,
                          failed_title="What Changed Since")

    def _states_listed(self, here: str, states: list) -> None:
        if not states:
            self.dialogs.info("What Changed Since", "No state of this folder is remembered yet. Use Tools > Compare > Remember This Folder's "
                              "State first, then come back after something has changed.")
            return
        dlg = StatePickerDialog(self, here, states)
        accepted = self._ask_state_picker(dlg)
        if dlg.forgotten:
            forgotten = list(dlg.forgotten)
            run_in_background(self, self.cmd_runner, "Forgetting states", lambda progress, cancel: [fstates.forget_state(s) for s in forgotten],
                              on_result=lambda _r: self._say(f"{_files(len(forgotten)).replace('file', 'state')} forgotten"),
                              tracked=self._size_jobs, indeterminate=True, failed_title="Forget This State")
        if accepted and dlg.chosen is not None:
            self._compare_with_state(here, dlg.chosen)

    def _compare_with_state(self, here: str, state: fstates.State) -> None:
        shown = {"done": 0, "total": 0, "files": 0, "all": 0}
        case_sensitive = bool(getattr(self.fs, "case_sensitive", True))

        def work(progress, cancel):
            old = fstates.load_items(state)

            def report(p: manifest.Progress) -> None:
                shown.update(done=p.bytes, total=p.total_bytes, files=p.files, all=p.total_files)
                progress(p.bytes, p.total_bytes)
            new = manifest.build(self.fs, here, cancel=cancel, progress=report)
            return fstates.compare(old, new, case_sensitive)

        def detail() -> str:
            return f"{shown['files']:,} of {shown['all']:,} files, {human_size(shown['done'])} of {human_size(shown['total'])}"

        run_in_background(self, self.cmd_runner, "Looking at what changed", work, tracked=self._size_jobs, detail=detail,
                          on_result=lambda changes: self._changes_found(here, state, changes), failed_title="What Changed Since")

    def _changes_found(self, here: str, state: fstates.State, changes: fstates.Changes) -> None:
        if not changes.rows:
            self.dialogs.info("What Changed Since", f"Nothing has changed since {_when(state.when)}: {_files(changes.files_now)} looked at"
                              + (f"; {changes.touched:,} have a new time but the same content." if changes.touched else "."))
            return
        dlg = ChangesDialog(self, changes, state)
        if not self._ask_changes_result(dlg) or not dlg.action:
            return
        self.changes_action(here, changes, state, dlg.action, dlg.rels)

    def changes_action(self, here: str, changes: fstates.Changes, state: fstates.State, action: str, rels: list) -> None:
        if not rels:
            return
        paths = [self.fs.join(here, *rel.split("/")) for rel in rels]
        if action == "mark":
            self.selection.add(paths)
            self._say(f"{_files(len(paths))} marked")
            return
        if action == "tab":
            wanted = set(rels)
            entries = [Entry(row.rel.rsplit("/", 1)[-1], self.fs.join(here, *row.rel.split("/")), False, row.size, row.mtime)
                       for row in changes.rows if row.exists and row.rel in wanted]
            title = f"Changed since {_when(state.when)}: {len(entries):,} files"
            self.active.new_tab(self.fs.found.store.add(ResultSet(title, here, entries)))
            return
        if action == "delete":
            with self._acting_on(self.active, paths):
                self.delete()
