"""Colour schemes: readable pairs (WCAG), switching, and no dimmed panel."""
import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("name,t", [("light", theme.LIGHT), ("dark", theme.DARK)])
def test_text_pairs_are_readable(name, t):
    pairs = {
        "text on page": (t["fg"], t["bg"]),
        "text on card": (t["fg"], t["card"]),
        "text on cursor row": (t["cursor_fg"], t["cursor_bg"]),
        "marked text on page": (t["marked"], t["bg"]),
        "marked text on cursor row": (t["marked"], t["cursor_bg"]),
        "dim text on page": (t["dim"], t["bg"]),
        "dim text on card": (t["dim"], t["card"]),
        "marked text on card": (t["marked"], t["card"]),
        "text on the quiet cursor row of the inactive panel": (t["fg"], t["line"]),
        "marked text on the quiet cursor row": (t["marked"], t["line"]),
        "danger on page": (t["danger"], t["bg"]),
        "button text on accent": (t["accent_fg"], t["accent"]),
    }
    for what, (a, b) in pairs.items():
        assert theme.contrast(a, b) >= 4.5, f"{name}: {what} is only {theme.contrast(a, b):.2f}:1"


@pytest.mark.parametrize("t", [theme.LIGHT, theme.DARK])
def test_the_cursor_row_is_visibly_different_from_the_page(t):
    assert theme.contrast(t["cursor_bg"], t["bg"]) >= 1.3


def test_the_two_schemes_really_differ():
    assert theme.luminance(theme.LIGHT["bg"]) > 0.8 > 0.2 > theme.luminance(theme.DARK["bg"])


def test_palette_carries_the_tokens(app):
    p = theme.build_palette(theme.DARK)
    assert p.color(QPalette.ColorRole.Base) == QColor(theme.DARK["bg"])
    assert p.color(QPalette.ColorRole.Highlight) == QColor(theme.DARK["cursor_bg"])


def test_manager_switches_and_reports_the_change(app):
    mgr = theme.ThemeManager(app, "light")
    seen = []
    mgr.changed.connect(lambda: seen.append(1))
    assert theme.current()["bg"] == theme.LIGHT["bg"]
    mgr.set_scheme("dark")
    assert theme.current()["bg"] == theme.DARK["bg"] and seen
    assert app.palette().color(QPalette.ColorRole.Base) == QColor(theme.DARK["bg"])
    mgr.set_scheme("nonsense")           # unknown names are ignored
    assert mgr.scheme == "dark"


def test_auto_follows_the_system(app, monkeypatch):
    monkeypatch.setattr(theme, "system_is_dark", lambda _app: True)
    mgr = theme.ThemeManager(app, "auto")
    assert theme.current()["bg"] == theme.DARK["bg"]
    monkeypatch.setattr(theme, "system_is_dark", lambda _app: False)
    mgr.apply()
    assert theme.current()["bg"] == theme.LIGHT["bg"]


@pytest.mark.parametrize("tokens", [theme.LIGHT, theme.DARK])
def test_tab_text_is_readable_on_both_kinds_of_tab(tokens):
    c = theme.tab_colors(tokens)
    assert theme.contrast(c["active_text"], c["active_fill"]) >= 4.5
    assert theme.contrast(c["inactive_text"], c["inactive_fill"]) >= 4.5
    assert theme.contrast(c["inactive_text"], c["hover_fill"]) >= 4.5


@pytest.mark.parametrize("tokens", [theme.LIGHT, theme.DARK])
def test_the_active_tab_is_the_big_gold_and_the_others_a_dark_gold(tokens):
    c = theme.tab_colors(tokens)
    assert c["active_fill"] == tokens["accent"]
    assert c["inactive_fill"] != c["active_fill"] and theme.contrast(c["active_fill"], c["inactive_fill"]) >= 1.5
    assert c["active_line"] != c["active_fill"] and c["inactive_line"] != c["inactive_fill"]   # an outline you can see


def test_mix_blends_between_two_colours():
    assert theme.mix("#000000", "#ffffff", 0.0) == "#ffffff"
    assert theme.mix("#000000", "#ffffff", 1.0) == "#000000"
    assert theme.mix("#ff0000", "#0000ff", 0.5) == "#800080"
