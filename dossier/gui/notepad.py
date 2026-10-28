"""The F4 notepad: edit a text file in place, with find and replace (Ctrl+F, Ctrl+H) that can use regular
expressions, vertical (column) selection and editing, and a save that keeps the file's encoding, byte-order
mark and kind of line break (see core/textedit.py)."""
from __future__ import annotations

import os
from dataclasses import replace as dc_replace
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QPushButton, QSplitter, QVBoxLayout, QWidget)

from ..core import markdownsafe, viewmodes
from ..core.languages import HIGHLIGHT_LIMIT, LANGUAGES, label, language_for
from ..core.replace import FindSpec, PatternError, count, expand_at, find_next, replacements, validate
from ..core.textedit import (Document, EncodingProblem, FileChangedOnDisk, convert_eol, load_document, save_document)
from ..core.textview import ENCODINGS
from . import theme
from .editor import EditorView, from_line_index, line_starts
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


class NotepadWindow(QMainWindow):
    saved = pyqtSignal(str)
    closed = pyqtSignal(object)
    preview_toggled = pyqtSignal(bool)        # the owner switched the Markdown preview on or off (the window remembers it for Markdown files)
    syntax_toggled = pyqtSignal(bool)         # the owner switched syntax highlighting on or off (remembered for every notepad)

    def __init__(self, doc: Document, dialogs, parent=None, show_replace: bool = False, preview: Optional[bool] = None,
                 syntax: bool = False) -> None:
        """``preview``: whether the Markdown preview starts shown; None means it is shown for a Markdown file and not for any other.
        ``syntax``: whether syntax highlighting and folding start on (it is opt-in)."""
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialogs = dialogs
        self.doc = doc
        self._extra_dirty = False       # a change that is not in the text: the kind of line break
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
        f = bar.addMenu("&File")
        for a in (self._action("Save", "Ctrl+S", self.save), self._action("Save As...", "Ctrl+Shift+S", self.save_as),
                  self._action("Reload from Disk", None, self.reload), self._action("Close", "Ctrl+W", self.close)):
            f.addAction(a)
        e = bar.addMenu("&Edit")
        for text, keys, slot in (("Undo", None, self.editor.undo), ("Redo", None, self.editor.redo)):
            e.addAction(self._action(text, keys, slot))
        e.addSeparator()
        for text, keys, slot in (("Find...", "Ctrl+F", self.bar.show_find), ("Replace...", "Ctrl+H", self.bar.show_replace),
                                 ("Find Next", "F3", lambda: self.find(True)),
                                 ("Find Previous", "Shift+F3", lambda: self.find(False)),
                                 ("Go to Line...", "Ctrl+G", self.ask_goto)):
            e.addAction(self._action(text, keys, slot))
        v = bar.addMenu("&View")
        self.act_wrap = QAction("Word Wrap", self)
        self.act_wrap.setCheckable(True)
        self.act_wrap.toggled.connect(lambda on: self.editor.setWrapMode(
            self.editor.WrapMode.WrapWord if on else self.editor.WrapMode.WrapNone))
        v.addAction(self.act_wrap)
        self.act_space = QAction("Show Spaces and Tabs", self)
        self.act_space.setCheckable(True)
        self.act_space.toggled.connect(lambda on: self.editor.setWhitespaceVisibility(
            self.editor.WhitespaceVisibility.WsVisible if on else self.editor.WhitespaceVisibility.WsInvisible))
        v.addAction(self.act_space)
        self.act_preview = QAction("Markdown Preview", self)
        self.act_preview.setCheckable(True)
        self.act_preview.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.act_preview.setToolTip("Show the text as Markdown beside the source (raw HTML in it is shown as text, never run)")
        self.act_preview.toggled.connect(self._set_preview)
        self.addAction(self.act_preview)
        v.addAction(self.act_preview)
        v.addSeparator()
        self.act_syntax = QAction("Syntax Highlighting", self)
        self.act_syntax.setCheckable(True)
        self.act_syntax.setToolTip("Colour the text by the language of the file and let blocks fold. Off by default; big files are not coloured")
        self.act_syntax.toggled.connect(self._set_syntax)
        v.addAction(self.act_syntax)
        self._language_choice = "auto"
        self.lang_menu = v.addMenu("Language")
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
        self.act_fold = self._action("Fold All Blocks", None, lambda: self.editor.set_all_folds(True))
        self.act_unfold = self._action("Unfold All Blocks", None, lambda: self.editor.set_all_folds(False))
        v.addAction(self.act_fold)
        v.addAction(self.act_unfold)
        v.addSeparator()
        for text, keys, slot in (("Zoom In", "Ctrl+=", self.editor.zoomIn), ("Zoom Out", "Ctrl+-", self.editor.zoomOut),
                                 ("Actual Size", "Ctrl+0", lambda: self.editor.zoomTo(0))):
            v.addAction(self._action(text, keys, slot))
        self._action("Hide the find bar", "Esc", self._escape)

    def _build_status(self) -> None:
        self.message = QLabel()
        self.position = QLabel()
        self.encoding = QComboBox()
        self.encoding.setToolTip("Encoding of the file (changing it rereads the file)")
        names = ["utf-8", "utf-16-le", "utf-16-be"] + [e for e in ENCODINGS if e not in ("utf-8", "utf-16")]
        self.encoding.addItems(names)
        self.eol = QComboBox()
        self.eol.setToolTip("Kind of line break written when saving")
        for label, value in EOLS:
            self.eol.addItem(label, value)
        self.statusBar().addWidget(self.message, 1)
        for w in (self.position, self.encoding, self.eol):
            self.statusBar().addPermanentWidget(w)
        self.encoding.activated.connect(self._encoding_chosen)
        self.eol.activated.connect(self._eol_chosen)

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
                self.message.setText("No highlighting for this kind of file. View > Language picks one")
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

    # files ---------------------------------------------------------------------------------------------------------------
    def current_text(self) -> str:
        return self.editor.text()

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
