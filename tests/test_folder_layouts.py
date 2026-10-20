"""Folder layouts in the window: a rule applies when its folder is shown, changes go to it, and the default comes back elsewhere."""
import json

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core.columns import DEFAULT_HIDDEN, index_of  # noqa: E402
from dossier.core.layouts import has_rules_for  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs, app, pump, world  # noqa: E402,F401


def goto(win, panel, path):
    panel.set_folder(str(path))
    pump(win, lambda: panel.path == str(path) and not panel.loading)


def tree(tmp):
    for n in ("photos", "photos/2024", "music", "other"):
        (tmp / n).mkdir(parents=True, exist_ok=True)
        (tmp / n / "f.txt").write_text(n)
    return tmp / "photos", tmp / "photos" / "2024", tmp / "music", tmp / "other"


def stored(win):
    return json.loads(win.settings.value("layouts/rules", "[]"))


def photos_layout(win, tmp, scope="only"):
    """The photo folder keeps thumbnails sorted by date, newest first."""
    photos, *_ = tree(tmp)
    goto(win, win.left, photos)
    win.remember_layout(scope)
    win.choose_mode("icons", 192)
    win.left.table.sortByColumn(index_of("modified"), Qt.SortOrder.DescendingOrder)
    return photos


def test_a_folder_keeps_its_view_and_sort_and_the_default_returns_elsewhere(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp)
    _p, _y, music, other = tree(tmp)
    assert win.left.view_mode == "icons" and win.left.icon_px == 192
    goto(win, win.left, music)
    assert win.left.view_mode == "details" and win.left.current_sort() == ("name", False)      # the ordinary view is back
    assert win.settings.value("view/mode_left") in (None, "details")                             # and was never overwritten
    goto(win, win.left, photos)
    assert win.left.view_mode == "icons" and win.left.icon_px == 192 and win.left.current_sort() == ("modified", True)
    rule = stored(win)[0]
    assert rule["scope"] == "only" and rule["mode"] == "icons" and rule["sort"] == "modified" and rule["desc"] is True


def test_a_tree_rule_reaches_the_subfolders_and_an_only_rule_does_not(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp, "tree")
    _p, year, music, other = tree(tmp)
    goto(win, win.left, year)
    assert win.left.view_mode == "icons" and win.left.layout_rule_path == str(photos)
    goto(win, win.left, other)
    assert win.left.view_mode == "details" and win.left.layout_rule_path == ""
    win.remember_layout("only")                                             # music: a rule of its own beside the photo rule
    win.choose_mode("icons", 64)
    goto(win, win.left, music / ".." / "photos")                            # never mind the path form: the same folder
    assert win.left.icon_px == 192


def test_changing_columns_in_a_ruled_folder_changes_the_rule_not_the_default_or_the_other_panel(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp)
    _p, _y, music, other = tree(tmp)
    goto(win, win.right, other)
    win.active = win.left
    win._column_toggled("size", False)
    assert "size" in stored(win)[0]["hidden"]
    assert win.settings.value("view/columns_hidden") in (None, "-", ",".join(sorted(DEFAULT_HIDDEN)))
    assert win.left.table.isColumnHidden(index_of("size")) and not win.right.table.isColumnHidden(index_of("size"))
    goto(win, win.left, music)
    assert not win.left.table.isColumnHidden(index_of("size"))               # the default columns are back
    goto(win, win.left, photos)
    assert win.left.table.isColumnHidden(index_of("size"))


def test_a_sort_change_is_kept_only_where_there_is_a_rule(world):
    win, d, left, right, tmp = world
    photos, _y, music, other = tree(tmp)
    goto(win, win.left, music)
    win.left.table.sortByColumn(index_of("size"), Qt.SortOrder.DescendingOrder)
    assert "layouts/rules" not in win.settings.allKeys() or stored(win) == []
    win.remember_layout("only")
    win.left.table.sortByColumn(index_of("type"), Qt.SortOrder.AscendingOrder)
    assert stored(win)[0]["sort"] == "type"


def test_back_to_the_default_removes_the_rule_and_a_parent_rule_takes_over(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp, "tree")
    _p, year, *_ = tree(tmp)
    goto(win, win.left, year)
    win.remember_layout("only")
    win.choose_mode("details", 0)
    assert win.left.view_mode == "details" and len(stored(win)) == 2
    win.forget_this_layout()
    assert len(stored(win)) == 1 and win.left.view_mode == "icons"          # the photo folder's tree rule again
    win.forget_this_layout()                                                # nothing of its own any more
    assert "no layout of its own" in win.status.text()
    goto(win, win.left, photos)
    win.forget_this_layout()
    assert stored(win) == [] and win.left.view_mode == "details" and win.left.layout_rule_path == ""


def test_the_label_shows_while_a_layout_is_in_force(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp)
    _p, _y, music, _o = tree(tmp)
    assert not win.layout_label.isHidden() and str(photos) in win.layout_label.toolTip()
    goto(win, win.left, music)
    assert win.layout_label.isHidden()


def test_forgetting_all_layouts_asks_and_resets_every_folder(world):
    win, d, left, right, tmp = world
    photos_layout(win, tmp)
    d.confirm_answer = False
    win.forget_all_layouts()
    assert len(stored(win)) == 1 and win.left.view_mode == "icons"
    d.confirm_answer = True
    win.forget_all_layouts()
    assert stored(win) == [] and win.left.view_mode == "details"


def test_the_home_page_and_archives_cannot_have_a_layout(world):
    win, d, left, right, tmp = world
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    win.remember_layout("tree")
    assert "cannot have a layout" in win.status.text() and stored(win) == []
    assert not has_rules_for("zip://C:/a.zip/")


def test_a_saved_layout_is_applied_when_the_program_starts(world):
    win, d, left, right, tmp = world
    photos = photos_layout(win, tmp)
    win.settings.sync()
    again = MainWindow(settings_path=str(tmp / "s.ini"), start=(str(photos), str(tmp)), dialogs=FakeDialogs())
    try:
        pump(again, lambda: again.left.path == str(photos))
        assert again.left.view_mode == "icons" and again.left.current_sort() == ("modified", True)
        assert again.right.view_mode == "details"
    finally:
        again.close()
