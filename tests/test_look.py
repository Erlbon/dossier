"""Settings > Fonts and Bold: bold on or off in the lists and in the bars, and the font of the program."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QFontDatabase  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import look  # noqa: E402
from dossier.gui.look_settings import DEFAULTS, LookDialog, read_look  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


@pytest.fixture(autouse=True)
def restore_look(app):
    """The look is process-wide state: put it back whatever a test did."""
    saved = QApplication.font()
    yield
    look.set_bold(True, True)
    QApplication.setFont(saved)


def choose(win, monkeypatch, **changes):
    def fake(self, dlg):
        if "system" in changes:
            dlg.use_system.setChecked(changes["system"])
        if "family" in changes:
            dlg.family.setCurrentFont(__import__("PyQt6.QtGui", fromlist=["QFont"]).QFont(changes["family"]))
        if "size" in changes:
            dlg.size.setValue(changes["size"])
        if "lists" in changes:
            dlg.bold_lists.setChecked(changes["lists"])
        if "bars" in changes:
            dlg.bold_bars.setChecked(changes["bars"])
        return True
    monkeypatch.setattr(type(win), "_run_look_dialog", fake)
    win.open_look_settings()


def row_font(win, name):
    m = win.left.model
    pump(win, lambda: any(m.entry_at(i).name == name for i in range(m.entry_count())))      # a refresh may be under way
    r = next(i for i in range(m.entry_count()) if m.entry_at(i).name == name)
    return m.index(r, 0).data(Qt.ItemDataRole.FontRole)


def test_nothing_stored_means_bold_everywhere_and_the_system_font(world):
    win, *_ = world
    assert read_look(win.settings) == DEFAULTS and look.bold_lists and look.bold_bars


def test_bold_in_the_lists_can_be_switched_off_and_on(world, monkeypatch):
    win, d, left, *_ = world
    (left / "folder").mkdir()
    (left / "file.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    assert row_font(win, "folder").bold()
    choose(win, monkeypatch, lists=False)
    assert row_font(win, "folder") is None and not look.bold_lists
    assert str(win.settings.value("view/bold_lists")).lower() == "false"
    choose(win, monkeypatch, lists=True)
    assert row_font(win, "folder").bold()


def test_marked_items_follow_the_same_switch(world, monkeypatch):
    win, d, left, *_ = world
    (left / "a.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.select_all()
    assert row_font(win, "a.txt") is not None and row_font(win, "a.txt").bold()
    choose(win, monkeypatch, lists=False)
    assert row_font(win, "a.txt") is None


def test_bold_in_the_bars_changes_the_styles_the_tabs_and_the_crumbs(world, monkeypatch):
    win, *_ = world
    assert "font-weight:bold" in win.left.bar.styleSheet()
    choose(win, monkeypatch, bars=False)
    assert "font-weight:normal" in win.left.bar.styleSheet() and "font-weight:bold" not in win.left.bar.styleSheet()
    assert "font-weight:normal" in win.left.tab_row.styleSheet() and look.weight() == "normal"
    choose(win, monkeypatch, bars=True)
    assert "font-weight:bold" in win.right.bar.styleSheet()


def test_the_home_page_names_follow_the_lists_switch(world, monkeypatch):
    win, *_ = world
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home and win.left.model.entry_count() > 2)
    m = win.left.model
    first = next(i for i in range(m.entry_count()) if m.entry_at(i).kind not in ("header", "action"))
    assert m.index(first, 0).data(Qt.ItemDataRole.FontRole).bold()
    choose(win, monkeypatch, lists=False)
    assert not m.index(first, 0).data(Qt.ItemDataRole.FontRole).bold()


def test_the_font_is_chosen_remembered_and_given_back(world, monkeypatch):
    win, *_ = world
    system = look.system_font()
    others = [f for f in QFontDatabase.families() if f != system.family()]
    if not others:
        pytest.skip("this platform has only one font (an offscreen test run)")
    family = others[0]
    choose(win, monkeypatch, system=False, family=family, size=14.0)
    assert QApplication.font().family() == family and QApplication.font().pointSizeF() == 14.0
    assert read_look(win.settings)["font_family"] == family and read_look(win.settings)["font_size"] == 14.0
    choose(win, monkeypatch, system=True)
    assert QApplication.font().family() == system.family() and read_look(win.settings)["font_family"] == ""


def test_the_dialog_shows_what_is_stored_and_the_defaults_button_resets(world):
    win, *_ = world
    dlg = LookDialog(win, {"font_family": "Arial", "font_size": 11.0, "bold_lists": False, "bold_bars": False})
    assert not dlg.use_system.isChecked() and dlg.family.isEnabled() and not dlg.bold_lists.isChecked()
    assert dlg.values()["font_size"] == 11.0
    dlg.defaults.click()
    assert dlg.use_system.isChecked() and not dlg.family.isEnabled()
    assert dlg.values() == DEFAULTS


def test_cancelling_changes_nothing(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(type(win), "_run_look_dialog", lambda self, dlg: (dlg.bold_lists.setChecked(False), False)[1])
    win.open_look_settings()
    assert look.bold_lists and win.settings.value("view/bold_lists") is None
