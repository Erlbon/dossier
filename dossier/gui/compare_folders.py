"""Compare Folders and Synchronize: the two panels' folders side by side, then one plan that makes them alike.

``core/compare.py`` finds the differences, ``core/sync.py`` decides what a direction (a *mode*) does about each and builds the plans. Here
is the window part: the options, a result list where every difference has the action the mode gives it and a check box to leave it out,
and the hand-over to the ordinary copy and delete commands (conflicts, progress, the queue, the recycle bin and Ctrl+Z are theirs).
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                             QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..core import compare as cmp
from ..core import sync
from ..core.sizefmt import human_size
from .background import run_in_background

FILTERS = ((cmp.ONLY_LEFT, "Only left"), (cmp.ONLY_RIGHT, "Only right"), (cmp.LEFT_NEWER, "Newer left"),
           (cmp.RIGHT_NEWER, "Newer right"), (cmp.DIFFERENT, "Different"), (cmp.TYPE, "File and folder"), (cmp.SAME, "Same"))


def _side(entry) -> str:
    if entry is None:
        return ""
    if entry.is_dir:
        return "folder"
    when = datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M") if entry.mtime else ""
    return f"{human_size(entry.size)}   {when}"


class CompareOptionsDialog(QDialog):
    def __init__(self, parent, left: str, right: str, values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare Folders")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Left:   {left}\nRight:  {right}"))
        form = QFormLayout()
        self.recursive = QCheckBox("Look in the subfolders too")
        self.recursive.setChecked(values["recursive"])
        self.by = QComboBox()
        for key, text in cmp.BY:
            self.by.addItem(text, key)
        self.by.setCurrentIndex(max(0, self.by.findData(values["by"])))
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 120)
        self.tolerance.setDecimals(1)
        self.tolerance.setSuffix(" s")
        self.tolerance.setValue(values["tolerance"])
        self.tolerance.setToolTip("Two times this close are the same time (a FAT drive keeps times to two seconds).")
        self.hour = QCheckBox("Ignore a difference of exactly one hour (summer time on FAT drives)")
        self.hour.setChecked(values["ignore_hour"])
        self.same = QCheckBox("Also list the files that are alike")
        self.same.setChecked(values["include_same"])
        form.addRow("", self.recursive)
        form.addRow("Tell files apart by", self.by)
        form.addRow("Times agree within", self.tolerance)
        form.addRow("", self.hour)
        form.addRow("", self.same)
        layout.addLayout(form)
        layout.addWidget(QLabel("Nothing is changed by the comparison. You choose what to do about the differences afterwards."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Compare", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {"recursive": self.recursive.isChecked(), "by": self.by.currentData(), "tolerance": float(self.tolerance.value()),
                "ignore_hour": self.hour.isChecked(), "include_same": self.same.isChecked()}


class CompareResultDialog(QDialog):
    """The differences. ``action`` is ``sync``, ``mark`` or ``""``; ``actions`` are the checked ones (``sync.Action``)."""

    def __init__(self, parent, result: cmp.CompareResult, mode: str = "update_right") -> None:
        super().__init__(parent)
        self.result = result
        self.action = ""
        self.actions: list = []
        self.setWindowTitle("Compare Folders")
        self.resize(1000, 620)
        layout = QVBoxLayout(self)
        counts = ", ".join(f"{result.count(k):,} {text.lower()}" for k, text in FILTERS if k != cmp.SAME and result.count(k))
        self.summary = QLabel((counts or "No differences") + f".  {result.scanned:,} items looked at, {result.same:,} files alike"
                              + (f", {result.unreadable} folder{'s' if result.unreadable != 1 else ''} could not be read." if result.unreadable else "."))
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        show = QHBoxLayout()
        show.addWidget(QLabel("Show"))
        self.filters: dict = {}
        for key, text in FILTERS:
            if result.count(key):
                box = QCheckBox(f"{text} ({result.count(key):,})")
                box.setChecked(True)
                box.toggled.connect(self._filter)
                show.addWidget(box)
                self.filters[key] = box
        show.addStretch(1)
        layout.addLayout(show)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Left", "Right", "Difference", "What will happen"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.items: list = []                          # (tree item, Row)
        self._busy = True
        for row in result.rows:
            item = QTreeWidgetItem(self.tree, [row.rel, _side(row.left), _side(row.right), cmp.STATUS_TEXT[row.status], ""])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.items.append((item, row))
        self.tree.itemChanged.connect(self._changed)
        for column, width in ((0, 340), (1, 170), (2, 170), (3, 200)):
            self.tree.setColumnWidth(column, width)
        layout.addWidget(self.tree, 1)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("Synchronize"))
        self.mode = QComboBox()
        for key, text in sync.MODES:
            self.mode.addItem(text, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        pick.addWidget(self.mode, 1)
        layout.addLayout(pick)
        self.what = QLabel()
        self.what.setWordWrap(True)
        layout.addWidget(self.what)
        buttons = QHBoxLayout()
        self.sync_button = QPushButton("Synchronize...")
        self.mark_button = QPushButton("Mark the Differences in the Panels")
        close = QPushButton("Close")
        for b in (self.sync_button, self.mark_button, close):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        close.clicked.connect(self.reject)
        self.sync_button.clicked.connect(lambda: self._finish("sync"))
        self.mark_button.clicked.connect(lambda: self._finish("mark"))
        layout.addLayout(buttons)
        self._busy = False
        self._mode_changed()

    # the actions ---------------------------------------------------------------------------------------------------------------------
    def current_mode(self) -> str:
        return self.mode.currentData()

    def _mode_changed(self, *_args) -> None:
        self._busy = True
        try:
            for item, row in self.items:
                action = sync.decide(row, self.current_mode())
                item.setText(4, sync.ACTION_TEXT[action.kind] + ("   (replaces a newer file)" if action.replaces_newer else ""))
                item.setData(4, Qt.ItemDataRole.UserRole, action)
                item.setCheckState(0, Qt.CheckState.Checked if action.kind else Qt.CheckState.Unchecked)
                flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable if action.kind else item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                item.setFlags(flags)
        finally:
            self._busy = False
        self._changed()

    def checked_actions(self) -> list:
        return [item.data(4, Qt.ItemDataRole.UserRole) for item, _row in self.items
                if item.checkState(0) == Qt.CheckState.Checked and item.data(4, Qt.ItemDataRole.UserRole).kind]

    def _changed(self, *_args) -> None:
        if self._busy:
            return
        chosen = self.checked_actions()
        s = sync.summarise(chosen)
        self.what.setText(f"{s.text().capitalize()}." + (f"  {human_size(s.bytes)} to copy." if s.bytes else ""))
        self.sync_button.setEnabled(s.total > 0)
        self.mark_button.setEnabled(bool(self.result.rows))

    def _filter(self, *_args) -> None:
        shown = {k for k, box in self.filters.items() if box.isChecked()}
        for item, row in self.items:
            item.setHidden(row.status not in shown)

    def _finish(self, action: str) -> None:
        self.action = action
        self.actions = self.checked_actions() if action == "sync" else []
        self.accept()


class CompareFoldersMixin:
    """Part of ``MainWindow``."""

    def _ask_compare_options(self, dlg) -> bool:           # seams for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_compare_result(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def compare_options(self) -> dict:
        s = self.settings
        g = lambda k, d: s.value("compare/" + k, d)                                       # noqa: E731
        flag = lambda v: str(v).lower() == "true"                                          # noqa: E731
        try:
            tolerance = float(g("tolerance", 2.0))
        except (TypeError, ValueError):
            tolerance = 2.0
        by = str(g("by", "size_time"))
        return {"recursive": flag(g("recursive", "true")), "by": by if by in dict(cmp.BY) else "size_time", "tolerance": tolerance,
                "ignore_hour": flag(g("ignore_hour", "true")), "include_same": flag(g("include_same", "false"))}

    def compare_folders(self) -> None:
        """Commands > Compare Folders and Synchronize: the folder of the left panel against the folder of the right."""
        left, right = self._disk_folder_of(self.left), self._disk_folder_of(self.right)
        if not left or not right:
            self._say("Both panels must show a folder to compare them")
            return
        if self.fs.parent(left) == self.fs.parent(right) and self.fs.basename(left) == self.fs.basename(right):
            self._say("Both panels show the same folder")
            return
        dlg = CompareOptionsDialog(self, left, right, self.compare_options())
        if not self._ask_compare_options(dlg):
            return
        values = dlg.values()
        for key, value in values.items():
            self.settings.setValue("compare/" + key, "true" if value is True else "false" if value is False else value)
        state = {"stage": "", "done": 0}

        def work(progress, cancel):
            def report(stage: str, done: int, total: int) -> None:
                state.update(stage=stage, done=done)
                progress(done, 0)
            return cmp.compare_trees(self.fs, left, right, cancel=cancel, progress=report, **values)

        run_in_background(self, self.cmd_runner, "Comparing folders", work, on_result=lambda r: self._compare_found(r, left, right),
                          tracked=self._size_jobs, detail=lambda: f"{state['stage']}: {state['done']:,} items", indeterminate=True,
                          failed_title="Compare Folders")

    def _compare_found(self, result: cmp.CompareResult, left: str, right: str) -> None:
        if not result.rows:
            self.dialogs.info("Compare Folders", f"The two folders are alike: {result.scanned:,} items were compared"
                              + (f"; {result.unreadable} folder{'s' if result.unreadable != 1 else ''} could not be read." if result.unreadable else "."))
            return
        dlg = CompareResultDialog(self, result)
        if not self._ask_compare_result(dlg) or not dlg.action:
            return
        self.compare_action(result, left, right, dlg.action, dlg.actions)

    def compare_action(self, result: cmp.CompareResult, left: str, right: str, action: str, actions: list) -> None:
        if action == "mark":
            paths = []
            for row in result.rows:
                if row.status in (cmp.ONLY_LEFT, cmp.LEFT_NEWER, cmp.DIFFERENT, cmp.TYPE) and row.left is not None:
                    paths.append(row.left.path)
                if row.status in (cmp.ONLY_RIGHT, cmp.RIGHT_NEWER, cmp.DIFFERENT, cmp.TYPE) and row.right is not None:
                    paths.append(row.right.path)
            self.selection.add(paths)
            self._say(f"{len(paths):,} different item{'s' if len(paths) != 1 else ''} marked in the two panels")
            return
        if action != "sync" or not actions:
            return
        summary = sync.summarise(actions)
        plans = sync.build_plans(self.fs, left, right, actions)
        if not plans:
            return
        text = f"Synchronize {left} and {right}:{chr(10)}{chr(10)}{summary.text().capitalize()}." + (
            f"{chr(10)}{human_size(summary.bytes)} will be copied." if summary.bytes else "") + (
            f"{chr(10)}{chr(10)}Deleted items go to the {self._bin_name()}; replaced files are overwritten." if summary.deletes_left or summary.deletes_right
            or summary.replaced else "")
        if not self.dialogs.confirm("Synchronize", text, "Synchronize"):
            return
        for plan in plans:
            ready = self._settle(plan)
            if ready is None:
                return                                         # something is in the way: the reason was shown
            self._run(ready)
        self._say(f"Synchronizing: {summary.text()}")

    def _bin_name(self) -> str:
        from .main_window import BIN
        return BIN

    # two files -------------------------------------------------------------------------------------------------------------------------
    def compare_files(self) -> None:
        """Commands > Compare the Two Current Files: the file under the cursor in each panel, byte by byte."""
        a, b = self.active.current_entry(), self.other.current_entry()
        if a is None or b is None or a.is_dir or b.is_dir or a.kind or b.kind:
            self._say("Put the cursor on a file in each panel to compare the two files")
            return

        def work(progress, cancel):
            progress(0, 0)
            return cmp.first_difference(self.fs, a.path, b.path, cancel)

        def done(pos: int) -> None:
            when = lambda e: datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M:%S") if e.mtime else ""        # noqa: E731
            facts = (f"{a.path}{chr(10)}  {a.size:,} bytes, {when(a)}{chr(10)}{b.path}{chr(10)}  {b.size:,} bytes, {when(b)}")
            if pos < 0:
                self.dialogs.info("Compare Files", f"The two files are identical.{chr(10)}{chr(10)}{facts}")
            else:
                self.dialogs.info("Compare Files", f"The files differ.{chr(10)}The first difference is at byte {pos:,} (offset 0x{pos:X})."
                                  f"{chr(10)}{chr(10)}{facts}")

        run_in_background(self, self.cmd_runner, "Comparing the files", work, on_result=done, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Compare Files")
