"""Choosing the columns of the folder lists: Name and Type stay, the rest can be switched on and off and moved."""
import os
import sys

import pytest

from dossier.core import columns
from dossier.core.vfs import LocalFileSystem

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_definitions_hang_together():
    assert set(columns.DEFAULT_ORDER) == set(columns.KEYS) == set(columns.LABELS)
    assert columns.PROTECTED == {"name", "type"} and not columns.PROTECTED & columns.DEFAULT_HIDDEN
    assert columns.type_text("a.jpg", False) == "JPG file" and columns.type_text("d", True) == "Folder"
    assert columns.type_text("Makefile", False) == "File" and columns.type_text(".bashrc", False) == "File"


def test_a_listing_carries_created_last_opened_and_attributes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    fs = LocalFileSystem()
    for e in (fs.stat(str(f)), [x for x in fs.list(str(tmp_path)) if x.name == "a.txt"][0]):
        assert e.ctime > 0 and e.atime > 0 and e.attrs
    if sys.platform == "win32":
        os.chmod(f, 0o444)
        assert "R" in columns.attributes_text(fs.stat(str(f)).attrs)
        os.chmod(f, 0o666)
    else:
        assert columns.attributes_text(fs.stat(str(f)).attrs).startswith("rw")


def visible(panel):
    h = panel.table.horizontalHeader()
    return [columns.KEYS[h.logicalIndex(v)] for v in range(h.count()) if not h.isSectionHidden(h.logicalIndex(v))]


def test_by_default_name_type_size_and_date_show_in_that_order(world):
    win, *_ = world
    assert visible(win.left) == ["name", "type", "size", "modified"] and visible(win.right) == visible(win.left)


def test_a_column_is_switched_on_and_off_for_both_panels_and_remembered(world):
    win, *_ = world
    win._column_toggled("created", True)
    assert visible(win.left) == ["name", "type", "size", "modified", "created"] and "created" in visible(win.right)
    win._column_toggled("size", False)
    assert "size" not in visible(win.left) and "size" not in visible(win.right)
    hidden, order = win.column_choice()
    assert "size" in hidden and "created" not in hidden and order[0] == "name"


def test_name_and_type_cannot_be_hidden_even_if_the_settings_say_so(world):
    win, *_ = world
    win._column_toggled("type", False)
    win.settings.setValue("view/columns_hidden", "name,type,size")
    win.apply_columns_everywhere()
    assert "name" in visible(win.left) and "type" in visible(win.left) and "size" not in visible(win.left)


