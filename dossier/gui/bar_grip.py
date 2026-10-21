"""The grip of a movable bar."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from . import theme


class BarGrip(QWidget):
    """Six dots at the left end of a bar (the programs bar, the function key bar): drag them to move the bar."""

    dragging = pyqtSignal(object)                 # the global position while the button is down
    dropped = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(12)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag to move the bar")
        self._down = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.current()["dim"]))
        top = (self.height() - 12) // 2
        for col in (3, 7):
            for row in range(3):
                p.drawEllipse(col, top + row * 5, 2, 2)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.dragging.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._down:
            self.dragging.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        if self._down and event.button() == Qt.MouseButton.LeftButton:
            self._down = False
            self.dropped.emit(event.globalPosition().toPoint())
