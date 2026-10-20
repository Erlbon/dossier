"""How the program looks beyond the colour scheme: bold on or off, and the font.

Two independent bold switches: the lists (folder names, marked items, the names on the Home page) and the bars (address bar, tabs,
buttons). The font is one family and size for the whole program; an empty family and size 0 mean the system's own. The state lives in
this module so the model and the panels can ask without knowing the window; the window sets it from the settings.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

bold_lists = True
bold_bars = True
_default: Optional[QFont] = None


def weight() -> str:
    """The CSS font-weight of the bars."""
    return "bold" if bold_bars else "normal"


def system_font() -> QFont:
    """The font the program started with, before any choice of ours."""
    global _default
    if _default is None:
        _default = QFont(QApplication.font())
    return QFont(_default)


def apply_font(family: str, size: float) -> None:
    """Set the program's font. ``""`` and ``0`` give back the system's."""
    base = system_font()
    font = QFont(base)
    if family:
        font.setFamily(family)
    if size and size > 0:
        font.setPointSizeF(float(size))
    QApplication.setFont(font)


def set_bold(lists: bool, bars: bool) -> None:
    global bold_lists, bold_bars
    bold_lists, bold_bars = bool(lists), bool(bars)
