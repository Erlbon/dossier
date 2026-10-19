"""The program icon: a gold folder with a D on a dark tile. ``dossier.svg`` is the master; ``dossier.ico``
(seven sizes, for the Windows exe and the taskbar) and ``dossier-256.png`` are made from it by
``tools/make_icons.py`` and committed, so a build needs no extra step."""
from __future__ import annotations

import os

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "dossier.svg")
ICO = os.path.join(HERE, "dossier.ico")
PNG = os.path.join(HERE, "dossier-256.png")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int, ratio: float = 1.0) -> QImage:
    """The icon drawn from the SVG at ``size`` pixels, so every size is sharp and none is a scaled bitmap."""
    with open(SVG, "rb") as f:
        renderer = QSvgRenderer(QByteArray(f.read()))
    px = int(size * ratio)
    image = QImage(px, px, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    return image


def app_icon() -> QIcon:
    app = QGuiApplication.instance()
    ratio = max(1.0, app.devicePixelRatio()) if app else 1.0
    icon = QIcon()
    for size in SIZES:
        pix = QPixmap.fromImage(render(size, ratio))
        pix.setDevicePixelRatio(ratio)
        icon.addPixmap(pix)
    return icon
