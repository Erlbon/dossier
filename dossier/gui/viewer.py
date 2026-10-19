"""The F3 text viewer: one window per call, stepping through the files that were marked (V3).

Read-only. Any size (the file is indexed in the background with progress and cancel), encoding
auto-detected and changeable, find with match case, go to line, follow mode for logs, line numbers,
vertical (column) selection and copy."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QInputDialog, QLabel, QLineEdit, QMainWindow, QPushButton,
                             QToolBar, QWidget)

from ..core.textview import AUTO, ENCODINGS, TextSource, TextTooLarge
from ..core.worker import Job, JobRunner, JobState
from . import icon_set, theme
from .dialogs import ProgressBox
from .line_view import LineView
from .models import human_size
from .qt_bridge import QtDispatcher


class TextViewerWindow(QMainWindow):
    edit_requested = pyqtSignal(str, bool)       # path, open the replace bar too

    def __init__(self, paths: list, index: int = 0, dispatch=None, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.paths = list(paths)
        self.index = 0
        self.source: Optional[TextSource] = None
        self.busy = False
        self._job: Optional[Job] = None
        self._dispatch = dispatch or QtDispatcher(self)      # callbacks must reach the GUI thread
        self._runner = JobRunner(self._dispatch)
        self.resize(960, 620)

        self.view = LineView()
        self.setCentralWidget(self.view)
        self.view.changed.connect(self._update_status)

        bar = QToolBar()
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        self.addToolBar(bar)
        self.prev_file = QPushButton()
        self.next_file = QPushButton()
        for b, name, tip in ((self.prev_file, "arrow-left", "Previous file (Ctrl+Page Up)"),
                             (self.next_file, "arrow-right", "Next file (Ctrl+Page Down)")):
            b.setIcon(icon_set.icon(name, theme.current()["fg"]))
            b.setToolTip(tip)
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bar.addWidget(b)
        self.prev_file.clicked.connect(lambda: self.step(-1))
        self.next_file.clicked.connect(lambda: self.step(1))
        self.file_buttons_visible = len(self.paths) > 1
        self.prev_file.setVisible(self.file_buttons_visible)
        self.next_file.setVisible(self.file_buttons_visible)

        self.encoding = QComboBox()
        self.encoding.addItems(["Auto"] + list(ENCODINGS))
        self.encoding.setToolTip("Text encoding")
        self.encoding.currentTextChanged.connect(self._encoding_changed)
        bar.addWidget(self.encoding)

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find (Ctrl+F)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMinimumWidth(200)
        self.find_edit.returnPressed.connect(lambda: self.find(forward=True))
        bar.addWidget(self.find_edit)
        self.case = QCheckBox("Match case")
        bar.addWidget(self.case)
        for text, icon, forward in (("Previous", "arrow-up", False), ("Next", "chevron-down", True)):
            b = QPushButton(text)
            b.setIcon(icon_set.icon(icon, theme.current()["fg"]))
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, f=forward: self.find(forward=f))
            bar.addWidget(b)
        self.follow = QCheckBox("Follow")
        self.follow.setToolTip("Keep the end of a growing file (a log) in view")
        self.follow.toggled.connect(self._follow_toggled)
        bar.addWidget(self.follow)

        self.status = QLabel()
        self.position = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.position)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)

        edit = QPushButton("Edit (F4)")
        edit.setFlat(True)
        edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit.setIcon(icon_set.icon("file-code", theme.current()["fg"]))
        edit.setToolTip("Open this file in the notepad: Ctrl+H there finds and replaces")
        edit.clicked.connect(lambda: self._edit(False))
        bar.addWidget(edit)
        for keys, slot in ((["F4"], lambda: self._edit(False)), (["Ctrl+H"], lambda: self._edit(True)),
                           (["Esc"], self._escape), (["F3"], self.close), (["Ctrl+F"], self._focus_find),
                           (["Ctrl+G"], self.ask_goto), (["Ctrl+PgDown"], lambda: self.step(1)),
                           (["Ctrl+PgUp"], lambda: self.step(-1)), (["Shift+Return"], lambda: self.find(forward=False))):
            act = QAction(self)
            act.setShortcuts([QKeySequence(k) for k in keys])
            act.triggered.connect(lambda _c=False, s=slot: s())
            self.addAction(act)

        self.load(max(0, min(index, len(self.paths) - 1)))

    def _edit(self, replace: bool) -> None:
        """The viewer reads; the notepad changes. Hand this file over (Ctrl+H opens its replace bar)."""
        if self.source is not None:
            self.edit_requested.emit(self.source.path, replace)

    def _escape(self) -> None:
        """Esc first clears a selection or a found match, and only then closes the window."""
        if self.view.has_selection():
            self.view.clear_selection()
        elif self.view.match is not None:
            self.view.clear_match()
        else:
            self.close()

    # files -----------------------------------------------------------------------------------
    def load(self, index: int) -> None:
        """Show file number ``index`` of the list."""
        if self._job is not None:
            self._job.cancel()
        self.index = index
        if self.source is not None:
            self.source.close()
            self.source = None
        self.view.set_source(None)
        path = self.paths[index]
        self.setWindowTitle(f"Dossier, Subject - {os.path.basename(path)}"
                            + (f" ({index + 1} of {len(self.paths)})" if len(self.paths) > 1 else ""))
        try:
            self.source = TextSource(path, AUTO if self.encoding.currentIndex() == 0 else self.encoding.currentText())
        except OSError as e:
            self.status.setText(f"Cannot open {os.path.basename(path)}: {e.strerror or e}")
            return
        self.view.set_source(self.source)
        self._index_source()

    def step(self, delta: int) -> None:
        if len(self.paths) > 1:
            self.load((self.index + delta) % len(self.paths))

    def _index_source(self) -> None:
        source = self.source
        if source is None:
            return
        self.busy = True
        holder: dict = {}
        box = ProgressBox(self, f"Reading {os.path.basename(source.path)}",
                          lambda: holder["job"].cancel() if "job" in holder else None)

        def work(progress, cancel):
            source.build_index(cancel, progress)

        def progressed(done: int, total: int) -> None:
            box.update(done, total)
            if source is self.source:
                self.view.refresh_counts()

        def finished(job: Job) -> None:
            box.close()
            if source is not self.source:
                return
            self.busy = False
            if job.state is JobState.FAILED and isinstance(job.error, TextTooLarge):
                self.status.setText(str(job.error) + ". Choose another encoding.")
            elif job.state is JobState.FAILED:
                self.status.setText(f"Cannot read the file: {job.error}")
            self.view.refresh_counts()
            self._update_status()

        job = self._runner.submit("Index", work, on_progress=progressed, on_done=finished)
        holder["job"] = job
        self._job = job

    def _encoding_changed(self, text: str) -> None:
        if self.source is None:
            return
        if self._job is not None:
            self._job.cancel()
        self.source.set_encoding(AUTO if text == "Auto" else text)
        self.view.set_source(self.source)
        self._index_source()

    # find ------------------------------------------------------------------------------------
    def _focus_find(self) -> None:
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def find(self, forward: bool = True, _wrapped: bool = False, _from: Optional[tuple] = None) -> None:
        needle = self.find_edit.text()
        source = self.source
        if not needle or source is None or self.busy:
            return
        if _from is not None:
            line, col = _from
        elif self.view.match is not None:
            ml, mc, mlen = self.view.match
            line, col = (ml, mc + 1) if forward else (ml, mc)
        else:
            line, col = self.view.top, 0
        holder: dict = {}
        box = ProgressBox(self, f"Searching for {needle}", lambda: holder["job"].cancel() if "job" in holder else None)
        case = self.case.isChecked()
        self.busy = True

        def work(progress, cancel):
            return source.find(needle, line, col, forward=forward, case_sensitive=case, cancel=cancel, progress=progress)

        def finished(job: Job) -> None:
            box.close()
            self.busy = False
            if source is not self.source or job.state is not JobState.DONE:
                self.status.setText("Search cancelled" if job.state is JobState.CANCELLED else self.status.text())
                return
            hit = job.result
            if hit is not None:
                self.view.show_match(hit[0], hit[1], len(needle))
                self.status.setText("Found after wrapping around" if _wrapped else "Found")
            elif not _wrapped:
                start = (0, 0) if forward else (max(0, source.line_count - 1), 10 ** 9)
                self.find(forward, True, start)
            else:
                self.view.clear_match()
                self.status.setText(f"Not found: {needle}")

        job = self._runner.submit("Find", work, on_progress=box.update, on_done=finished)
        holder["job"] = job

    def ask_goto(self) -> None:
        n, ok = QInputDialog.getInt(self, "Go to Line", "Line number:", self.view.top + 1, 1, max(1, self.view.total))
        if ok:
            self.goto_line_number(n)

    def goto_line_number(self, n: int) -> None:
        self.view.goto_line(n - 1)

    # follow ----------------------------------------------------------------------------------
    def _follow_toggled(self, on: bool) -> None:
        if on:
            self.view.scroll_to_end()
            self._timer.start()
        else:
            self._timer.stop()

    def _poll(self) -> None:
        if self.source is None or self.busy:
            return
        stick = self.view.at_end() or self.follow.isChecked()
        try:
            changed = self.source.refresh()
        except OSError:
            return
        if changed:
            self.view.refresh_counts()
            if stick and self.follow.isChecked():
                self.view.scroll_to_end()

    # status ----------------------------------------------------------------------------------
    def _update_status(self) -> None:
        s = self.source
        if s is None:
            self.position.setText("")
            return
        self.position.setText(f"Line {min(self.view.top + 1, max(s.line_count, 1)):,} of {s.line_count:,}"
                              + ("" if s.complete else " (reading)"))
        if not self.busy and s.binary:
            self.status.setText("This looks like a binary file; text may be unreadable. "
                                f"{s.encoding}, {human_size(s.size)}")
        elif not self.busy and not self.status.text().startswith(("Found", "Not found", "Search")):
            self.status.setText(f"{s.encoding}, {human_size(s.size)}")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._job is not None:
            self._job.cancel()
        self._runner.shutdown(wait=False)
        if self.source is not None:
            self.source.close()
            self.source = None
        super().closeEvent(event)
