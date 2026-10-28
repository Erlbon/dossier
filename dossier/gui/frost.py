"""The frosted look, shared by the picture viewer and the file manager: a picture of the screen, blurred by Dossier itself.

The blur is ours (scale far down and back up with smoothing), so it has the same strength on every computer and needs no help from
Windows. ``grab_screens`` takes a picture of every screen; the file manager paints the part behind its window and lays a tint over it
(see ``frost_window.py``). ``active`` says whether the file manager is frosted now, so the bars that normally paint their own
background (``fill``) leave it out and let the frost show.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QGuiApplication, QPixmap

DEFAULT_LEVEL = 50            # percent of the screen that shows through the file manager's frame (the viewer has its own, higher)
MAX_LEVEL = 80                # never clear: the menu and the bars must stay readable

_active = False


def active() -> bool:
    return _active


def set_active(on: bool) -> None:
    global _active
    _active = bool(on)


def fill(color: str) -> str:
    """The background a bar paints: its own colour, or nothing while the window is frosted (the window paints the frost)."""
    return "transparent" if _active else color


def tint_alpha(level: int) -> int:
    """The opacity (0 to 255) of the window-coloured layer over the blurred screen when ``level`` percent shows through."""
    return round(255 * (100 - max(1, min(MAX_LEVEL, int(level)))) / 100)


def screen_under_cursor():
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


def grab_backdrop() -> Optional[QPixmap]:
    """A picture of the screen under the cursor, or None when the system will not give one."""
    screen = screen_under_cursor()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)
    return None if pixmap.isNull() else pixmap


def blurred(pixmap: QPixmap, shrink: int = 16) -> QPixmap:
    """``pixmap`` softened: scaled far down and back up with smoothing."""
    w, h = pixmap.width(), pixmap.height()
    small = pixmap.scaled(max(1, w // shrink), max(1, h // shrink), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def grab_screens() -> dict:
    """``{screen name: (geometry, blurred picture)}`` for every screen that gives a picture."""
    shots: dict = {}
    for screen in QGuiApplication.screens():
        pixmap = screen.grabWindow(0)
        if not pixmap.isNull():
            shots[screen.name()] = (screen.geometry(), blurred(pixmap))
    return shots
