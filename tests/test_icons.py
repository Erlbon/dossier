"""Icons: Tabler SVGs painted in the scheme colours, wired into the list, drives and F-key bar."""
import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize, Qt  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.filetypes import all_icon_names  # noqa: E402
from dossier.gui import icon_set, theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def dominant_color(icon):
    image = icon.pixmap(QSize(24, 24)).toImage()
    best = None
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200:
                best = c if best is None or c.alpha() > best.alpha() else best
    return best


def test_every_icon_the_app_uses_renders_something(app):
    icon_set.clear_cache()
    for name in sorted(all_icon_names() | {"copy", "pencil", "trash", "folder-plus", "arrows-right-left"}):
        assert not icon_set.icon(name, "#123456").isNull(), name


def test_an_icon_is_painted_in_the_requested_colour(app):
    icon_set.clear_cache()
    c = dominant_color(icon_set.icon("folder", "#d4a94f"))
    assert c is not None and (c.red(), c.green(), c.blue()) == (0xD4, 0xA9, 0x4F)
    c2 = dominant_color(icon_set.icon("folder", "#112233"))
    assert (c2.red(), c2.green(), c2.blue()) == (0x11, 0x22, 0x33)


def test_a_missing_icon_is_empty_not_an_error(app):
    assert icon_set.icon("no-such-icon-anywhere").isNull()


def test_the_cache_is_reused_and_can_be_cleared(app):
    icon_set.clear_cache()
    a = icon_set.icon("file", "#000000")
    assert icon_set.icon("file", "#000000") is a
    icon_set.clear_cache()
    assert icon_set.icon("file", "#000000") is not a


# in the window ---------------------------------------------------------------------------------
from tests.test_gui_commander import FakeDialogs  # noqa: E402,F401
from dossier.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def win(app, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "book.epub").write_text("x")
    (tmp_path / "pic.jpg").write_text("x")
    (tmp_path / "mystery.zzz").write_text("x")
    w = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)),
                   dialogs=FakeDialogs())
    w.show()
    yield w
    w.close()


def test_list_rows_have_icons_by_type(win):
    m = win.left.model
    by_name = {m.entry_at(r).name: m.index(r, 0) for r in range(m.entry_count())}
    for name in ("..", "sub", "book.epub", "pic.jpg", "mystery.zzz"):
        assert not m.data(by_name[name], Qt.ItemDataRole.DecorationRole).isNull(), name
    assert m.data(by_name["book.epub"], Qt.ItemDataRole.DecorationRole) is not \
        m.data(by_name["pic.jpg"], Qt.ItemDataRole.DecorationRole)
    assert m.data(m.index(0, 1), Qt.ItemDataRole.DecorationRole) is None   # only the name column


def test_marked_items_get_a_gold_icon(win):
    m = win.left.model
    row = m.row_of("book.epub")
    plain = dominant_color(m.data(m.index(row, 0), Qt.ItemDataRole.DecorationRole))
    win.selection.add([m.entry_at(row).path])
    marked = dominant_color(m.data(m.index(row, 0), Qt.ItemDataRole.DecorationRole))
    assert QColor(theme.current()["marked"]).rgb() == marked.rgb() != plain.rgb()


def test_f_key_buttons_and_drive_chip_have_icons(win):
    assert all(not b.icon().isNull() for b in win._fkey_buttons)
    assert not win.left.drive_bar.chip.icon().isNull()
    assert all(not a.icon().isNull() for a in win.left.drive_bar.menu.actions())


def test_a_scheme_change_repaints_the_icons(win):
    win.set_scheme("light")
    light = dominant_color(win._fkey_buttons[0].icon())
    win.set_scheme("dark")
    dark = dominant_color(win._fkey_buttons[0].icon())
    assert light.rgb() == QColor(theme.LIGHT["fg"]).rgb() and dark.rgb() == QColor(theme.DARK["fg"]).rgb()


def test_the_list_background_follows_the_scheme_in_both_directions(win):
    from PyQt6.QtGui import QPalette
    for scheme, tokens in (("dark", theme.DARK), ("light", theme.LIGHT), ("dark", theme.DARK)):
        win.set_scheme(scheme)
        for panel in (win.left, win.right):
            for widget in (panel.table, panel.table.viewport()):
                assert widget.palette().color(QPalette.ColorRole.Base) == QColor(tokens["bg"]), (scheme, widget)
