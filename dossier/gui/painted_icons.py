"""A few small icons drawn in code, used when the chosen icon set has no file for them (so a set never
shows a blank where a close cross or a terminal belongs). A real icon of the same name in a set wins."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

SIZES = (16, 20, 24, 32)


def _canvas(size: int, ratio: float) -> tuple:
    px = int(size * ratio)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    pix.setDevicePixelRatio(ratio)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 16.0, size / 16.0)            # draw on a 16 by 16 grid whatever the size
    return pix, p


def _pen(color: str, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _close(p: QPainter, color: str) -> None:
    p.setPen(_pen(color, 1.6))
    p.drawLine(QPointF(4.5, 4.5), QPointF(11.5, 11.5))
    p.drawLine(QPointF(11.5, 4.5), QPointF(4.5, 11.5))


def _terminal(p: QPainter, color: str) -> None:
    p.setPen(_pen(color, 1.3))
    p.drawRoundedRect(QRectF(1.5, 2.5, 13, 11), 2, 2)
    p.drawPolyline([QPointF(4.5, 5.8), QPointF(7.0, 8.0), QPointF(4.5, 10.2)])
    p.drawLine(QPointF(8.6, 10.4), QPointF(11.6, 10.4))


PAINTED: dict = {"x": _close, "terminal-2": _terminal}


def has(name: str) -> bool:
    return name in PAINTED


def icon(name: str, color: str, ratio: float = 1.0) -> QIcon:
    draw: Callable = PAINTED[name]
    result = QIcon()
    for size in SIZES:
        pix, p = _canvas(size, ratio)
        draw(p, color)
        p.end()
        result.addPixmap(pix)
    return result
