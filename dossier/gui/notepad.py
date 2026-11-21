"""The F4 notepad: edit a text file in place, with find and replace (Ctrl+F, Ctrl+H) that can use regular
expressions, vertical (column) selection and editing, and a save that keeps the file's encoding, byte-order
mark and kind of line break (see core/textedit.py)."""
from __future__ import annotations

import os
import threading
from dataclasses import replace as dc_replace
from typing import Optional

from PyQt6.QtCore import QEvent, QFileSystemWatcher, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QMenu, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from ..core import markdownsafe, viewmodes
from ..core.languages import HIGHLIGHT_LIMIT, LANGUAGES, label, language_for
from ..core.platform import longpath
from ..core.replace import FindSpec, PatternError, count, expand_at, find_next, replacements, validate
from ..core.textedit import (Document, EncodingProblem, FileChangedOnDisk, convert_eol, load_document, save_document)
from ..core.textview import ENCODINGS
from . import theme
from .editor import EditorView, from_line_index, line_starts
from .floating_bar import FloatingBar, Toast
from .frost_window import FrostSurface
from .markdown_view import MarkdownView

EOLS = (("Windows (CRLF)", "\r\n"), ("Unix (LF)", "\n"), ("Classic Mac (CR)", "\r"))
COUNT_LIMIT_CHARS = 2_000_000       # beyond this the live match count is skipped: it would lag the typing
PREVIEW_DELAY = 300                 # ms of quiet in the typing before the Markdown preview is drawn again


class FindBar(QWidget):
    """Find and replace controls under the text. Ctrl+F shows the find row, Ctrl+H both rows."""

    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find")
        self.replace = QLineEdit()
        self.replace.setPlaceholderText("Replace with")
        self.regex = QCheckBox("Regular expression")
        self.case = QCheckBox("Match case")
        self.word = QCheckBox("Whole word")
        self.dotall = QCheckBox(". also matches line breaks")
        self.in_selection = QCheckBox("In selection")
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.replace_button = QPushButton("Replace")
        self.replace_all_button = QPushButton("Replace All")
        self.message = QLabel()
        self.message.setWordWrap(True)
        for b in (self.prev_button, self.next_button, self.replace_button, self.replace_all_button):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.find_row = QWidget()
        r1 = QHBoxLayout(self.find_row)
        r1.setContentsMargins(0, 0, 0, 0)
        r1.addWidget(QLabel("Find:"))
        r1.addWidget(self.find, 1)
        r1.addWidget(self.prev_button)
        r1.addWidget(self.next_button)
        self.replace_row = QWidget()
        r2 = QHBoxLayout(self.replace_row)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.addWidget(QLabel("Replace:"))
        r2.addWidget(self.replace, 1)
        r2.addWidget(self.replace_button)
        r2.addWidget(self.replace_all_button)
        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        for c in (self.regex, self.case, self.word, self.dotall, self.in_selection):
            options.addWidget(c)
        options.addStretch(1)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 6, 4)
        box.setSpacing(3)
        box.addWidget(self.find_row)
        box.addWidget(self.replace_row)
        box.addLayout(options)
        box.addWidget(self.message)
        self.setVisible(False)
        for w in (self.find, self.replace):
            w.textChanged.connect(lambda _t: self.changed.emit())
        for c in (self.regex, self.case, self.word, self.dotall):
            c.toggled.connect(lambda _b: self.changed.emit())
        self.regex.toggled.connect(self.dotall.setEnabled)
        self.dotall.setEnabled(False)

    def spec(self) -> FindSpec:
        return FindSpec(self.find.text(), regex=self.regex.isChecked(), case=self.case.isChecked(),
                        whole_word=self.word.isChecked(), dot_all=self.dotall.isChecked())

    def show_find(self) -> None:
        self.replace_row.setVisible(False)
        self.setVisible(True)
        self.find.setFocus()
        self.find.selectAll()

    def show_replace(self) -> None:
        self.replace_row.setVisible(True)
        self.setVisible(True)
        self.find.setFocus()
        self.find.selectAll()

    def say(self, text: str, problem: bool = False) -> None:
        t = theme.current()
        self.message.setStyleSheet(f"color:{t['danger'] if problem else t['dim']};")
        self.message.setText(text)


