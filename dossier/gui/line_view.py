"""A read-only view of the lines of a TextSource: only the visible lines are decoded and painted, so
a file of any size scrolls at once. Has line numbers, normal selection and vertical (column,
rectangular) selection, and copy.

Vertical selection: Alt+drag with the mouse, or Alt+Shift+arrows. Never Ctrl+Alt (AltGr on Norwegian
keyboards)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QGuiApplication, QKeyEvent, QKeySequence, QPainter
from PyQt6.QtWidgets import QAbstractScrollArea

from ..core.textview import TextSource
from . import theme

TAB = 8
COPY_LIMIT = 10_000_000       # characters; a bigger selection is cut and the user is told


def vcol_of(text: str, col: int) -> int:
    """Visual column of character index ``col`` (tabs expand to the next multiple of TAB)."""
    return len(text[:col].expandtabs(TAB))


def col_of_vcol(text: str, vcol: int) -> int:
    """The character index under visual column ``vcol`` (past the end gives ``len(text)``)."""
    if "\t" not in text:
        return min(vcol, len(text))
    v = 0
    for i, ch in enumerate(text):
        width = TAB - (v % TAB) if ch == "\t" else 1
        if vcol < v + width:
            return i
        v += width
    return len(text)


class LineView(QAbstractScrollArea):
    changed = pyqtSignal()           # position, selection or contents changed (for status text)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.source: Optional[TextSource] = None
        self.top = 0
        self.anchor: Optional[tuple] = None      # (line, col)
        self.head: Optional[tuple] = None
        self.block = False
        self.match: Optional[tuple] = None       # (line, col, length)
        self._max_vcols = 0
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # geometry ------------------------------------------------------------------------------
    @property
    def cw(self) -> int:
        return max(1, self.fontMetrics().horizontalAdvance("M"))

    @property
    def lh(self) -> int:
        return self.fontMetrics().height() + 2

    @property
    def visible_lines(self) -> int:
        return max(1, self.viewport().height() // self.lh)

    @property
    def total(self) -> int:
        return self.source.line_count if self.source else 0

    def gutter(self) -> int:
        digits = max(3, len(str(max(self.total, 1))))
        return digits * self.cw + 14

    # contents ------------------------------------------------------------------------------
    def set_source(self, source: Optional[TextSource]) -> None:
        self.source = source
        self.top = 0
        self.anchor = self.head = self.match = None
        self._max_vcols = 0
        self.refresh_counts()
        self.verticalScrollBar().setValue(0)

    def refresh_counts(self) -> None:
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, self.total - self.visible_lines))
        bar.setPageStep(self.visible_lines)
        bar.setSingleStep(1)
        self.viewport().update()
        self.changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_counts()

    def _scrolled(self, value: int) -> None:
        self.top = value
        self.viewport().update()
        self.changed.emit()

    def goto_line(self, n: int, center: bool = True) -> None:
        n = max(0, min(n, max(0, self.total - 1)))
        target = n - self.visible_lines // 2 if center else n
        self.verticalScrollBar().setValue(max(0, target))

    def scroll_to_end(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def at_end(self) -> bool:
        return self.verticalScrollBar().value() >= self.verticalScrollBar().maximum()

    def show_match(self, line: int, col: int, length: int) -> None:
        self.match = (line, col, length)
        if not (self.top <= line < self.top + self.visible_lines):
            self.goto_line(line)
        text = self.source.line(line) if self.source else ""
        x0 = vcol_of(text, col) * self.cw
        view_w = self.viewport().width() - self.gutter()
        h = self.horizontalScrollBar()
        if x0 < h.value() or x0 + length * self.cw > h.value() + view_w:
            h.setValue(max(0, x0 - view_w // 3))
        self.viewport().update()
        self.changed.emit()

    def clear_match(self) -> None:
        self.match = None
        self.viewport().update()

    # selection -------------------------------------------------------------------------------
    def has_selection(self) -> bool:
        return self.anchor is not None and self.head is not None and self.anchor != self.head

    def clear_selection(self) -> None:
        self.anchor = self.head = None
        self.viewport().update()
        self.changed.emit()

    def _ordered(self) -> tuple:
        a, h = self.anchor, self.head
        return (a, h) if a <= h else (h, a)

    def line_range(self, n: int) -> Optional[tuple]:
        """The selected character range ``(start, end)`` on line ``n``, or None."""
        if not self.has_selection() or self.source is None:
            return None
        text = self.source.line(n)
        if self.block:
            l0, l1 = sorted((self.anchor[0], self.head[0]))
            if not l0 <= n <= l1:
                return None
            va = vcol_of(self.source.line(self.anchor[0]), self.anchor[1])
            vh = vcol_of(self.source.line(self.head[0]), self.head[1])
            v0, v1 = sorted((va, vh))
            c0, c1 = col_of_vcol(text, v0), col_of_vcol(text, v1)
            return (c0, c1)
        (l0, c0), (l1, c1) = self._ordered()
        if not l0 <= n <= l1:
            return None
        start = c0 if n == l0 else 0
        end = c1 if n == l1 else len(text) + 1       # the +1 paints the line break
        return (start, end)

    def selected_text(self) -> str:
        if not self.has_selection() or self.source is None:
            return ""
        (l0, _), (l1, _) = self._ordered()
        parts, size = [], 0
        for n in range(l0, l1 + 1):
            rng = self.line_range(n)
            text = self.source.line(n)
            piece = text[rng[0]:rng[1]] if rng else ""
            parts.append(piece)
            size += len(piece) + 1
            if size > COPY_LIMIT:
                break
        return "\n".join(parts)

    def copy(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    # mouse -----------------------------------------------------------------------------------
    def _pos_to_cell(self, pos: QPoint) -> tuple:
        line = min(max(self.top + pos.y() // self.lh, 0), max(0, self.total - 1))
        text = self.source.line(line) if self.source else ""
        vcol = max(0, (pos.x() - self.gutter() + self.horizontalScrollBar().value() + self.cw // 2) // self.cw)
        return line, col_of_vcol(text, vcol)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.source is None:
            return
        self.setFocus()
        self.block = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        cell = self._pos_to_cell(event.position().toPoint())
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.anchor is not None:
            self.head = cell
        else:
            self.anchor = self.head = cell
        self.viewport().update()
        self.changed.emit()

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self.anchor is None:
            return
        pos = event.position().toPoint()
        if pos.y() < 0:
            self.verticalScrollBar().setValue(self.top - 1)
        elif pos.y() > self.viewport().height():
            self.verticalScrollBar().setValue(self.top + 1)
        self.head = self._pos_to_cell(pos)
        self.viewport().update()
        self.changed.emit()

    # keyboard --------------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, mods = event.key(), event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        bar = self.verticalScrollBar()
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif key == Qt.Key.Key_Escape and self.has_selection():
            self.clear_selection()
        elif shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home,
                               Qt.Key.Key_End) and self.source is not None:
            self._extend(key, block=alt)
        elif key == Qt.Key.Key_Down:
            bar.setValue(self.top + 1)
        elif key == Qt.Key.Key_Up:
            bar.setValue(self.top - 1)
        elif key == Qt.Key.Key_PageDown:
            bar.setValue(self.top + self.visible_lines - 1)
        elif key == Qt.Key.Key_PageUp:
            bar.setValue(self.top - self.visible_lines + 1)
        elif key == Qt.Key.Key_Home and ctrl:
            bar.setValue(0)
            self.horizontalScrollBar().setValue(0)
        elif key == Qt.Key.Key_End and ctrl:
            bar.setValue(bar.maximum())
        elif key == Qt.Key.Key_Home:
            self.horizontalScrollBar().setValue(0)
        elif key == Qt.Key.Key_Left:
            h = self.horizontalScrollBar()
            h.setValue(h.value() - 8 * self.cw)
        elif key == Qt.Key.Key_Right:
            h = self.horizontalScrollBar()
            h.setValue(h.value() + 8 * self.cw)
        else:
            super().keyPressEvent(event)

    def _extend(self, key, block: bool) -> None:
        """Shift+arrow grows the selection from the caret; with Alt it is a vertical (block) selection."""
        if self.head is None:
            self.anchor = self.head = (self.top, 0)
        self.block = block
        line, col = self.head
        text = self.source.line(line)
        if key == Qt.Key.Key_Left:
            col = max(0, col - 1)
        elif key == Qt.Key.Key_Right:
            col = col + 1 if block else min(len(text), col + 1)
        elif key == Qt.Key.Key_Up:
            line = max(0, line - 1)
            col = col_of_vcol(self.source.line(line), vcol_of(text, col))
        elif key == Qt.Key.Key_Down:
            line = min(self.total - 1, line + 1)
            col = col_of_vcol(self.source.line(line), vcol_of(text, col))
        elif key == Qt.Key.Key_Home:
            col = 0
        elif key == Qt.Key.Key_End:
            col = len(text)
        self.head = (line, col)
        if not (self.top <= line < self.top + self.visible_lines):
            self.goto_line(line)
        self.viewport().update()
        self.changed.emit()

    # painting --------------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        t = theme.current()
        p.fillRect(self.viewport().rect(), QColor(t["bg"]))
        if self.source is None:
            return
        cw, lh, gut = self.cw, self.lh, self.gutter()
        hoff = self.horizontalScrollBar().value()
        p.setFont(self.font())
        ascent = self.fontMetrics().ascent() + 1
        w, h = self.viewport().width(), self.viewport().height()
        p.fillRect(QRect(0, 0, gut - 6, h), QColor(t["card"]))
        longest = self._max_vcols
        for row in range(self.visible_lines + 1):
            n = self.top + row
            if n >= self.total:
                break
            y = row * lh
            text = self.source.line(n)
            expanded = text.expandtabs(TAB)
            longest = max(longest, len(expanded))
            rng = self.line_range(n)
            if rng is not None:
                x0 = gut + vcol_of(text, rng[0]) * cw - hoff
                x1 = gut + (vcol_of(text, min(rng[1], len(text))) + (1 if rng[1] > len(text) else 0)) * cw - hoff
                wash = QColor(t["accent"])
                wash.setAlpha(90)             # a see-through wash keeps the text readable in both schemes
                p.fillRect(QRect(x0, y, max(x1 - x0, cw // 2 if self.block else 0), lh), wash)
            if self.match and self.match[0] == n:
                mx = gut + vcol_of(text, self.match[1]) * cw - hoff
                p.fillRect(QRect(mx, y, self.match[2] * cw, lh), QColor(t["accent"]))
            p.setClipRect(QRect(gut, 0, max(0, w - gut), h))
            p.setPen(QColor(t["fg"]))
            p.drawText(gut - hoff, y + ascent, expanded)
            if self.match and self.match[0] == n:
                mx = gut + vcol_of(text, self.match[1]) * cw - hoff
                p.setClipRect(QRect(max(mx, gut), y, self.match[2] * cw, lh))
                p.setPen(QColor(t["accent_fg"]))
                p.drawText(gut - hoff, y + ascent, expanded)
            p.setClipping(False)
            p.setPen(QColor(t["dim"]))
            label = str(n + 1)
            p.drawText(gut - 10 - len(label) * cw, y + ascent, label)
        if longest != self._max_vcols:
            self._max_vcols = longest
            hbar = self.horizontalScrollBar()
            hbar.setRange(0, max(0, longest * cw - (w - gut) + cw * 2))
            hbar.setPageStep(max(1, w - gut))

