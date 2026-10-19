"""Light and dark colours, taken from pluteus (``pluteus/static/base.css``): the same tokens, gold
accent and cool grey surfaces, switchable between Auto (follow the system), Light and Dark.

One table of tokens per scheme; a palette is built from it, so the whole window, the lists and
the folder notes share it. The pairs that matter for reading are checked against the WCAG contrast
formula in ``tests/test_theme.py``. Nothing here dims a panel: the active panel is shown by its
address bar only.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

LIGHT = {
    "bg": "#ffffff", "fg": "#1d2330", "dim": "#636b7d", "line": "#d9dde7", "card": "#f5f6fa",
    "accent": "#8a6410", "accent_fg": "#ffffff", "danger": "#b3382c",
    "cursor_bg": "#ecdfbd", "cursor_fg": "#1d2330", "marked": "#7a5710",
}
DARK = {
    "bg": "#14171f", "fg": "#e6e9f2", "dim": "#9aa3b8", "line": "#2b3140", "card": "#1c212c",
    "accent": "#d4a94f", "accent_fg": "#1a1406", "danger": "#ef7b6f",
    "cursor_bg": "#3b3322", "cursor_fg": "#e6e9f2", "marked": "#d4a94f",
}
SCHEMES = ("auto", "light", "dark")

_current = dict(LIGHT)


def current() -> dict:
    """The tokens of the scheme that is on screen now."""
    return _current


def luminance(color: str) -> float:
    c = QColor(color)
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two colours (1 to 21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    """``a`` blended into ``b``: amount 0 is all ``b``, 1 is all ``a``. Returns '#rrggbb'."""
    ca, cb = QColor(a), QColor(b)
    k = max(0.0, min(1.0, amount))
    return QColor(round(cb.red() + (ca.red() - cb.red()) * k), round(cb.green() + (ca.green() - cb.green()) * k),
                  round(cb.blue() + (ca.blue() - cb.blue()) * k)).name()


def is_dark(t: Optional[dict] = None) -> bool:
    return luminance((t or _current)["bg"]) < 0.3


def tab_colors(t: Optional[dict] = None) -> dict:
    """The folder tabs. The current tab and the address field that belongs to it are solid gold in the active
    panel and a dark gold in the other panel; every tab that is not the current one is blue, in both panels.
    Every tab has a thin outline. Text colours are chosen for contrast (checked in tests/test_theme.py)."""
    t = t or _current
    dark = is_dark(t)
    inactive = mix(t["accent"], t["bg"], 0.30)
    dim = mix(t["accent"], t["bg"], 0.50 if dark else 0.34)
    blue = {"fill": "#2f4d77", "line": "#6b90c2", "text": "#e3ecf8", "hover": "#3b5f93"} if dark else            {"fill": "#cfe0f5", "line": "#4b74a8", "text": "#12294a", "hover": "#bcd3ef"}
    return {
        "active_fill": t["accent"], "active_text": t["accent_fg"], "active_line": QColor(t["accent"]).darker(170).name(),
        "dim_fill": dim, "dim_text": t["fg"] if dark else t["fg"],
        "inactive_fill": inactive, "inactive_text": t["fg"], "inactive_line": t["accent"],
        "hover_fill": mix(t["accent"], t["bg"], 0.48),
        "blue_fill": blue["fill"], "blue_line": blue["line"], "blue_text": blue["text"], "blue_hover": blue["hover"],
    }


def build_palette(t: dict) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "card"), (R.WindowText, "fg"), (R.Base, "bg"), (R.AlternateBase, "card"),
                      (R.Text, "fg"), (R.Button, "card"), (R.ButtonText, "fg"), (R.ToolTipBase, "card"),
                      (R.ToolTipText, "fg"), (R.Highlight, "cursor_bg"), (R.HighlightedText, "cursor_fg"),
                      (R.PlaceholderText, "dim"), (R.Link, "accent"), (R.LinkVisited, "dim"),
                      (R.BrightText, "danger"), (R.Mid, "line"), (R.Midlight, "line"), (R.Dark, "line"),
                      (R.Light, "bg"), (R.Shadow, "line")):
        p.setColor(role, QColor(t[key]))
    D = QPalette.ColorGroup.Disabled
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(D, role, QColor(t["dim"]))
    return p


def system_is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:   # Qt older than 6.5
        return False


class ThemeManager(QObject):
    """Owns the chosen scheme (auto, light, dark), applies it, and follows the system in auto."""

    changed = pyqtSignal()

    def __init__(self, app: QApplication, scheme: str = "auto", parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.scheme = scheme if scheme in SCHEMES else "auto"
        try:
            app.styleHints().colorSchemeChanged.connect(lambda _s: self.apply() if self.scheme == "auto" else None)
        except AttributeError:
            pass
        self.apply()

    def tokens(self) -> dict:
        dark = system_is_dark(self.app) if self.scheme == "auto" else self.scheme == "dark"
        return DARK if dark else LIGHT

    def set_scheme(self, scheme: str) -> None:
        if scheme in SCHEMES and scheme != self.scheme:
            self.scheme = scheme
            self.apply()

    def apply(self) -> None:
        global _current
        _current = dict(self.tokens())
        self.app.setStyle("Fusion")   # draws from the palette alone, immune to native dark-mode quirks
        self.app.setPalette(build_palette(_current))
        self.changed.emit()
