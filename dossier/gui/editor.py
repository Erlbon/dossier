"""The editing widget of the notepad: Scintilla (the engine of Notepad++), set up for plain text.

Vertical (column) selection and editing comes with it: Alt+drag with the mouse, Alt+Shift+arrows from
the keyboard, typing and pasting into every line of the block, and the block reaching past the end of
short lines. Never Ctrl+Alt (AltGr on Norwegian keyboards).
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.Qsci import QsciScintilla

from . import theme

S = QsciScintilla
NEWLINES = chr(13) + chr(10)      # built from code points: no backslash escapes to be mangled


def u16len(text: str) -> int:
    """Length in UTF-16 units, which is how Scintilla counts characters in a line."""
    return len(text.encode("utf-16-le")) // 2


def to_line_index(starts: list, text: str, offset: int) -> tuple:
    """Python character offset to Scintilla's (line, index). ``starts`` holds each line's first offset."""
    line = bisect_right(starts, offset) - 1
    return line, u16len(text[starts[line]:offset])


def line_starts(text: str) -> list:
    starts = [0]
    pos = text.find("\n")
    while pos >= 0:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts


def from_line_index(starts: list, text: str, line: int, index: int) -> int:
    """Scintilla's (line, index) to a Python character offset."""
    line = max(0, min(line, len(starts) - 1))
    base = starts[line]
    end = starts[line + 1] - 1 if line + 1 < len(starts) else len(text)
    units = 0
    for i in range(base, end):
        if units >= index:
            return i
        units += 2 if ord(text[i]) > 0xFFFF else 1
    return end


class EditorView(QsciScintilla):
    escape_pressed = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()          # the editor takes Esc itself, so the window's shortcut never sees it
        super().keyPressEvent(event)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setUtf8(True)
        self.setEolMode(S.EolMode.EolUnix)              # the text is kept with \n; the file's kind is restored on save
        self.setEolVisibility(False)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setMarginLineNumbers(0, True)
        self.setMarginsFont(self.font())
        self.setTabWidth(8)
        self.setIndentationsUseTabs(True)
        self.setAutoIndent(True)
        self.setCaretLineVisible(True)
        self.setWrapMode(S.WrapMode.WrapNone)
        self.setBraceMatching(S.BraceMatch.NoBraceMatch)
        self.linesChanged.connect(self._fit_margin)
        # Column editing -----------------------------------------------------------------------------------
        self.SendScintilla(S.SCI_SETRECTANGULARSELECTIONMODIFIER, S.SCMOD_ALT)       # Alt+drag makes a block
        self.SendScintilla(S.SCI_SETMULTIPLESELECTION, 1)
        self.SendScintilla(S.SCI_SETADDITIONALSELECTIONTYPING, 1)                    # type into every line of it
        self.SendScintilla(S.SCI_SETMULTIPASTE, S.SC_MULTIPASTE_EACH)                # paste into every line
        self.SendScintilla(S.SCI_SETVIRTUALSPACEOPTIONS, S.SCVS_RECTANGULARSELECTION)  # a block may pass short lines
        self.apply_theme()
        self._fit_margin()

    # look ------------------------------------------------------------------------------------------------------
    def apply_theme(self) -> None:
        t = theme.current()
        self.setPaper(QColor(t["bg"]))
        self.setColor(QColor(t["fg"]))
        self.setMarginsBackgroundColor(QColor(t["card"]))
        self.setMarginsForegroundColor(QColor(t["dim"]))
        self.setCaretForegroundColor(QColor(t["fg"]))
        self.setCaretLineBackgroundColor(QColor(t["cursor_bg"]))
        self.setSelectionBackgroundColor(QColor(t["accent"]))
        self.setSelectionForegroundColor(QColor(t["fg"]))
        self.SendScintilla(S.SCI_SETSELALPHA, 110)              # see-through, so the text stays readable
        self.SendScintilla(S.SCI_SETADDITIONALSELALPHA, 110)

    def _fit_margin(self) -> None:
        digits = max(3, len(str(max(1, self.lines()))))
        self.setMarginWidth(0, "9" * (digits + 1))

    # text ------------------------------------------------------------------------------------------------------
    def set_document_text(self, text: str) -> None:
        """Load text as the starting point: not modified, nothing to undo."""
        self.setText(text)
        self.SendScintilla(S.SCI_EMPTYUNDOBUFFER)
        self.setModified(False)
        self.setCursorPosition(0, 0)

    def offsets(self) -> tuple:
        """``(text, caret_offset, selection)`` in Python offsets; ``selection`` is ``(begin, end)`` or None."""
        text = self.text()
        starts = line_starts(text)
        line, index = self.getCursorPosition()
        caret = from_line_index(starts, text, line, index)
        sel = None
        if self.hasSelectedText():
            l1, i1, l2, i2 = self.getSelection()
            a = from_line_index(starts, text, l1, i1)
            b = from_line_index(starts, text, l2, i2)
            sel = (min(a, b), max(a, b))
        return text, caret, sel

    def select_offsets(self, begin: int, end: int, text: Optional[str] = None) -> None:
        text = self.text() if text is None else text
        starts = line_starts(text)
        l1, i1 = to_line_index(starts, text, begin)
        l2, i2 = to_line_index(starts, text, end)
        self.setSelection(l1, i1, l2, i2)
        self.ensureLineVisible(l1)

    def replace_changes(self, text: str, changes: list) -> None:
        """Apply ``(begin, end, new)`` changes (ascending, from the same ``text``) as ONE undo step."""
        starts = line_starts(text)
        self.beginUndoAction()
        try:
            for begin, end, new in reversed(changes):          # from the end, so earlier offsets stay valid
                l1, i1 = to_line_index(starts, text, begin)
                l2, i2 = to_line_index(starts, text, end)
                self.setSelection(l1, i1, l2, i2)
                self.replaceSelectedText(new)
        finally:
            self.endUndoAction()

    # blocks ------------------------------------------------------------------------------------------------------
    def is_block_selection(self) -> bool:
        return bool(self.SendScintilla(S.SCI_SELECTIONISRECTANGLE))

    def selection_count(self) -> int:
        return int(self.SendScintilla(S.SCI_GETSELECTIONS))

    def select_block(self, line1: int, col1: int, line2: int, col2: int) -> None:
        """A vertical selection from (line1, col1) to (line2, col2), columns counted in characters. A column past
        the end of a short line is kept as virtual space, so the block stays a straight rectangle."""
        def at(line: int, col: int) -> tuple:
            text = self.text(line).rstrip(NEWLINES)
            if col <= len(text):
                return self.positionFromLineIndex(line, u16len(text[:col])), 0
            return self.positionFromLineIndex(line, u16len(text)), col - len(text)

        (p1, v1), (p2, v2) = at(line1, col1), at(line2, col2)
        self.SendScintilla(S.SCI_SETRECTANGULARSELECTIONANCHOR, p1)
        self.SendScintilla(S.SCI_SETRECTANGULARSELECTIONANCHORVIRTUALSPACE, v1)
        self.SendScintilla(S.SCI_SETRECTANGULARSELECTIONCARET, p2)
        self.SendScintilla(S.SCI_SETRECTANGULARSELECTIONCARETVIRTUALSPACE, v2)