def test_the_shared_dialog_gets_the_columns_and_its_answer_is_applied(world, monkeypatch):
    win, *_ = world
    seen = {}

    def fake(dlg):
        seen["keys"] = dlg.column_order()
        seen["name_checkable"] = bool(dlg.list_widget.item(0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
        for i in range(dlg.list_widget.count()):
            if dlg.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == "attributes":
                dlg.list_widget.item(i).setCheckState(Qt.CheckState.Checked)
        dlg.move_selected(0)

    monkeypatch.setattr(type(win), "_run_column_dialog", lambda self, dlg: fake(dlg))
    win.open_column_settings()
    assert seen["keys"] == list(columns.DEFAULT_ORDER) and not seen["name_checkable"]
    assert "attributes" in visible(win.left)


def test_dragging_a_header_changes_the_order_for_both_panels(world):
    win, *_ = world
    h = win.left.table.horizontalHeader()
    h.moveSection(h.visualIndex(columns.index_of("modified")), h.visualIndex(columns.index_of("size")))
    pump(win, lambda: visible(win.right)[:4] == ["name", "type", "modified", "size"])
    assert win.column_choice()[1][:4] == ["name", "type", "modified", "size"]


def test_new_columns_show_their_values_and_sort(world):
    win, d, left, *_ = world
    (left / "b.txt").write_text("1")
    (left / "a.jpg").write_text("22")
    win._column_toggled("attributes", True)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    m = win.left.model
    row = next(r for r in range(m.entry_count()) if m.entry_at(r).name == "a.jpg")
    assert m.index(row, columns.index_of("type")).data() == "JPG file"
    assert m.index(row, columns.index_of("attributes")).data()
    m.sort(columns.index_of("type"), Qt.SortOrder.AscendingOrder)
    files = [m.entry_at(r).name for r in range(m.entry_count()) if not m.entry_at(r).is_dir]
    assert files.index("a.jpg") < files.index("b.txt")                           # JPG file before TXT file


def test_the_home_page_keeps_its_own_three_columns_and_the_choice_returns_after_it(world):
    win, *_ = world
    win._column_toggled("created", True)
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    h = win.left.table.horizontalHeader()
    assert [columns.KEYS[h.logicalIndex(v)] for v in range(h.count()) if not h.isSectionHidden(h.logicalIndex(v))] == \
        ["name", "size", "modified"]
    win.left.set_folder(str(world[2]))
    pump(win, lambda: not win.left.is_home)
    assert "created" in visible(win.left) and visible(win.left)[:2] == ["name", "type"]


def test_the_menu_entries_exist_and_defaults_come_back(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Columns..." in [a.text() for a in menus["View"].actions()]
    win._column_toggled("created", True)
    assert "created" in visible(win.left)

    def press_reset(dlg):                                 # the dialog's own Back to the Default Columns button
        from PyQt6.QtWidgets import QPushButton
        next(b for b in dlg.findChildren(QPushButton) if b.text() == "Back to the Default Columns").click()
    win._run_column_dialog = press_reset
    win.open_column_settings()
    assert visible(win.left) == ["name", "type", "size", "modified"]


def test_on_the_home_page_the_columns_choice_is_kept_and_the_page_says_why_nothing_changes(world):
    win, d, left, *_ = world
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    win._set_active(win.left)
    win.show_column_menu(win.left, win.left.table.rect().center())
    assert "Home page has its own three columns" in win.status.text()
    win._column_toggled("created", True)
    h = win.left.table.horizontalHeader()
    assert [columns.KEYS[h.logicalIndex(v)] for v in range(h.count()) if not h.isSectionHidden(h.logicalIndex(v))] == \
        ["name", "size", "modified"]                                   # the page still shows its three
    win.left.set_folder(str(left))
    pump(win, lambda: not win.left.is_home)
    assert "created" in visible(win.left)                               # and the folder shows what was chosen


# Fit Columns to Panel (the owner's option A, 2026-11-18) ------------------------------------------------------------------
def _fits(panel):
    h = panel.table.horizontalHeader()
    return h.length() <= panel.table.viewport().width() and not panel.table.horizontalScrollBar().isVisible()


def test_fit_columns_is_on_by_default_and_every_edge_stays_on_screen(world):
    win, *_ = world
    win.resize(900, 600)
    pump(win, lambda: _fits(win.left))
    assert win.fit_columns_on() and win.act_fit_columns.isChecked()
    h = win.left.table.horizontalHeader()
    name = columns.index_of("name")
    assert not h.stretchLastSection() and h.sectionResizeMode(name) == h.ResizeMode.Stretch


def test_widening_a_column_narrows_name_and_name_keeps_a_minimum(world):
    win, *_ = world
    win.resize(900, 600)
    pump(win, lambda: _fits(win.left))
    h = win.left.table.horizontalHeader()
    name, size = columns.index_of("name"), columns.index_of("size")
    before = h.sectionSize(name)
    h.resizeSection(size, h.sectionSize(size) + 60)
    pump(win, lambda: h.sectionSize(name) < before and _fits(win.left))   # Linux lays out in more steps: wait for the last one
    h.resizeSection(size, 2000)                          # far wider than the panel: Name stops at its minimum, scrollbar back
    pump(win, lambda: win.left._fit_squeezed)
    assert h.sectionSize(name) >= win.left.NAME_MIN
    h.resizeSection(size, 80)                            # room again: Name stretches again
    pump(win, lambda: not win.left._fit_squeezed)
    assert h.sectionResizeMode(name) == h.ResizeMode.Stretch


def test_switching_fit_off_restores_stretch_last_and_is_remembered(world):
    win, dialogs, left, right, tmp_path = world
    win.act_fit_columns.setChecked(False)
    for panel in (win.left, win.right):
        h = panel.table.horizontalHeader()
        assert h.stretchLastSection() and h.sectionResizeMode(columns.index_of("name")) == h.ResizeMode.Interactive
    win._column_toggled("created", True)                 # a new layout keeps the choice
    assert win.left.table.horizontalHeader().stretchLastSection()
    from dossier.gui.main_window import MainWindow
    from tests.test_gui_commander import FakeDialogs
    again = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=FakeDialogs())
    try:
        assert not again.fit_columns_on() and not again.act_fit_columns.isChecked()
        assert again.left.table.horizontalHeader().stretchLastSection()
    finally:
        again.close()


def test_the_header_menu_offers_the_switch_with_its_tick(world, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    win, *_ = world
    shown = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.setdefault("menu", self))
    win._set_active(win.left)
    win.show_column_menu(win.left, win.left.table.rect().center())
    entry = next(a for a in shown["menu"].actions() if a.text() == "Fit Columns to Panel")
    assert entry.isCheckable() and entry.isChecked()
    entry.trigger()
    assert not win.fit_columns_on() and not win.act_fit_columns.isChecked()
