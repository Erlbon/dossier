"""The hex view of the F3 viewer: offsets, bytes and text side by side, for a file of any size (only the visible rows are read).

Read-only. Mouse and keys move a cursor over the bytes (Shift extends a selection), Ctrl+C copies the selection as hex and
Ctrl+Shift+C as text, ``goto`` and ``show_match`` scroll to an offset. The reading and searching is ``core/hexview.py``.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QGuiApplication, QKeyEvent, QPainter
from PyQt6.QtWidgets import QAbstractScrollArea

from ..core.hexview import PRINTABLE, WIDTH, HexFile, format_row, offset_digits
from . import theme

GAP = 2                # characters between the columns
MID = 1                # the extra space between the two halves of the hex column


class HexView(QAbstractScrollArea):
    changed = pyqtSignal()                 # the cursor, the selection or the file changed: the status line is read again

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.file: Optional[HexFile] = None
        self.cursor = 0
        self.anchor = 0
        self.match: Optional[tuple] = None            # (offset, length)
        self._scale = 1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # geometry ------------------------------------------------------------------------------------------------------------------------
    @property
    def cw(self) -> int:
        return max(1, self.fontMetrics().horizontalAdvance("M"))

    @property
    def lh(self) -> int:
        return self.fontMetrics().height() + 2

    @property
    def visible_rows(self) -> int:
        return max(1, self.viewport().height() // self.lh)

    def _digits(self) -> int:
        return offset_digits(self.file.size) if self.file else 8

    def _hex_x(self) -> int:
        return (self._digits() + GAP) * self.cw + 4

    def _text_x(self) -> int:
        return self._hex_x() + (WIDTH * 3 + MID + GAP) * self.cw

    def _byte_x(self, column: int) -> int:
        return self._hex_x() + (column * 3 + (MID if column >= 8 else 0)) * self.cw

    @property
    def top_row(self) -> int:
        return self.verticalScrollBar().value() * self._scale

    def _update_scroll(self) -> None:
        rows = self.file.rows if self.file else 0
        self._scale = rows // 2_000_000_000 + 1
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, (rows - self.visible_rows) // self._scale + (1 if self._scale > 1 else 0)))
        bar.setSingleStep(1)
        bar.setPageStep(max(1, self.visible_rows // self._scale))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll()

    # the file ------------------------------------------------------------------------------------------------------------------------
    def set_file(self, file: Optional[HexFile]) -> None:
        self.file = file
        self.cursor = self.anchor = 0
        self.match = None
        self.verticalScrollBar().setValue(0)
        self._update_scroll()
        self.viewport().update()
        self.changed.emit()

    def refresh(self) -> bool:
        """A file that grew (a log, a download) is read again; True when it changed."""
        if self.file is None or not self.file.refresh():
            return False
        self._update_scroll()
        self.viewport().update()
        self.changed.emit()
        return True

    def goto(self, offset: int, select: int = 0) -> None:
        """Put the cursor on ``offset`` (and select ``select`` bytes from it) and scroll it into view."""
        if self.file is None or self.file.size == 0:
            return
        self.cursor = max(0, min(offset, self.file.size - 1))
        self.anchor = self.cursor if not select else min(self.cursor + select - 1, self.file.size - 1)
        self._reveal()
        self.changed.emit()
        self.viewport().update()

    def show_match(self, offset: int, length: int) -> None:
        self.match = (offset, length)
        self.goto(offset)
        self.anchor = self.cursor

    def clear_match(self) -> None:
        self.match = None
        self.viewport().update()

    def _reveal(self) -> None:
        row = self.cursor // WIDTH
        bar = self.verticalScrollBar()
        first = self.top_row
        if row < first or row >= first + self.visible_rows:
            bar.setValue(max(0, (row - self.visible_rows // 3) // self._scale))
        self.viewport().update()

    # the selection -------------------------------------------------------------------------------------------------------------------
    def selection(self) -> tuple:
        """``(first offset, number of bytes)`` of the selection; the byte under the cursor when nothing is selected."""
        if self.file is None or self.file.size == 0:
            return 0, 0
        lo, hi = min(self.cursor, self.anchor), max(self.cursor, self.anchor)
        return lo, hi - lo + 1

    def selected_bytes(self, limit: int = 1 << 20) -> bytes:
        lo, n = self.selection()
        return self.file.read(lo, min(n, limit)) if self.file else b""

    def copy_hex(self) -> None:
        QGuiApplication.clipboard().setText(" ".join(f"{b:02X}" for b in self.selected_bytes()))

    def copy_text(self) -> None:
        QGuiApplication.clipboard().setText("".join(PRINTABLE.get(b, ".") for b in self.selected_bytes()))

    # painting ------------------------------------------------------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self.viewport())
        t = theme.current()
        p.fillRect(self.viewport().rect(), QColor(t["bg"]))
        if self.file is None:
            return
        p.setFont(self.font())
        cw, lh = self.cw, self.lh
        ascent = self.fontMetrics().ascent() + 1
        digits, hx, tx = self._digits(), self._hex_x(), self._text_x()
        p.fillRect(QRect(0, 0, hx - 6, self.viewport().height()), QColor(t["card"]))
        lo, n = self.selection()
        sel_lo, sel_hi = lo, lo + n
        wash = QColor(t["accent"])
        wash.setAlpha(110)
        for r in range(self.visible_rows + 1):
            row = self.top_row + r
            if row >= self.file.rows:
                break
            y = r * lh
            data = self.file.row(row)
            base = row * WIDTH
            for c in range(len(data)):
                at = base + c
                if sel_lo <= at < sel_hi:
                    p.fillRect(QRect(self._byte_x(c), y, 2 * cw, lh), wash)
                    p.fillRect(QRect(tx + c * cw, y, cw, lh), wash)
                if self.match and self.match[0] <= at < self.match[0] + self.match[1]:
                    p.fillRect(QRect(self._byte_x(c), y, 2 * cw, lh), QColor(t["accent"]))
                    p.fillRect(QRect(tx + c * cw, y, cw, lh), QColor(t["accent"]))
                if at == self.cursor:
                    p.setPen(QColor(t["fg"]))
                    p.drawRect(QRect(self._byte_x(c) - 1, y, 2 * cw + 1, lh - 1))
            off, hexes, text = format_row(base, data, digits)
            p.setPen(QColor(t["dim"]))
            p.drawText(4, y + ascent, off)
            p.setPen(QColor(t["fg"]))
            for c, b in enumerate(data):
                if self.match and self.match[0] <= base + c < self.match[0] + self.match[1]:
                    p.setPen(QColor(t["accent_fg"]))
                else:
                    p.setPen(QColor(t["fg"]) if b else QColor(t["dim"]))
                p.drawText(self._byte_x(c), y + ascent, f"{b:02X}")
            for c, ch in enumerate(text):
                p.setPen(QColor(t["accent_fg"]) if self.match and self.match[0] <= base + c < self.match[0] + self.match[1] else
                         QColor(t["fg"]) if ch != "." else QColor(t["dim"]))
                p.drawText(tx + c * cw, y + ascent, ch)

    # mouse and keys ------------------------------------------------------------------------------------------------------------------
    def offset_at(self, x: int, y: int) -> int:
        if self.file is None or self.file.size == 0:
            return -1
        row = self.top_row + max(0, y // self.lh)
        tx = self._text_x()
        if x >= tx:
            col = min(WIDTH - 1, (x - tx) // self.cw)
        else:
            x -= self._hex_x()
            col = min(WIDTH - 1, max(0, (x - (MID * self.cw if x >= (8 * 3 + MID) * self.cw else 0)) // (3 * self.cw)))
        return max(0, min(row * WIDTH + int(col), self.file.size - 1))

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        at = self.offset_at(int(event.position().x()), int(event.position().y()))
        if at >= 0:
            self.cursor = at
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.anchor = at
            self.changed.emit()
            self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            at = self.offset_at(int(event.position().x()), int(event.position().y()))
            if at >= 0 and at != self.cursor:
                self.cursor = at
                self._reveal()
                self.changed.emit()

    def wheelEvent(self, event) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - (event.angleDelta().y() // 120) * 3)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.file is None:
            return super().keyPressEvent(event)
        mods, key = event.modifiers(), event.key()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        size = self.file.size
        page = self.visible_rows * WIDTH
        move = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -WIDTH, Qt.Key.Key_Down: WIDTH,
                Qt.Key.Key_PageUp: -page, Qt.Key.Key_PageDown: page}.get(key)
        if ctrl and key == Qt.Key.Key_C:
            (self.copy_text if shift else self.copy_hex)()
            return
        if ctrl and key == Qt.Key.Key_A:
            self.anchor, self.cursor = 0, max(0, size - 1)
        elif key == Qt.Key.Key_Home:
            self.cursor = 0 if ctrl else self.cursor - self.cursor % WIDTH
        elif key == Qt.Key.Key_End:
            self.cursor = size - 1 if ctrl else min(size - 1, self.cursor - self.cursor % WIDTH + WIDTH - 1)
        elif move is not None:
            self.cursor = max(0, min(size - 1, self.cursor + move))
        else:
            return super().keyPressEvent(event)
        if not shift and key != Qt.Key.Key_A:
            self.anchor = self.cursor
        self._reveal()
        self.changed.emit()
