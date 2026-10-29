"""The F3 viewer: one window per call, stepping through the files that were marked (V3), in the mode that fits each file.

The mode is chosen by content (``core/viewmodes.py``): text, a picture (fit, zoom, turn, EXIF), a binary file as hex, or Markdown
rendered; the View as box switches a file to any other sensible mode (Markdown as its source, any file as hex).

Read-only. Text: any size (the file is indexed in the background with progress and cancel), encoding auto-detected and
changeable, find with match case, go to line, follow mode for logs, line numbers, vertical (column) selection and copy."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QTextDocument
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..core import markdownsafe, viewmodes
from ..core.exif import read_exif
from ..core.hexview import HexFile, inspect, parse_hex
from ..core.textview import AUTO, ENCODINGS, TextSource, TextTooLarge, detect_encoding
from ..core.worker import Job, JobRunner, JobState
from . import icon_set, theme
from .dialogs import ProgressBox
from .floating_bar import FloatingBar, Toast
from .frost_window import FrostSurface
from .hex_view import HexView
from .image_view import ImagePage, read_image
from .line_view import LineView
from .markdown_view import MarkdownView
from .models import human_size
from .qt_bridge import QtDispatcher


class TextViewerWindow(FrostSurface, QMainWindow):
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
        central = QWidget()
        self._central_layout = QVBoxLayout(central)
        self._central_layout.setContentsMargins(0, 0, 0, 0)
        self._central_layout.setSpacing(0)
        self._central_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.view.changed.connect(self._update_status)
        self.hex.changed.connect(self._update_status)
        self.image_page.view.changed.connect(self._update_status)
        self.image_page.view.step_requested.connect(self.step)        # the wheel turns the pages of a folder of pictures
        self.markdown.open_file_requested.connect(self._open_linked)
        self.markdown.refused.connect(lambda text: self.status.setText(f"This link is not opened: {text}"))

        # no toolbar and no status line: one floating bar over the page (built below), a find strip under it that shows on request, and
        # messages that float for a few seconds. The widgets below hold the state and the settings menu drives them.
        self.mode_box = QComboBox()
        self.mode_box.currentIndexChanged.connect(self._mode_chosen)
        self.encoding = QComboBox()
        self.encoding.addItems(["Auto"] + list(ENCODINGS))
        self.encoding.currentTextChanged.connect(self._encoding_changed)
        self.hex_find_kind = QComboBox()
        self.hex_find_kind.addItems(["Text", "Hex bytes"])
        self.hex_find_kind.setToolTip("What the find box holds")
        self.case = QCheckBox("Match case")
        self.follow = QCheckBox("Follow")
        self.follow.setToolTip("Keep the end of a growing file (a log) in view")
        self.follow.toggled.connect(self._follow_toggled)
        self.image_info = QCheckBox("Info (I)")
        self.image_info.toggled.connect(self.image_page.show_info)
        self.file_buttons_visible = len(self.paths) > 1
        self._build_find_strip()
        self.status = Toast(self.stack)
        self._build_pill()
        self.statusBar().hide()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)

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
        """Esc first clears a selection or a found match (or hides the find strip), and only then closes the window."""
        if self.find_strip.isVisible():
            self.find_strip.hide()
            self._focus_page()
        elif self.mode == "text" and self.view.has_selection():
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

    def _build_find_strip(self) -> None:
        """The find box, under the page, shown by the Find button or Ctrl+F and hidden by Esc."""
        strip = self.find_strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(8, 4, 8, 4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find (Ctrl+F)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMinimumWidth(200)
        self.find_edit.returnPressed.connect(lambda: self.find(forward=True))
        row.addWidget(self.find_edit, 1)
        row.addWidget(self.hex_find_kind)
        row.addWidget(self.case)
        for text, icon, forward in (("Previous", "arrow-up", False), ("Next", "chevron-down", True)):
            b = QPushButton(text)
            b.setIcon(icon_set.icon(icon, theme.current()["fg"]))
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, f=forward: self.find(forward=f))
            row.addWidget(b)
        strip.hide()
        self._central_layout.addWidget(strip)

    def _build_pill(self) -> None:
        """The window's one bar, over the page: the buttons that fit the kind of file are shown (see ``_arrange_pill``)."""
        view = self.image_page.view
        bar = self.floating = FloatingBar(self.stack, self.stack, self.step, self.close,
                                          specs=(("prev", "◀", "Previous file (Ctrl+Page Up)", lambda: self.step(-1)),
                                                 ("next", "▶", "Next file (Ctrl+Page Down)", lambda: self.step(1)),
                                                 ("close", "✕", "Close (Esc, F3)", self.close)))
        self._pill = {"sep_files": bar.add_separator()}
        self.edit_button = bar.add_button("edit", "Edit", "Open this file in the notepad (F4): Ctrl+H there finds and replaces",
                                          lambda: self._edit(False), icon="file-code")
        bar.add_button("find", "Find", "Find (Ctrl+F)", self._focus_find, icon="search")
        bar.add_button("goto", "Go to", "Go to a line or an offset (Ctrl+G)", self.ask_goto, icon="hash")
        for key, glyph, tip, slot in (("out", "−", "Zoom out (-)", lambda: view.zoom_by(0.8)),
                                      ("in", "+", "Zoom in (+)", lambda: view.zoom_by(1.25)),
                                      ("fit", "▢", "Fit to the window (0)", lambda: view.fit()),
                                      ("actual", "1:1", "Every pixel (1)", lambda: view.actual_size()),
                                      ("left", "↶", "Turn left (L)", lambda: view.turn(-1)),
                                      ("right", "↷", "Turn right (R)", lambda: view.turn(1))):
            bar.add_button(key, glyph, tip, slot)
        self.info_button = bar.add_button("info", "ⓘ", "The file's facts and, for a photo, its EXIF (I)", lambda: None, checkable=True)
        self.info_button.clicked.connect(self.image_info.setChecked)
        self.image_info.toggled.connect(self.info_button.setChecked)
        self._pill["sep_tools"] = bar.add_separator()
        self.position = bar.add_label()
        bar.add_button("settings", "Settings", "View as, encoding, follow", self._popup_settings, icon="settings")
        for page in (self.view, self.hex, self.markdown, view):
            bar.watch(page)

    PILL_KEYS = {"text": ("edit", "find", "goto"), "hex": ("find", "goto"), "markdown": ("edit", "find"),
                 "image": ("out", "in", "fit", "actual", "left", "right", "info")}

    def _arrange_pill(self) -> None:
        """Show the buttons that belong to this kind of file and the file buttons only when there is more than one file."""
        bar = self.floating
        every = {key for keys in self.PILL_KEYS.values() for key in keys}
        wanted = set(self.PILL_KEYS.get(self.mode, ()))
        for key in every:
            bar.buttons[key].setVisible(key in wanted)
        stepping = len(self.paths) > 1
        bar.buttons["prev"].setVisible(stepping)
        bar.buttons["next"].setVisible(stepping)
        self._pill["sep_files"].setVisible(stepping)
        self.position.setVisible(self.mode != "markdown")
        bar.set_enabled(True)
        bar.bar.adjustSize()
        bar.place()

    def _settings_menu(self) -> QMenu:
        """View as, and for text the encoding and following a growing file: what stays set while you read."""
        menu = QMenu(self)
        view_as = menu.addMenu("View As")
        for m in self._modes:
            act = view_as.addAction(viewmodes.LABELS[m])
            act.setCheckable(True)
            act.setChecked(m == self.mode)
            act.triggered.connect(lambda _c=False, m=m: self.enter_mode(m) if m != self.mode else None)
        if self.mode == "text":
            menu.addSeparator()
            encoding = menu.addMenu("Encoding")
            for i in range(self.encoding.count()):
                act = encoding.addAction(self.encoding.itemText(i))
                act.setCheckable(True)
                act.setChecked(i == self.encoding.currentIndex())
                act.triggered.connect(lambda _c=False, i=i: self.encoding.setCurrentIndex(i))
            follow = menu.addAction("Follow the End of the File")
            follow.setToolTip(self.follow.toolTip())
            follow.setCheckable(True)
            follow.setChecked(self.follow.isChecked())
            follow.triggered.connect(lambda checked=False: self.follow.setChecked(bool(checked)))
        return menu

    def _popup_settings(self) -> None:
        menu = self._settings_menu()
        button = self.floating.buttons["settings"]
        menu.popup(button.mapToGlobal(button.rect().topLeft()) - QPoint(0, menu.sizeHint().height()))

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
        if mode == "image":
            self.find_strip.hide()
        self.hex_find_kind.setVisible(mode == "hex")
        self.case.setVisible(mode in ("text", "hex", "markdown"))
        self.file_buttons_visible = len(self.paths) > 1
        self._arrange_pill()
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
        if self.mode == "image":
            return
        self.find_strip.show()
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
            warning = f"This looks like a binary file; text may be unreadable. {s.encoding}, {human_size(s.size)}"
            if self.status.text() != warning:
                self.status.setText(warning)
        elif not self.busy and not pinned and not self.status.text().startswith(("Found", "Not found", "Search")):
            self.status.set_quiet(f"{s.encoding}, {human_size(s.size)}")
            self.position.setToolTip(self.status.text())

    def _hex_status(self) -> None:
        f = self.hexfile
        if f is None:
            self.position.setText("")
            return
        lo, n = self.hex.selection()
        self.position.setText(f"Offset 0x{lo:X} ({lo:,}) of {f.size:,}" + (f"   {n:,} bytes selected" if n > 1 else ""))
        if not self.status.text().startswith(("Found", "Not found", "Search", "Hex bytes")):
            numbers = "   ".join(f"{label} {text.split('  ')[0]}" for label, text in inspect(f.read(lo, 8))[:3])
            self.status.set_quiet(f"{human_size(f.size)}   {numbers}")
            self.position.setToolTip(self.status.text())

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._close_current()
        self._runner.shutdown(wait=False)
        super().closeEvent(event)