class NotepadWindow(FrostSurface, QMainWindow):
    saved = pyqtSignal(str)
    closed = pyqtSignal(object)
    preview_toggled = pyqtSignal(bool)        # the owner switched the Markdown preview on or off (the window remembers it for Markdown files)
    syntax_toggled = pyqtSignal(bool)         # the owner switched syntax highlighting on or off (remembered for every notepad)
    _disk_seen = pyqtSignal(str, object)      # (path, (size, mtime_ns) or None): what a thread saw on disk, handed to the window's thread

    def __init__(self, doc: Document, dialogs, parent=None, show_replace: bool = False, preview: Optional[bool] = None,
                 syntax: bool = False) -> None:
        """``preview``: whether the Markdown preview starts shown; None means it is shown for a Markdown file and not for any other.
        ``syntax``: whether syntax highlighting and folding start on (it is opt-in)."""
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialogs = dialogs
        self.doc = doc
        self._extra_dirty = False       # a change that is not in the text: the kind of line break
        self._host = None               # the NotepadTabs window this is a tab of, if any
        self._checking = False
        self._asking = False
        self.resize(900, 640)
        self.editor = EditorView()
        self.preview = MarkdownView()
        self.preview.setVisible(False)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.editor)
        self.split.addWidget(self.preview)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)
        self.bar = FindBar()
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.split, 1)
        lay.addWidget(self.bar)
        self.setCentralWidget(central)
        self._build_menus()
        self._build_floating_bar()
        self._build_status()
        self.editor.set_document_text(doc.text)
        self.editor.modificationChanged.connect(lambda _m: self._update_title())
        self.editor.cursorPositionChanged.connect(lambda *_a: self._update_position())
        self.editor.selectionChanged.connect(self._update_position)
        self.editor.escape_pressed.connect(self._escape)
        self.editor.textChanged.connect(self._render_soon)
        self.editor.verticalScrollBar().valueChanged.connect(self._sync_preview)
        self.preview.open_file_requested.connect(lambda path: self.message.setText(f"A link to a file: {path}"))
        self.preview.refused.connect(lambda text: self.message.setText(f"This link is not opened: {text}"))
        self.bar.next_button.clicked.connect(lambda: self.find(True))
        self.bar.prev_button.clicked.connect(lambda: self.find(False))
        self.bar.replace_button.clicked.connect(self.replace_one)
        self.bar.replace_all_button.clicked.connect(self.replace_all)
        self.bar.find.returnPressed.connect(lambda: self.find(True))
        self.bar.changed.connect(self._validate_soon)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._validate)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(PREVIEW_DELAY)
        self._render_timer.timeout.connect(self._render)
        self._update_title()
        self._update_status_fields()
        self._update_position()
        self._disk_seen.connect(self._on_disk_seen)
        self._disk_timer = QTimer(self)
        self._disk_timer.setSingleShot(True)
        self._disk_timer.setInterval(300)
        self._disk_timer.timeout.connect(self.check_disk)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _p: self._disk_timer.start())
        self._rewatch()
        if show_replace:
            self.bar.show_replace()
        self.act_preview.setChecked(preview if preview is not None else self.is_markdown())
        self.act_syntax.setChecked(bool(syntax))
        self._apply_syntax()                                      # (a switch that stays off sends no signal)

    # setup -----------------------------------------------------------------------------------------------------
    def _action(self, text: str, keys, slot) -> QAction:
        act = QAction(text, self)
        if keys:
            act.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
        act.triggered.connect(lambda _c=False: slot())
        self.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        f = self.file_menu = bar.addMenu("&File")
        for a in (self._action("Save", "Ctrl+S", self.save), self._action("Save As...", "Ctrl+Shift+S", self.save_as),
                  self._action("Reload from Disk", None, self.reload), self._action("Close", "Ctrl+W", self.close)):
            f.addAction(a)
        e = self.edit_menu = bar.addMenu("&Edit")
        for text, keys, slot in (("Undo", None, self.editor.undo), ("Redo", None, self.editor.redo), (None, None, None),
                                 ("Cut", None, self.editor.cut), ("Copy", None, self.editor.copy), ("Paste", None, self.editor.paste),
                                 ("Select All", None, self.editor.selectAll), (None, None, None),
                                 ("Find...", "Ctrl+F", self.bar.show_find), ("Replace...", "Ctrl+H", self.bar.show_replace),
                                 ("Find Next", "F3", lambda: self.find(True)),
                                 ("Find Previous", "Shift+F3", lambda: self.find(False)),
                                 ("Go to Line...", "Ctrl+G", self.ask_goto)):
            if text is None:
                e.addSeparator()
            else:
                e.addAction(self._action(text, keys, slot))
        v = self.view_menu = bar.addMenu("&View")
        self.act_preview = QAction("Markdown Preview", self)
        self.act_preview.setCheckable(True)
        self.act_preview.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.act_preview.setToolTip("Show the text as Markdown beside the source (raw HTML in it is shown as text, never run)")
        self.act_preview.toggled.connect(self._set_preview)
        self.addAction(self.act_preview)
        v.addAction(self.act_preview)
        v.addSeparator()
        self.act_fold = self._action("Fold All Blocks", None, lambda: self.editor.set_all_folds(True))
        self.act_unfold = self._action("Unfold All Blocks", None, lambda: self.editor.set_all_folds(False))
        v.addAction(self.act_fold)
        v.addAction(self.act_unfold)
        v.addSeparator()
        for text, keys, slot in (("Zoom In", "Ctrl+=", self.editor.zoomIn), ("Zoom Out", "Ctrl+-", self.editor.zoomOut),
                                 ("Actual Size", "Ctrl+0", lambda: self.editor.zoomTo(0))):
            v.addAction(self._action(text, keys, slot))
        self._build_settings_menu()
        self._action("Hide the find bar", "Esc", self._escape)

    def _build_settings_menu(self) -> None:
        """What stays set while you work: wrap, spaces, colouring and language, encoding, line break. Not on the menu bar: the gear button."""
        m = self.settings_menu = QMenu(self)
        self.act_wrap = QAction("Word Wrap", self)
        self.act_wrap.setCheckable(True)
        self.act_wrap.toggled.connect(lambda on: self.editor.setWrapMode(
            self.editor.WrapMode.WrapWord if on else self.editor.WrapMode.WrapNone))
        m.addAction(self.act_wrap)
        self.act_space = QAction("Show Spaces and Tabs", self)
        self.act_space.setCheckable(True)
        self.act_space.toggled.connect(lambda on: self.editor.setWhitespaceVisibility(
            self.editor.WhitespaceVisibility.WsVisible if on else self.editor.WhitespaceVisibility.WsInvisible))
        m.addAction(self.act_space)
        m.addSeparator()
        self.act_syntax = QAction("Colour the Text (Syntax Highlighting)", self)
        self.act_syntax.setCheckable(True)
        self.act_syntax.setToolTip("Colour the text by the language of the file and let blocks fold. Off by default; big files are not coloured")
        self.act_syntax.toggled.connect(self._set_syntax)
        m.addAction(self.act_syntax)
        self._language_choice = "auto"
        self.lang_menu = m.addMenu("Language")
        group = QActionGroup(self)
        self.lang_actions: dict = {}
        for choice, text in (("auto", "Automatic (by the file name)"), ("none", "Plain Text")) + tuple(
                (key, label(key)) for key in LANGUAGES):
            act = self.lang_menu.addAction(text)
            act.setCheckable(True)
            act.setActionGroup(group)
            act.triggered.connect(lambda _c=False, c=choice: self._choose_language(c))
            self.lang_actions[choice] = act
            if choice == "none":
                self.lang_menu.addSeparator()
        self.lang_actions["auto"].setChecked(True)
        m.addSeparator()
        self.encoding_menu = m.addMenu("Encoding")
        self.eol_menu = m.addMenu("Line Break")
        self.encoding_menu.aboutToShow.connect(lambda: self._fill_choice_menu(self.encoding_menu, self.encoding, self._encoding_chosen))
        self.eol_menu.aboutToShow.connect(lambda: self._fill_choice_menu(self.eol_menu, self.eol, self._eol_chosen))

    @staticmethod
    def _fill_choice_menu(menu, combo, chosen) -> None:
        """A submenu with the entries of ``combo`` and the current one ticked; choosing one sets the combo and calls ``chosen``."""
        menu.clear()
        group = QActionGroup(menu)
        for i in range(combo.count()):
            act = menu.addAction(combo.itemText(i))
            act.setCheckable(True)
            act.setActionGroup(group)
            act.setChecked(i == combo.currentIndex())
            act.triggered.connect(lambda _c=False, i=i: (combo.setCurrentIndex(i), chosen(i)))

    def _build_floating_bar(self) -> None:
        """The same floating bar as the picture viewer, over the text: it fades in when the mouse moves and out when it rests. It is the
        window's only bar: menus, the few tools, the cursor position and the settings all live in it."""
        self.floating = FloatingBar(self.editor.viewport(), self.editor, lambda _d: None, self.close,
                                    specs=(("close", "✕", "Close (Ctrl+W)", self.close),))
        bar = self.floating
        for key, text, icon, menu in (("file", "File", "file", self.file_menu), ("edit", "Edit", "pencil", self.edit_menu),
                                      ("view", "View", "eye", self.view_menu)):
            bar.add_button(key, text, f"The {text} menu", lambda m=menu, k=key: self._popup_menu(m, k), icon=icon)
        bar.add_separator()
        bar.add_button("save", "Save", "Save (Ctrl+S)", self.save, icon="device-floppy")
        bar.add_button("find", "Find", "Find and replace (Ctrl+F, Ctrl+H)", self.bar.show_find, icon="search")
        bar.add_button("goto", "Go to", "Go to line (Ctrl+G)", self.ask_goto, icon="hash")
        bar.add_separator()
        self.position = bar.add_label()
        bar.add_button("settings", "Settings", "Word wrap, colouring, language, encoding and line break",
                       lambda: self._popup_menu(self.settings_menu, "settings"), icon="settings")
        bar.set_enabled(True)
        self.editor.bottom_room = lambda: bar.room_below(self.editor.viewport().height())   # the last lines scroll clear of the bar
        self.editor.refresh_tail(force=True)
        self.menuBar().hide()                      # the menus live in the floating bar: one bar, not a menu bar as well (the actions keep their keys)

    def _popup_menu(self, menu, key: str) -> None:
        """A menu of the bar, in the bar's look, opened upwards from its button."""
        self.floating.popup_menu(menu, key)

    def _build_status(self) -> None:
        """No status line: messages float over the text for a few seconds, the position is in the bar, encoding and line break are in
        Settings (the two combo boxes only hold the choice and are never shown)."""
        self.message = Toast(self.editor.viewport())
        self.encoding = QComboBox()
        self.encoding.setToolTip("Encoding of the file (changing it rereads the file)")
        names = ["utf-8", "utf-16-le", "utf-16-be"] + [e for e in ENCODINGS if e not in ("utf-8", "utf-16")]
        self.encoding.addItems(names)
        self.eol = QComboBox()
        self.eol.setToolTip("Kind of line break written when saving")
        for label, value in EOLS:
            self.eol.addItem(label, value)
        self.encoding.activated.connect(self._encoding_chosen)
        self.eol.activated.connect(self._eol_chosen)
        self.statusBar().hide()

    def _update_status_fields(self) -> None:
        blocked = self.encoding.blockSignals(True)
        i = self.encoding.findText(self.doc.encoding)
        if i < 0:
            self.encoding.addItem(self.doc.encoding)
            i = self.encoding.findText(self.doc.encoding)
        self.encoding.setCurrentIndex(i)
        self.encoding.blockSignals(blocked)
        blocked = self.eol.blockSignals(True)
        self.eol.setCurrentIndex(max(0, self.eol.findData(self.doc.eol)))
        self.eol.blockSignals(blocked)
        if self.doc.mixed_eol:
            self.message.setText("The line breaks were mixed; they will be written as "
                                 + self.eol.currentText() + ".")

    # syntax highlighting and folding --------------------------------------------------------------------------------
    def _set_syntax(self, on: bool) -> None:
        self._apply_syntax()
        self.syntax_toggled.emit(on)

    def _choose_language(self, choice: str) -> None:
        self._language_choice = choice
        self._apply_syntax()

    def _apply_syntax(self) -> None:
        """Colour and fold the text if highlighting is on, in the language chosen (or the file name's), unless the text is too big."""
        key = None
        if self.act_syntax.isChecked() and self._language_choice != "none":
            key = language_for(self.doc.path) if self._language_choice == "auto" else self._language_choice
            if key is None:
                self.message.setText("No highlighting for this kind of file. View > Settings > Language picks one")
            elif self.editor.length() > HIGHLIGHT_LIMIT:
                self.message.setText("This text is too big to colour (the limit is 1 MB)")
                key = None
        shown = self.editor.set_language(key)
        has = self.editor.language is not None
        self.act_fold.setEnabled(has)
        self.act_unfold.setEnabled(has)
        if key is not None and not shown:
            self.message.setText(f"This Scintilla has no highlighting for {label(key)}")

    # the Markdown preview ------------------------------------------------------------------------------------------
    def is_markdown(self) -> bool:
        return self.doc.path.lower().endswith(viewmodes.MARKDOWN_EXTENSIONS)

    def _set_preview(self, on: bool) -> None:
        self.preview.setVisible(on)
        if on:
            self.split.setSizes([1, 1])
            self._render()
        self.preview_toggled.emit(on)

    def _render_soon(self) -> None:
        if self.preview.isVisibleTo(self):
            self._render_timer.start()

    def _render(self) -> None:
        """Draw the preview from the text as it is now (not the file on disk), in the safe subset of Markdown: nothing in it runs."""
        if not self.preview.isVisibleTo(self):
            return
        text = self.editor.text()
        if markdownsafe.too_big(len(text.encode("utf-8"))):
            self.preview.show_notice("This text is too big to show as Markdown (the limit is 256 KB). The source is still editable.")
            return
        self.preview.set_markdown(text, os.path.dirname(self.doc.path), keep_position=True)

    def _sync_preview(self, *_a) -> None:
        """The preview follows the source: the same fraction of the page is in view."""
        if not self.preview.isVisibleTo(self):
            return
        mine, theirs = self.editor.verticalScrollBar(), self.preview.verticalScrollBar()
        if mine.maximum() > 0:
            theirs.setValue(int(theirs.maximum() * mine.value() / mine.maximum()))

    # title, status ------------------------------------------------------------------------------------------------
    def is_modified(self) -> bool:
        return self.editor.isModified() or self._extra_dirty

    def mark_clean(self) -> None:
        self._extra_dirty = False
        self.editor.setModified(False)
        self._update_title()

    def _update_title(self) -> None:
        self.setWindowTitle(f"Dossier, Subject - {os.path.basename(self.doc.path)}"
                            + ("*" if self.is_modified() else ""))

    def _update_position(self, *_a) -> None:
        line, index = self.editor.getCursorPosition()
        text = f"Ln {line + 1}, Col {index + 1}"
        if self.editor.hasSelectedText():
            if self.editor.is_block_selection() and self.editor.selection_count() > 1:
                text += f"   Block of {self.editor.selection_count()} lines"
            else:
                text += f"   {len(self.editor.selectedText()):,} selected"
        self.position.setText(text)

    # find and replace ----------------------------------------------------------------------------------------------
    def _validate_soon(self) -> None:
        self._timer.start()

    def _validate(self) -> bool:
        spec = self.bar.spec()
        if not spec.pattern:
            self.bar.say("")
            return False
        try:
            validate(spec, self.bar.replace.text())
        except PatternError as e:
            self.bar.say(str(e), problem=True)
            return False
        text = self.editor.text()
        if len(text) <= COUNT_LIMIT_CHARS:
            n = count(text, spec)
            self.bar.say(f"{n:,} match{'es' if n != 1 else ''}")
        else:
            self.bar.say("")
        return True

    def _checked_spec(self) -> Optional[FindSpec]:
        spec = self.bar.spec()
        try:
            validate(spec, self.bar.replace.text())
        except PatternError as e:
            self.bar.say(str(e), problem=True)
            return None
        return spec

    def find(self, forward: bool = True) -> bool:
        spec = self._checked_spec()
        if spec is None:
            return False
        if not self.bar.isVisible():
            self.bar.show_find()
        text, caret, sel = self.editor.offsets()
        start = (sel[1] if sel else caret) if forward else (sel[0] if sel else caret)
        hit = find_next(text, spec, start, forward=forward, wrap=True)
        if hit is None:
            self.bar.say("No match", problem=True)
            return False
        wrapped = hit[0] < start if forward else hit[0] >= start
        self.editor.select_offsets(hit[0], hit[1], text)
        self.bar.say("Wrapped around" if wrapped else "")
        return True

    def replace_one(self) -> None:
        spec = self._checked_spec()
        if spec is None:
            return
        text, caret, sel = self.editor.offsets()
        if sel:
            new = expand_at(text, spec, self.bar.replace.text(), sel[0], sel[1])
            if new is not None:                    # the selection IS a match: replace it, then move on
                self.editor.replaceSelectedText(new)
        self.find(True)

    def replace_all(self) -> int:
        spec = self._checked_spec()
        if spec is None:
            return 0
        text, caret, sel = self.editor.offsets()
        region = sel if (self.bar.in_selection.isChecked() and sel) else None
        try:
            changes = replacements(text, spec, self.bar.replace.text(), region=region)
        except PatternError as e:
            self.bar.say(str(e), problem=True)
            return 0
        if not changes:
            self.bar.say("No match", problem=True)
            return 0
        self.editor.replace_changes(text, changes)          # one undo step
        self.bar.say(f"Replaced {len(changes):,} (Ctrl+Z undoes all of them)")
        return len(changes)

    def ask_goto(self) -> None:
        n, ok = QInputDialog.getInt(self, "Go to Line", "Line number:", self.editor.getCursorPosition()[0] + 1, 1,
                                    max(1, self.editor.lines()))
        if ok:
            self.goto_line(n)

    def goto_line(self, n: int) -> None:
        self.editor.setCursorPosition(max(0, n - 1), 0)
        self.editor.ensureLineVisible(max(0, n - 1))

    def _escape(self) -> None:
        if self.bar.isVisible():
            self.bar.setVisible(False)
            self.editor.setFocus()

    # the file changed under the editor (card 70) -----------------------------------------------------------------------
    def _rewatch(self) -> None:
        """Watch the file again (a save that replaces the file drops the watch). A file not made yet has nothing to watch."""
        old = self._watcher.files()
        if old:
            self._watcher.removePaths(old)
        if self.doc.mtime_ns:
            self._watcher.addPath(self.doc.path)

    def check_disk(self) -> None:
        """Ask a thread what the file looks like on disk now; ``_on_disk_seen`` gets the answer. Called when the file's watcher fires, when
        the window comes to the front and when its tab is chosen."""
        if self._checking or not self.doc.mtime_ns:
            return
        self._checking = True
        path = self.doc.path

        def work() -> None:
            try:
                st = os.stat(longpath(path))
                seen = (st.st_size, st.st_mtime_ns)
            except OSError:
                seen = None
            try:
                self._disk_seen.emit(path, seen)
            except RuntimeError:                       # the window is gone
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_disk_seen(self, path: str, seen) -> None:
        self._checking = False
        if seen is None or path != self.doc.path or self._asking:
            return
        if tuple(seen) == (self.doc.size, self.doc.mtime_ns):
            return
        if self._host is not None and self._host.current_page() is not self:
            return                                     # a tab out of sight: asked when it is chosen
        self._asking = True
        try:
            choice = self.dialogs.ask_file_changed(os.path.basename(self.doc.path), self.is_modified())
        finally:
            self._asking = False
        if choice == "reload":
            self.reload(ask=False)
        else:                                          # keep mine: the disk version is known now, a save writes straight over it
            self.doc = dc_replace(self.doc, size=seen[0], mtime_ns=seen[1])

    def bring_forward(self) -> None:
        if self._host is not None:
            self._host.show_page(self)
        else:
            self.raise_()
            self.activateWindow()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowActivate and self.isWindow():
            self.check_disk()
        return super().event(e)

    # files ---------------------------------------------------------------------------------------------------------------
    def save(self, force: bool = False) -> bool:
        """Write the file. Returns True when it was saved."""
        text = self.editor.text()
        try:
            new = save_document(self.doc, text, force=force)
        except FileChangedOnDisk:
            choice = self.dialogs.ask_changed_on_disk(os.path.basename(self.doc.path))
            if choice == "overwrite":
                return self.save(force=True)
            if choice == "reload":
                self.reload(ask=False)          # the user chose the disk version; nothing was saved
            return False
        except EncodingProblem as e:
            if self.doc.encoding != "utf-8" and self.dialogs.confirm(
                    "Cannot save in this encoding", f"{e}\n\nSave the file as UTF-8 instead?", "Save as UTF-8"):
                self.doc = dc_replace(self.doc, encoding="utf-8", bom=b"")
                self._update_status_fields()
                return self.save(force=force)
            return False
        except OSError as e:
            self.dialogs.info("Save", f"The file could not be saved: {e.strerror or e}")
            return False
        self.doc = new
        self._rewatch()
        self.mark_clean()
        self.message.setText("Saved")
        self.saved.emit(self.doc.path)
        return True

    def save_as(self) -> bool:
        path = self.dialogs.ask_save_path(self.doc.path)
        if not path:
            return False
        old = self.doc
        self.doc = dc_replace(old, path=path, size=0, mtime_ns=0)
        ok = self.save(force=True)
        if not ok:
            self.doc = old
        self._update_title()
        self._rewatch()
        self._apply_syntax()                                     # the new name may be another language
        return ok

    def reload(self, ask: bool = True, encoding: str = "auto") -> bool:
        if ask and self.is_modified() and not self.dialogs.confirm(
                "Reload", "Throw away your changes and read the file again?", "Reload"):
            return False
        try:
            doc = load_document(self.doc.path, encoding)
        except Exception as e:
            self.dialogs.info("Reload", str(e))
            self._update_status_fields()
            return False
        self.doc = doc
        self._rewatch()
        self.editor.set_document_text(doc.text)
        self._extra_dirty = False
        self._update_status_fields()
        self._update_title()
        return True

    def _encoding_chosen(self, _i: int) -> None:
        wanted = self.encoding.currentText()
        if wanted != self.doc.encoding and not self.reload(encoding=wanted):
            self._update_status_fields()

    def _eol_chosen(self, _i: int) -> None:
        eol = self.eol.currentData()
        if eol != self.doc.eol:
            self.doc = convert_eol(self.doc, eol)
            self._extra_dirty = True
            self._update_title()
            self.message.setText("Line breaks will be written as " + self.eol.currentText())

    def closeEvent(self, event) -> None:
        if self.is_modified():
            answer = self.dialogs.ask_save(os.path.basename(self.doc.path))
            if answer == "cancel" or (answer == "save" and not self.save()):
                event.ignore()
                return
        self.closed.emit(self)
        super().closeEvent(event)


