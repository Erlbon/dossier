"""Tools > Check Folder Health...: the file health checks (``core/health.py``) in a window.

The findings are grouped by rule on the left (worst first, with "All findings" on top); the files of the chosen group are on the right, with
what is wrong and what would put it right. A fix is previewed as the plan it is, then run through the ordinary queue (conflict dialog, progress,
Cancel, the recycle bin, undo for renames and same-drive moves). Findings can be marked in the panel, or a rule ignored below the checked folder.
The check runs on a thread with progress and a Stop; a stopped run keeps what it found.
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget, QAbstractItemView)

from ..core import health
from ..core.ops import describe_op
from ..core.progress import CancelToken

MAX_ROWS = 5000
ALL = ""                                                     # the data of the "All findings" row
SEVERITY_COLOURS = {health.ERROR: "#e0605e", health.WARNING: "#d9a05b", health.INFO: "#8a93a6"}
KIND_ORDER = ("rename", "quarantine", "delete")
KIND_TITLES = {"rename": "Rename", "quarantine": "Move to the quarantine folder", "delete": "Delete to the recycle bin"}


class _Row(QTreeWidgetItem):
    """A table row that sorts severity by how bad it is, not by its letters."""

    def __lt__(self, other) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() is not None else 0
        if column == 0:
            a, b = self.data(0, Qt.ItemDataRole.UserRole + 1), other.data(0, Qt.ItemDataRole.UserRole + 1)
            if a != b:
                return a < b
        return self.text(column).lower() < other.text(column).lower()


class PlanPreview(QDialog):
    """The steps a fix would take, listed; nothing has happened yet."""

    def __init__(self, parent, plans: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview of the fix")
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        steps = 0
        lines: list = []
        for plan in plans:
            moves = [op for op in plan.ops if op.kind.value != "mkdir"]
            steps += len(moves)
            lines.append(f"{plan.title}: {len(moves):,} step{'s' if len(moves) != 1 else ''}")
            lines += ["  " + describe_op(op) for op in plan.ops[:500]]
            if len(plan.ops) > 500:
                lines.append(f"  ... and {len(plan.ops) - 500:,} more")
            lines += [f"  note: {w}" for w in plan.warnings[:20]] + [f"  CANNOT RUN: {b}" for b in plan.blocking[:20]]
            lines.append("")
        self.summary = QLabel(f"{steps:,} step{'s' if steps != 1 else ''} in {len(plans)} plan{'s' if len(plans) != 1 else ''}. Nothing is changed "
                              "until you press Run; names that are taken are asked about then, and nothing is replaced without asking.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.text = QPlainTextEdit(chr(10).join(lines))
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.run = buttons.addButton("Run", QDialogButtonBox.ButtonRole.AcceptRole)
        self.run.setDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HealthWindow(QDialog):
    def __init__(self, win, folder: str, deep: bool = False, start: bool = True) -> None:
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Check Folder Health")
        self.setModal(False)
        self.resize(1040, 620)
        self.findings: list = []
        self.ignores = health.IgnoreList()
        self.report: Optional[health.Report] = None
        self._job = None
        self._cancel: Optional[CancelToken] = None
        self._closed = False
        self._shown: list = []                                       # the findings on the right, in the order of the table rows

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Checking"))
        self.folder = QLineEdit(folder)
        top.addWidget(self.folder, 1)
        self.browse = QPushButton("Browse...")
        self.browse.setAutoDefault(False)
        self.browse.clicked.connect(self._browse)
        top.addWidget(self.browse)
        self.deep = QCheckBox("Deep (reads whole zip files)")
        self.deep.setChecked(deep)
        top.addWidget(self.deep)
        self.check_button = QPushButton("Check")
        self.check_button.setAutoDefault(False)
        self.check_button.clicked.connect(self._check_or_stop)
        top.addWidget(self.check_button)
        layout.addLayout(top)
        self.counts = QLabel()
        layout.addWidget(self.counts)

        split = QSplitter()
        self.groups = QListWidget()
        self.groups.setMinimumWidth(190)
        self.groups.currentRowChanged.connect(lambda _row: self._show_group())
        split.addWidget(self.groups)
        right = QWidget()
        box = QVBoxLayout(right)
        box.setContentsMargins(0, 0, 0, 0)
        self.table = QTreeWidget()
        self.table.setColumnCount(5)
        self.table.setHeaderLabels(["Severity", "Item", "Folder", "What", "Fix"])
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)                           # every header resizes and sorts
        self.table.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        box.addWidget(self.table, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.detail)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("Preview fix...")
        self.fix_button = QPushButton("Fix")
        self.mark_button = QPushButton("Mark in the panel")
        self.ignore_button = QPushButton("Ignore this rule here")
        self.reset_button = QPushButton("Show ignored")
        self.copy_button = QPushButton("Copy list")
        for b in (self.preview_button, self.fix_button, self.mark_button, self.ignore_button, self.reset_button, self.copy_button):
            b.setAutoDefault(False)
            actions.addWidget(b)
        actions.addStretch(1)
        box.addLayout(actions)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 800])
        layout.addWidget(split, 1)
        self.status = QLabel("")
        layout.addWidget(self.status)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.close)
        layout.addWidget(close)

        self.preview_button.clicked.connect(lambda: self._fix(preview=True))
        self.fix_button.clicked.connect(lambda: self._fix(preview=False))
        self.mark_button.clicked.connect(self.mark_in_panel)
        self.ignore_button.clicked.connect(self.ignore_rule)
        self.reset_button.clicked.connect(self.show_ignored)
        self.copy_button.clicked.connect(self.copy_list)
        self.refresh()
        if start:
            self.start()

    # running the check ----------------------------------------------------------------------------------------------------------------
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder to check", self.folder.text())
        if path:
            self.folder.setText(os.path.normpath(path))

    def _check_or_stop(self) -> None:
        if self._job is not None:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        root = self.folder.text().strip()
        if not root or self._job is not None:
            return
        self.findings, self.report = [], None
        self.ignores.clear()
        self.refresh()
        self._cancel = CancelToken()
        cancel, tier, fs = self._cancel, (health.T2 if self.deep.isChecked() else health.T1), self.win.fs

        def work(progress, token):
            return health.run_checks(fs, [root], max_tier=tier, cancel=cancel, partial_on_cancel=True,
                                     progress=lambda done, found: progress(done, found))

        def on_progress(done: int, found: int) -> None:
            if not self._closed:
                self.status.setText(f"Checking... {done:,} files looked at, {found:,} findings so far")

        def finished(job) -> None:
            self._job = None
            if self._closed:
                return
            self.check_button.setText("Check")
            if job.error is not None or job.result is None:
                self.status.setText(f"The check could not run: {job.error}")
                return
            self.report = job.result
            self.findings = list(self.report.findings)
            self.refresh()
            note = " (stopped: this is what was found until then)" if self.report.cancelled else ""
            unread = f"; {self.report.unreadable} item(s) could not be read" if self.report.unreadable else ""
            self.status.setText(f"Looked at {self.report.files:,} files in {self.report.folders:,} folders{note}{unread}.")
        self.check_button.setText("Stop")
        self.status.setText("Checking...")
        self._job = self.win.cmd_runner.submit("Checking folder health", work, on_progress=on_progress, on_done=finished)

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
        self.status.setText("Stopping...")

    def done(self, result: int) -> None:
        self._closed = True
        if self._cancel is not None:
            self._cancel.cancel()
        super().done(result)

    # what is shown ----------------------------------------------------------------------------------------------------------------------
    def visible(self) -> list:
        return self.ignores.visible(self.findings)

    def current_rule(self) -> Optional[str]:
        item = self.groups.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def refresh(self) -> None:
        """Rebuild the group list (keeping the chosen one when it is still there) and the table."""
        wanted = self.current_rule()
        visible = self.visible()
        groups = health.group_by_rule(visible)
        counts = {s: sum(1 for f in visible if f.severity == s) for s in health.SEVERITIES}
        self.counts.setText(f"{counts[health.ERROR]:,} errors   {counts[health.WARNING]:,} warnings   {counts[health.INFO]:,} notes"
                            + (f"   ({len(self.findings) - len(visible):,} hidden by ignored rules)" if len(visible) != len(self.findings) else ""))
        blocked = self.groups.blockSignals(True)
        self.groups.clear()
        everything = QListWidgetItem(f"All findings   {len(visible):,}")
        everything.setData(Qt.ItemDataRole.UserRole, ALL)
        self.groups.addItem(everything)
        for g in groups:
            row = QListWidgetItem(f"● {g.rule}   {g.count:,}")
            row.setData(Qt.ItemDataRole.UserRole, g.rule)
            row.setForeground(QColor(SEVERITY_COLOURS[g.severity]))
            row.setToolTip(f"{g.severity}; {g.fixable:,} of {g.count:,} can be fixed")
            self.groups.addItem(row)
        index = next((i for i in range(self.groups.count()) if self.groups.item(i).data(Qt.ItemDataRole.UserRole) == wanted), 0)
        self.groups.setCurrentRow(index)
        self.groups.blockSignals(blocked)
        self._show_group()

    def group_findings(self) -> list:
        rule = self.current_rule()
        visible = self.visible()
        return visible if not rule else [f for f in visible if f.rule == rule]

    def _show_group(self) -> None:
        findings = self.group_findings()
        self.table.setSortingEnabled(False)
        self.table.clear()
        self._shown = findings[:MAX_ROWS]
        for i, f in enumerate(self._shown):
            row = _Row([f.severity, os.path.basename(f.path), os.path.dirname(f.path), f.message, f.fix.label if f.fix else ""])
            row.setData(0, Qt.ItemDataRole.UserRole, i)
            row.setData(0, Qt.ItemDataRole.UserRole + 1, health.SEVERITIES.index(f.severity))
            row.setForeground(0, QColor(SEVERITY_COLOURS[f.severity]))
            row.setToolTip(1, f.path)
            self.table.addTopLevelItem(row)
        for column, widest in enumerate((120, 260, 300, 560, 220)):          # as wide as the text needs (the header too), but not wider than this
            self.table.resizeColumnToContents(column)
            self.table.setColumnWidth(column, min(self.table.columnWidth(column) + 14, widest))
        self.table.setSortingEnabled(True)
        if len(findings) > MAX_ROWS:
            self.detail.setText(f"Showing the first {MAX_ROWS:,} of {len(findings):,}. The buttons below act on all of them; "
                                "choose a rule on the left to narrow the list.")
        self._selection_changed()

    def selected(self) -> list:
        """The findings of the selected rows (the whole group when nothing is selected)."""
        rows = self.table.selectedItems()
        if not rows:
            return self.group_findings()
        return [self._shown[r.data(0, Qt.ItemDataRole.UserRole)] for r in rows]

    def _selection_changed(self) -> None:
        chosen = self.selected()
        rows = self.table.selectedItems()
        fixable = [f for f in chosen if f.fix]
        if len(rows) == 1:
            f = self._shown[rows[0].data(0, Qt.ItemDataRole.UserRole)]
            self.detail.setText(f"{f.path}{chr(10)}{f.message}" + (f" ({f.evidence})" if f.evidence else "")
                                + (f"{chr(10)}Fix: {f.fix.label}" + (f" to {f.fix.new_name}" if f.fix.new_name else "") if f.fix else ""))
        elif len(self.group_findings()) <= MAX_ROWS:
            self.detail.setText("")
        self.fix_button.setText(f"Fix selected ({len(fixable):,})" if rows else f"Fix all {len(fixable):,}")
        self.fix_button.setEnabled(bool(fixable))
        self.preview_button.setEnabled(bool(fixable))
        self.mark_button.setEnabled(bool(chosen))
        self.ignore_button.setEnabled(bool(chosen))
        self.reset_button.setVisible(len(self.ignores) > 0)
        self.copy_button.setEnabled(bool(self.group_findings()))

    # acting on findings ------------------------------------------------------------------------------------------------------------------
    def mark_in_panel(self) -> None:
        """Put the checked files into the shared selection, and show the folder they are in when it is just one."""
        paths = [f.path for f in self.selected()]
        if not paths:
            return
        self.win.selection.add(paths)
        folders = {os.path.dirname(p) for p in paths}
        if len(folders) == 1 and not self.win.active.is_home:
            self.win.active.set_folder(next(iter(folders)), select=os.path.basename(paths[0]))
        self.status.setText(f"Marked {len(paths):,} item{'s' if len(paths) != 1 else ''}: use any command on them in the panels.")

    def ignore_rule(self) -> None:
        rules = {f.rule for f in self.selected()}
        if not rules:
            return
        for rule in rules:
            self.ignores.add(self.folder.text().strip(), rule)
        self.status.setText(f"Ignoring {', '.join(sorted(rules))} below {self.folder.text().strip()} until the next check.")
        self.refresh()

    def show_ignored(self) -> None:
        self.ignores.clear()
        self.status.setText("Ignored rules are shown again.")
        self.refresh()

    def copy_list(self) -> None:
        lines = ["\t".join((f.severity, f.rule, f.path, f.message, f.evidence)) for f in self.group_findings()]
        QApplication.clipboard().setText(chr(10).join(lines))
        self.status.setText(f"Copied {len(lines):,} line{'s' if len(lines) != 1 else ''}.")

    def plans_for(self, findings: list):
        """One fix plan for each kind of fix among ``findings`` (a plan holds one kind), made on a thread by the caller."""
        quarantine = self.win.quarantine_settings()
        fs = self.win.fs
        plans = []
        for kind in KIND_ORDER:
            of_kind = [f for f in findings if f.fix and f.fix.kind == kind]
            if of_kind:
                plan = health.fix_plan(fs, of_kind, quarantine)
                if plan is not None:
                    plans.append(plan)
        return plans

    def _fix(self, preview: bool) -> None:
        chosen = [f for f in self.selected() if f.fix]
        if not chosen:
            return
        self.win._plan_in_background("Preparing the fix", lambda watch: self.plans_for(chosen), lambda plans: self._planned(plans, preview))

    def _planned(self, plans: list, preview: bool) -> None:
        if not plans:
            self.status.setText("Nothing to fix.")
            return
        if preview or any(p.blocking for p in plans):
            dialog = PlanPreview(self, plans)
            self._show_preview(dialog)
            if dialog.result() != QDialog.DialogCode.Accepted or any(p.blocking for p in plans):
                return
        for plan in plans:
            ready = self.win._settle(plan)                          # conflicts are asked about, never replaced
            if ready is not None:
                self.win._run(ready, on_done=self._fixed)

    def _show_preview(self, dialog) -> None:                        # a seam for tests
        dialog.exec()

    def _fixed(self, job) -> None:
        """A fix finished: what was done is no longer a finding."""
        result = job.result
        if result is None or self._closed:
            return
        gone = {r.op.src for r in result.done if r.op.src}
        self.findings = [f for f in self.findings if f.path not in gone]
        self.refresh()
        failed = len(result.failed)
        self.status.setText(f"Fixed {len(result.done):,} item{'s' if len(result.done) != 1 else ''}" + (f"; {failed} could not be changed" if failed else "") + ".")


class HealthMixin:
    """Part of ``MainWindow``."""

    def check_folder_health(self) -> None:
        panel = self.active
        if panel.is_home or "://" in panel.path:
            self._say("Open a folder on a drive of this computer first: that is the folder the health check looks through")
            return
        window = HealthWindow(self, panel.real_folder())
        windows = self.__dict__.setdefault("_health_windows", [])
        windows.append(window)
        window.finished.connect(lambda _r, w=window: windows.remove(w) if w in windows else None)
        self._show_health_window(window)

    def _show_health_window(self, window) -> None:              # a seam for tests
        window.show()
