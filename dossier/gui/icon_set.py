"""Icons for the GUI: Tabler outline SVGs (MIT, ``icons/LICENSE-tabler.txt``) painted in the colours of
the current scheme. One icon is one stroke colour, so a scheme change just re-renders the cache.

Frozen builds must include ``dossier/gui/icons`` as data (PyInstaller ``datas``)."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from . import theme

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
SIZES = (16, 20, 24, 32)

_svg_text: dict = {}
_cache: dict = {}


def path_of(name: str) -> str:
    return os.path.join(ICON_DIR, name + ".svg")


def _source(name: str) -> str:
    if name not in _svg_text:
        try:
            with open(path_of(name), encoding="utf-8") as f:
                _svg_text[name] = f.read()
        except OSError:
            _svg_text[name] = ""
    return _svg_text[name]


def _render(svg: str, size: int, ratio: float) -> QPixmap:
    px = int(size * ratio)
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, px, px))
    painter.end()
    pix = QPixmap.fromImage(image)
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(name: str, color: Optional[str] = None) -> QIcon:
    """The icon ``name`` in ``color`` (a '#rrggbb' string; default: the scheme's secondary text colour).
    A missing file gives an empty icon, never an error."""
    color = color or theme.current()["dim"]
    key = (name, color)
    if key in _cache:
        return _cache[key]
    svg = _source(name)
    result = QIcon()
    if svg:
        tinted = svg.replace("currentColor", color)
        app = QGuiApplication.instance()
        ratio = max(1.0, app.devicePixelRatio()) if app else 1.0
        for size in SIZES:
            result.addPixmap(_render(tinted, size, ratio))
    _cache[key] = result
    return result


def clear_cache() -> None:
    """Call when the colour scheme changes."""
    _cache.clear()