def new_page(doc: Document, dialogs, settings, show_replace: bool = False) -> NotepadWindow:
    """A notepad for ``doc`` with the remembered choices (Markdown preview, syntax colouring) from ``settings``, ready to be a window of its
    own or a tab of ``NotepadTabs``."""
    remembered = str(settings.value("editor/markdown_preview", "")).lower()
    win = NotepadWindow(doc, dialogs, show_replace=show_replace, preview={"true": True, "false": False}.get(remembered),
                        syntax=str(settings.value("editor/syntax", "false")).lower() == "true")
    win.syntax_toggled.connect(lambda on: settings.setValue("editor/syntax", "true" if on else "false"))
    win.preview_toggled.connect(lambda on, w=win: settings.setValue("editor/markdown_preview", "true" if on else "false")
                                if w.is_markdown() else None)
    return win


class NotepadTabs(FrostSurface, QMainWindow):
    """One window with a notepad in each tab (card 70): F4 on several marked files, and the notepad Explorer starts. Each tab is a whole
    ``NotepadWindow`` (its own text, unsaved state, find bar, syntax and preview) shown as a widget. Closing a tab asks as closing a
    window does; closing the last tab, or the window, ends it. Ctrl+W closes the tab, Ctrl+Tab and Ctrl+Shift+Tab switch."""

    closed = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 640)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # the panels' own tabs: rounded tops, the current one gold, the others blue, a small cross of our own (the owner, 2026-11-19)
        from .panel import PanelTabBar
        bar = PanelTabBar()
        bar.panel_active = True
        bar.setAcceptDrops(False)
        bar.middle_clicked.connect(lambda i: self.tabs.widget(i).close())
        self.tabs.setTabBar(bar)
        self._close_buttons: dict = {}
        self.tabs.setMovable(True)
        self.tabs.setTabBarAutoHide(True)
        self.setCentralWidget(self.tabs)
        self._closing = False
        self.session = None                                  # whatever must live as long as the window (the single-instance server)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._style_tab_row()
        for text, keys, step in (("Next Tab", "Ctrl+Tab", 1), ("Previous Tab", "Ctrl+Shift+Tab", -1)):
            act = QAction(text, self)
            act.setShortcut(QKeySequence(keys))
            act.triggered.connect(lambda _c=False, d=step: self.step_tab(d))
            self.addAction(act)

    # the pages -------------------------------------------------------------------------------------------------------
    def pages(self) -> list:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_page(self):
        return self.tabs.currentWidget()

    def mark_clean(self) -> None:
        for page in self.pages():
            page.mark_clean()

    def page_for(self, path: str):
        key = os.path.normcase(path)
        return next((p for p in self.pages() if os.path.normcase(p.doc.path) == key), None)

    def add_page(self, page: NotepadWindow) -> None:
        page.setWindowFlags(Qt.WindowType.Widget)
        page._host = self
        i = self.tabs.addTab(page, "")
        self._attach_close_button(page)
        self._retitle(page)
        page.windowTitleChanged.connect(lambda _t, p=page: self._retitle(p))
        page.closed.connect(self._page_closed)
        self.tabs.setCurrentIndex(i)
        page.show()

    def show_page(self, page) -> None:
        self.tabs.setCurrentWidget(page)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def step_tab(self, direction: int) -> None:
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + direction) % n)

    def _retitle(self, page) -> None:
        i = self.tabs.indexOf(page)
        if i < 0:
            return
        name = os.path.basename(page.doc.path) + ("*" if page.is_modified() else "")
        self.tabs.setTabText(i, name.replace("&", "&&"))
        self.tabs.setTabToolTip(i, page.doc.path)
        if page is self.current_page():
            self.setWindowTitle(page.windowTitle())

    def _style_tab_row(self) -> None:
        """The row behind the tabs in the card colour, and the crosses small and quiet until the pointer is on them, as in the panels."""
        t = theme.current()
        self.tabs.tabBar().setStyleSheet(
            f"QTabBar{{background:{t['card']};}}"
            f"QTabBar QToolButton{{padding:1px;border:none;border-radius:3px;background:transparent;}}"
            f"QTabBar QToolButton:hover{{background:{t['line']};}}")
        self._style_close_buttons()

    def _attach_close_button(self, page) -> None:
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QTabBar, QToolButton
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setIconSize(QSize(12, 12))
        btn.setToolTip("Close tab (Ctrl+W)")
        btn.clicked.connect(lambda _c=False, p=page: p.close())
        self.tabs.tabBar().setTabButton(self.tabs.indexOf(page), QTabBar.ButtonPosition.RightSide, btn)
        self._close_buttons[id(page)] = (page, btn)
        page.destroyed.connect(lambda _o=None, k=id(page): self._close_buttons.pop(k, None))
        self._style_close_buttons()

    def _style_close_buttons(self) -> None:
        """A cross in the text colour of its tab: dark on the gold current tab, light on the blue ones."""
        from . import icon_set
        c = theme.tab_colors()
        current = self.current_page()
        for key, (page, btn) in list(self._close_buttons.items()):
            try:
                btn.setIcon(icon_set.icon("x", c["active_text"] if page is current else c["blue_text"]))
            except RuntimeError:                      # the button went away with its tab
                self._close_buttons.pop(key, None)

    def _tab_changed(self, _i: int) -> None:
        self._style_close_buttons()
        page = self.current_page()
        if page is not None:
            self.setWindowTitle(page.windowTitle())
            page.check_disk()

    def _page_closed(self, page) -> None:
        i = self.tabs.indexOf(page)
        if i >= 0:
            self.tabs.removeTab(i)
        if self.tabs.count() == 0 and not self._closing:
            self.close()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowActivate and self.current_page() is not None:
            self.current_page().check_disk()
        return super().event(e)

    def closeEvent(self, event) -> None:
        self._closing = True
        for page in self.pages():
            if not page.close():                              # the owner cancelled the save question: stay open
                self._closing = False
                event.ignore()
                return
        self.closed.emit(self)
        super().closeEvent(event)
