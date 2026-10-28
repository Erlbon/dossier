"""The F3 viewer: one window per call, stepping through the files that were marked (V3), in the mode that fits each file.

The mode is chosen by content (``core/viewmodes.py``): text, a picture (fit, zoom, turn, EXIF), a binary file as hex, or Markdown
rendered; the View as box switches a file to any other sensible mode (Markdown as its source, any file as hex).

Read-only. Text: any size (the file is indexed in the background with progress and cancel), encoding auto-detected and
changeable, find with match case, go to line, follow mode for logs, line numbers, vertical (column) selection and copy."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QTextDocument
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QInputDialog, QLabel, QLineEdit, QMainWindow, QPushButton,
                             QStackedWidget, QToolBar, QWidget)

from ..core import markdownsafe, viewmodes
from ..core.exif import read_exif
from ..core.hexview import HexFile, inspect, parse_hex
from ..core.textview import AUTO, ENCODINGS, TextSource, TextTooLarge, detect_encoding
from ..core.worker import Job, JobRunner, JobState
from . import icon_set, theme
from .dialogs import ProgressBox
from .floating_bar import FloatingBar
from .hex_view import HexView
from .image_view import ImagePage, read_image
from .line_view import LineView
from .markdown_view import MarkdownView
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
        self.hexfile: Optional[HexFile] = None
        self.mode = "text"
        self._modes: list = []
        self._pinned = ""                        # a note that the status line keeps until another file or mode is shown
        self.busy = False
        self._job: Optional[Job] = None
        self._dispatch = dispatch or QtDispatcher(self)      # callbacks must reach the GUI thread
        self._runner = JobRunner(self._dispatch)
        self.resize(960, 620)

        self.view = LineView()
        self.hex = HexView()
        self.image_page = ImagePage()
        self.markdown = MarkdownView()
        self.stack = QStackedWidget()
        for page in (self.view, self.image_page, self.hex, self.markdown):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)
        self.view.changed.connect(self._update_status)
        self.hex.changed.connect(self._update_status)
        self.image_page.view.changed.connect(self._update_status)
        self.image_page.view.step_requested.connect(self.step)        # the wheel turns the pages of a folder of pictures
        self.markdown.open_file_requested.connect(self._open_linked)
        self.markdown.refused.connect(lambda text: self.status.setText(f"This link is not opened: {text}"))

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

        self._tb: dict = {"text": [], "find": [], "hex": [], "image": []}      # toolbar entries that belong to some modes only
        self.mode_box = QComboBox()
        self.mode_box.setToolTip("View this file as")
        self.mode_box.currentIndexChanged.connect(self._mode_chosen)
        bar.addWidget(self.mode_box)
        self.encoding = QComboBox()
        self.encoding.addItems(["Auto"] + list(ENCODINGS))
        self.encoding.setToolTip("Text encoding")
        self.encoding.currentTextChanged.connect(self._encoding_changed)
        self._tb["text"].append(bar.addWidget(self.encoding))

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find (Ctrl+F)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMinimumWidth(200)
        self.find_edit.returnPressed.connect(lambda: self.find(forward=True))
        self._tb["find"].append(bar.addWidget(self.find_edit))
        self.hex_find_kind = QComboBox()
        self.hex_find_kind.addItems(["Text", "Hex bytes"])
        self.hex_find_kind.setToolTip("What the find box holds")
        self._tb["hex"].append(bar.addWidget(self.hex_find_kind))
        self.case = QCheckBox("Match case")
        self._tb["find"].append(bar.addWidget(self.case))
        for text, icon, forward in (("Previous", "arrow-up", False), ("Next", "chevron-down", True)):
            b = QPushButton(text)
            b.setIcon(icon_set.icon(icon, theme.current()["fg"]))
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, f=forward: self.find(forward=f))
            self._tb["find"].append(bar.addWidget(b))
        self.follow = QCheckBox("Follow")
        self.follow.setToolTip("Keep the end of a growing file (a log) in view")
        self.follow.toggled.connect(self._follow_toggled)
        self._tb["text"].append(bar.addWidget(self.follow))
        self.image_info = QCheckBox("Info (I)")
        self.image_info.setToolTip("The file's facts and, for a photo, its EXIF")
        self.image_info.toggled.connect(self.image_page.show_info)
        self._tb["image"].append(bar.addWidget(self.image_info))
        self.floating = FloatingBar(self.image_page.view.viewport(), self.image_page.view, self.step, self.close)   # zoom, fit, turn: over the picture

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
        self.edit_button = edit
        bar.addWidget(edit)
        for keys, slot in ((["F4"], lambda: self._edit(False)), (["Ctrl+H"], lambda: self._edit(True)),
                           (["Esc"], self._escape), (["F3"], self.close), (["Ctrl+F"], self._focus_find),
                           (["Ctrl+G"], self.ask_goto), (["Ctrl+PgDown"], lambda: self.step(1)),
                           (["Ctrl+PgUp"], lambda: self.step(-1)), (["Shift+Return"], lambda: self.find(forward=False)),
                           (["I"], self._toggle_info)):
            act = QAction(self)
            act.setShortcuts([QKeySequence(k) for k in keys])
            act.triggered.connect(lambda _c=False, s=slot: s())
            self.addAction(act)

        self.load(max(0, min(index, len(self.paths) - 1)))

    def _edit(self, replace: bool) -> None:
        """The viewer reads; the notepad changes. Hand this file over (Ctrl+H opens its replace bar). Pictures and binary files are not
        text and are not edited."""
        if self.mode in ("image", "hex"):
            self.status.setText("A picture or a binary file is not edited as text")
            return
        if self.paths:
            self.edit_requested.emit(self.paths[self.index], replace)

    def _escape(self) -> None:
        """Esc first clears a selection or a found match, and only then closes the window."""
        if self.mode == "text" and self.view.has_selection():
            self.view.clear_selection()
        elif self.mode == "text" and self.view.match is not None:
            self.view.clear_match()
        elif self.mode == "hex" and self.hex.match is not None:
            self.hex.clear_match()
        else:
            self.close()

    # files -----------------------------------------------------------------------------------
    def load(self, index: int) -> None:
        """Show file number ``index`` of the list, in the mode that fits what is inside it."""
        self.index = index
        path = self.paths[index]
        self.setWindowTitle(f"Dossier, Subject - {os.path.basename(path)}"
                            + (f" ({index + 1} of {len(self.paths)})" if len(self.paths) > 1 else ""))
        self._modes = viewmodes.modes_for(path)
        blocked = self.mode_box.blockSignals(True)
        self.mode_box.clear()
        for m in self._modes:
            self.mode_box.addItem(viewmodes.LABELS[m], m)
        self.mode_box.blockSignals(blocked)
        self.enter_mode(self._modes[0])

    def _mode_chosen(self, i: int) -> None:
        if 0 <= i < len(self._modes) and self._modes[i] != self.mode:
            self.enter_mode(self._modes[i])

    def _close_current(self) -> None:
        if self._job is not None:
            self._job.cancel()
        if self.source is not None:
            self.source.close()
            self.source = None
        self.view.set_source(None)
        if self.hexfile is not None:
            self.hex.set_file(None)
            self.hexfile.close()
            self.hexfile = None
        self.image_page.view.set_image(None)
        self.image_page.info.clear()
        self.busy = False

    def enter_mode(self, mode: str) -> None:
        """Show the current file in ``mode`` (text, hex, image or markdown)."""
        self._close_current()
        self.mode = mode
        self._pinned = ""
        self.status.setText("")
        self.position.setText("")
        blocked = self.mode_box.blockSignals(True)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(mode)))
        self.mode_box.blockSignals(blocked)
        for kind, actions in self._tb.items():
            show = {"text": mode == "text", "find": mode in ("text", "hex", "markdown"), "hex": mode == "hex",
                    "image": mode == "image"}[kind]
            for action in actions:
                action.setVisible(show)
        self.edit_button.setEnabled(mode in ("text", "markdown"))
        self.floating.set_stepping(len(self.paths) > 1)
        self.floating.set_enabled(mode == "image")
        path = self.paths[self.index]
        {"text": self._open_text, "hex": self._open_hex, "image": self._open_image, "markdown": self._open_markdown}[mode](path)
        self._focus_page()

    def _focus_page(self) -> None:
        page = self.stack.currentWidget()
        if page is not None:
            page.setFocus()

    def _open_text(self, path: str) -> None:
        self.stack.setCurrentWidget(self.view)
        try:
            self.source = TextSource(path, AUTO if self.encoding.currentIndex() == 0 else self.encoding.currentText())
        except OSError as e:
            self.status.setText(f"Cannot open {os.path.basename(path)}: {e.strerror or e}")
            return
        self.view.set_source(self.source)
        self._index_source()

    def _open_hex(self, path: str) -> None:
        self.stack.setCurrentWidget(self.hex)
        try:
            self.hexfile = HexFile(path)
        except OSError as e:
            self.status.setText(f"Cannot open {os.path.basename(path)}: {e.strerror or e}")
            return
        self.hex.set_file(self.hexfile)
        self._update_status()

    def _open_markdown(self, path: str) -> None:
        try:
            size = os.path.getsize(path)
        except OSError as e:
            self.status.setText(f"Cannot open {os.path.basename(path)}: {e.strerror or e}")
            return
        if markdownsafe.too_big(size):
            self.enter_mode("text")
            self._pinned = f"{human_size(size)} is too big to render as Markdown (the limit is 256 KB): shown as text"
            self.status.setText(self._pinned)
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self.status.setText(f"Cannot open {os.path.basename(path)}: {e.strerror or e}")
            return
        encoding = detect_encoding(data[:65536])
        self.stack.setCurrentWidget(self.markdown)
        self.markdown.set_markdown(data.decode(encoding, "replace").lstrip("\ufeff"), os.path.dirname(path))
        self.status.setText(f"Markdown, {human_size(size)}. Links open only to the web, mail and files on this computer")

    def _open_image(self, path: str) -> None:
        self.stack.setCurrentWidget(self.image_page)
        self.status.setText("Reading the picture...")
        holder: dict = {}

        def work(progress, cancel):
            progress(0, 0)
            return read_image(path), read_exif(path)

        def finished(job: Job) -> None:
            if path != self.paths[self.index] or self.mode != "image":
                return
            if job.state is not JobState.DONE or job.result is None or job.result[0].isNull():
                self.status.setText("This picture cannot be decoded here. View as: Hex shows what is in the file")
                return
            image, exif = job.result
            self.image_page.view.set_image(image)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            kind = viewmodes.image_kind(viewmodes.read_head(path), path)
            facts = [("Name", os.path.basename(path)), ("Size", human_size(size)),
                     ("Dimensions", f"{image.width()} x {image.height()} pixels"), ("Format", kind.upper() or "?")]
            self.image_page.info.show_info(facts, exif)
            self._update_status()

        job = self._runner.submit("Picture", work, on_done=finished)
        holder["job"] = job
        self._job = job

    def _open_linked(self, path: str) -> None:
        """A link in a Markdown file to a file on this computer: show it next, in this window."""
        if not os.path.isfile(path):
            self.status.setText(f"No such file: {path}")
            return
        self.paths.insert(self.index + 1, path)
        self.prev_file.setVisible(True)
        self.next_file.setVisible(True)
        self.load(self.index + 1)

    def _toggle_info(self) -> None:
        if self.mode == "image":
            self.image_info.setChecked(not self.image_info.isChecked())

    def set_wheel_map(self, wheel_map: dict) -> None:
        self.image_page.view.wheel_map = dict(wheel_map)

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
        if self.mode == "hex":
            return self._find_hex(forward)
        if self.mode == "markdown":
            return self._find_markdown(forward)
        if self.mode == "image":
            return
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

    def _find_markdown(self, forward: bool) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.markdown.find(needle, flags):
            self.status.setText("Found")
            return
        cursor = self.markdown.textCursor()                      # wrap around once
        cursor.movePosition(cursor.MoveOperation.Start if forward else cursor.MoveOperation.End)
        self.markdown.setTextCursor(cursor)
        self.status.setText("Found after wrapping around" if self.markdown.find(needle, flags) else f"Not found: {needle}")

    def _find_hex(self, forward: bool) -> None:
        text = self.find_edit.text()
        file = self.hexfile
        if not text or file is None:
            return
        if self.hex_find_kind.currentIndex() == 1:
            pattern = parse_hex(text)
            if pattern is None:
                self.status.setText("Hex bytes are pairs of digits, for example DE AD BE EF")
                return
        else:
            pattern = text.encode("utf-8")
        ignore_case = self.hex_find_kind.currentIndex() == 0 and not self.case.isChecked()       # bytes are always exact
        start = self.hex.cursor + 1 if forward else self.hex.cursor
        if self.hex.match is not None and forward:
            start = self.hex.match[0] + 1
        if self._job is not None:
            self._job.cancel()
        self.status.setText("Searching...")

        def work(progress, cancel):
            return file.find(pattern, start, forward=forward, cancel=cancel, ignore_case=ignore_case)

        def finished(job: Job) -> None:
            if file is not self.hexfile or job is not self._job:          # a search that was replaced by a newer one
                return
            if job.state is not JobState.DONE:
                self.status.setText("Search cancelled" if job.state is JobState.CANCELLED else f"Search failed: {job.error}")
            elif job.result < 0:
                self.hex.clear_match()
                self.status.setText(f"Not found: {text}")
            else:
                self.hex.show_match(job.result, len(pattern))
                self.status.setText(f"Found at offset 0x{job.result:X} ({job.result:,})")

        self._job = self._runner.submit("Find", work, on_done=finished)

    def ask_goto(self) -> None:
        if self.mode == "hex" and self.hexfile is not None:
            text, ok = QInputDialog.getText(self, "Go to Offset", "Offset (decimal, or hexadecimal with 0x):")
            if ok and text.strip():
                try:
                    offset = int(text.strip(), 16 if text.strip().lower().startswith("0x") else 10)
                except ValueError:
                    self.status.setText(f"Not an offset: {text}")
                    return
                self.hex.goto(offset)
            return
        if self.mode != "text":
            return
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
        if self.mode == "hex" and self.hexfile is not None:
            self.hex.refresh()
            return
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
        if self.mode == "hex":
            return self._hex_status()
        if self.mode == "image":
            view = self.image_page.view
            w, h = view.image_size()
            self.position.setText(f"{w} x {h}   {view.zoom * 100:.0f}%" if view.has_image() else "")
            if view.has_image() and self.status.text().startswith("Reading"):
                self.status.setText("")
            return
        if self.mode == "markdown":
            return
        s = self.source
        if s is None:
            self.position.setText("")
            return
        self.position.setText(f"Line {min(self.view.top + 1, max(s.line_count, 1)):,} of {s.line_count:,}"
                              + ("" if s.complete else " (reading)"))
        pinned = bool(self._pinned) and self.status.text() == self._pinned
        if not self.busy and s.binary and not pinned:
            self.status.setText("This looks like a binary file; text may be unreadable. "
                                f"{s.encoding}, {human_size(s.size)}")
        elif not self.busy and not pinned and not self.status.text().startswith(("Found", "Not found", "Search")):
            self.status.setText(f"{s.encoding}, {human_size(s.size)}")

    def _hex_status(self) -> None:
        f = self.hexfile
        if f is None:
            self.position.setText("")
            return
        lo, n = self.hex.selection()
        self.position.setText(f"Offset 0x{lo:X} ({lo:,}) of {f.size:,}" + (f"   {n:,} bytes selected" if n > 1 else ""))
        if not self.status.text().startswith(("Found", "Not found", "Search", "Hex bytes")):
            numbers = "   ".join(f"{label} {text.split('  ')[0]}" for label, text in inspect(f.read(lo, 8))[:3])
            self.status.setText(f"{human_size(f.size)}   {numbers}")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._close_current()
        self._runner.shutdown(wait=False)
        super().closeEvent(event)
