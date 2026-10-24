"""Quick filter, folder history, the hotlist, and opening a folder in the other panel."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from dossier.gui import panel as panel_module  # noqa: E402
from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401

CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier


def make_folders(tmp, *names_):
    out = []
    for n in names_:
        d = tmp / n
        d.mkdir(exist_ok=True)
        out.append(str(d))
    return out


def go(win, path):
    win.left.set_folder(path)
    pump(win, lambda: win.left.path == path)


# folder history ---------------------------------------------------------------------------------------------
def test_back_and_forward_walk_through_the_folders_a_tab_has_shown(world):
    win, _d, left, right, tmp = world
    a, b, c = make_folders(tmp, "ha", "hb", "hc")
    for p in (a, b, c):
        go(win, p)
    assert win.left.history_back() and win.left.path == b
    assert win.left.history_back() and win.left.path == a
    assert win.left.history_forward() and win.left.path == b
    assert win.left.history_entries()[0][1] == c                       # newest first, and going back changed nothing
    n = len(win.left.history_entries())
    win.left.history_back()
    win.left.history_forward()
    assert len(win.left.history_entries()) == n


def test_a_new_place_cuts_off_what_was_forward(world):
    win, _d, left, right, tmp = world
    a, b, c, d = make_folders(tmp, "ha", "hb", "hc", "hd")
    for p in (a, b, c):
        go(win, p)
    win.left.history_back()
    go(win, d)
    assert not win.left.history_forward()                              # c is gone from the future
    assert [p for _i, p in win.left.history_entries()][:3] == [d, b, a]


def test_back_and_forward_at_the_ends_do_nothing_and_a_refresh_adds_nothing(world):
    win, _d, left, right, tmp = world
    (a,) = make_folders(tmp, "ha")
    go(win, a)
    count = len(win.left.history_entries())
    win.left.refresh()
    pump(win, lambda: True)
    assert len(win.left.history_entries()) == count
    while win.left.history_back():
        pass
    assert not win.left.history_back()
    while win.left.history_forward():
        pass
    assert not win.left.history_forward()


def test_each_tab_has_its_own_history_and_switching_tabs_adds_none(world):
    win, _d, left, right, tmp = world
    a, b = make_folders(tmp, "ha", "hb")
    go(win, a)
    win.left.new_tab(b)
    pump(win, lambda: win.left.path == b)
    first_tab_history = None
    win.left.tabs.setCurrentIndex(0)
    pump(win, lambda: win.left.path == a)
    first_tab_history = [p for _i, p in win.left.history_entries()]
    assert b not in first_tab_history and a in first_tab_history
    win.left.tabs.setCurrentIndex(1)
    pump(win, lambda: win.left.path == b)
    second = [p for _i, p in win.left.history_entries()]
    assert second == [b] and win.left.history_position == 0
    win.left.tabs.setCurrentIndex(0)
    pump(win, lambda: win.left.path == a)
    assert [p for _i, p in win.left.history_entries()] == first_tab_history   # unchanged by the visits


def test_the_history_is_capped(world, monkeypatch):
    win, _d, left, right, tmp = world
    monkeypatch.setattr(panel_module, "HISTORY_MAX", 4)
    folders = make_folders(tmp, *[f"h{i}" for i in range(8)])
    for p in folders:
        go(win, p)
    entries = win.left.history_entries()
    assert len(entries) == 4 and entries[0][1] == folders[-1] and win.left.history_position == 3


def test_a_folder_that_cannot_be_opened_keeps_the_position(world):
    win, _d, left, right, tmp = world
    a, b = make_folders(tmp, "ha", "hb")
    go(win, a)
    go(win, b)
    import shutil
    shutil.rmtree(a)
    position = win.left.history_position
    assert not win.left.history_back()
    assert win.left.history_position == position and win.left.path == b


def test_alt_arrows_and_the_mouse_buttons_go_back_and_forward(world):
    win, _d, left, right, tmp = world
    a, b = make_folders(tmp, "ha", "hb")
    go(win, a)
    go(win, b)
    key(win, Qt.Key.Key_Left, ALT)
    pump(win, lambda: win.left.path == a)
    key(win, Qt.Key.Key_Right, ALT)
    pump(win, lambda: win.left.path == b)
    vp = win.left.table.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier, vp.rect().center())
    pump(win, lambda: win.left.path == a)
    QTest.mouseClick(vp, Qt.MouseButton.ForwardButton, Qt.KeyboardModifier.NoModifier, vp.rect().center())
    pump(win, lambda: win.left.path == b)


def test_the_history_menu_lists_newest_first_ticks_the_current_and_goes_there(world):
    win, _d, left, right, tmp = world
    a, b, c = make_folders(tmp, "ha", "hb", "hc")
    for p in (a, b, c):
        go(win, p)
    win.left.history_back()
    pump(win, lambda: win.left.path == b)
    menu = win.build_history_menu()
    actions = [x for x in menu.actions()]
    assert [x.data() for x in actions[:3]] == [c, b, a]
    assert [x.isChecked() for x in actions[:3]] == [False, True, False]
    actions[2].trigger()
    pump(win, lambda: win.left.path == a)
    key(win, Qt.Key.Key_Down, ALT)                                       # the shortcut opens the same list
    assert win._history_menu is not None and win._history_menu.isVisible()
    win._history_menu.close()


# quick filter ----------------------------------------------------------------------------------------------
def fill(win, left):
    for n in ("Holiday.jpg", "holiday.png", "notes.txt", "Report.txt", "readme.md"):
        (left / n).write_text(n)
    (left / "photos").mkdir(exist_ok=True)
    win.left.refresh()


def test_ctrl_s_opens_the_filter_and_typing_narrows_the_list_by_part_of_a_name(world):
    win, _d, left, *_ = world
    fill(win, left)
    key(win, Qt.Key.Key_S, CTRL)
    assert win.left.filter_edit.isVisible() and win.left.filter_edit.hasFocus()
    QTest.keyClicks(win.left.filter_edit, "HOLI")
    assert names(win.left) == ["..", "holiday.png", "Holiday.jpg"] or sorted(names(win.left)) == sorted(["..", "Holiday.jpg", "holiday.png"])
    assert "Filter: 2 of 6 shown" in win.status.text()
    assert win.left.model.counts() == (2, 6)


def test_a_pattern_with_wildcards_is_matched_on_the_whole_name(world):
    win, _d, left, *_ = world
    fill(win, left)
    win.left.start_filter()
    win.left.filter_edit.setText("*.txt")
    assert sorted(names(win.left)) == sorted(["..", "notes.txt", "Report.txt"])
    win.left.filter_edit.setText("r?port*")
    assert sorted(names(win.left)) == sorted(["..", "Report.txt"])


def test_escape_clears_the_filter_and_hides_the_field(world):
    win, _d, left, *_ = world
    fill(win, left)
    win.left.start_filter()
    win.left.filter_edit.setText("txt")
    QTest.keyClick(win.left.filter_edit, Qt.Key.Key_Escape)
    assert not win.left.filter_edit.isVisible() and not win.left.filter_active
    assert len(names(win.left)) == 7                                      # everything is back, with the up row
    assert win.left.table.hasFocus()


def test_enter_returns_to_the_list_and_keeps_the_filter_and_escape_there_clears_it_before_the_marks(world):
    win, _d, left, *_ = world
    fill(win, left)
    key(win, Qt.Key.Key_Space)                                            # a mark somewhere
    win.left.start_filter()
    win.left.filter_edit.setText("txt")
    QTest.keyClick(win.left.filter_edit, Qt.Key.Key_Return)
    assert win.left.table.hasFocus() and win.left.filter_active and win.left.filter_edit.isVisible()
    key(win, Qt.Key.Key_Escape)                                           # first Esc: the filter
    assert not win.left.filter_active and len(win.selection) == 1
    key(win, Qt.Key.Key_Escape)                                           # second Esc: the marks
    assert len(win.selection) == 0


def test_a_refresh_keeps_the_filter_and_moving_to_another_folder_drops_it(world):
    win, _d, left, *_ = world
    fill(win, left)
    win.left.start_filter()
    win.left.filter_edit.setText("txt")
    win.left.refresh()
    pump(win, lambda: True)
    assert win.left.filter_active and sorted(names(win.left)) == sorted(["..", "notes.txt", "Report.txt"])
    win.left.set_folder(str(left / "photos"))
    pump(win, lambda: win.left.path == str(left / "photos"))
    assert not win.left.filter_active and not win.left.filter_edit.isVisible()
    win.left.set_folder(str(left))
    pump(win, lambda: win.left.path == str(left))
    assert len(names(win.left)) == 7


def test_marks_stay_on_filtered_out_items_and_commands_work_on_what_is_shown(world):
    win, dialogs, left, right, _t = world
    fill(win, left)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("notes.txt"), 0))
    key(win, Qt.Key.Key_Space)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("readme.md"), 0))
    key(win, Qt.Key.Key_Space)
    win.left.start_filter()
    win.left.filter_edit.setText("txt")
    assert len(win.selection) == 2                                        # readme.md is hidden but still marked
    assert [p.rsplit("\\", 1)[-1] for p in win.left.targets()] == ["notes.txt"]
    win.left.clear_filter()
    assert len(win.left.targets()) == 2


def test_the_filter_works_with_sorting_and_an_empty_result_leaves_the_up_row(world):
    win, _d, left, *_ = world
    fill(win, left)
    win.left.start_filter()
    win.left.filter_edit.setText("zzz")
    assert names(win.left) == [".."]
    win.left.filter_edit.setText("o")
    win.left.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    shown = [n for n in names(win.left) if n != ".."]
    assert shown[0] == "photos" and shown[1:] == sorted(shown[1:], key=str.lower, reverse=True)


def test_the_home_page_has_nothing_to_filter(world):
    win, *_ = world
    win.left.go_home()
    pump(win, lambda: win.left.is_home)
    win.left.start_filter()
    assert not win.left.filter_edit.isVisible() and "Home page" in win.status.text()


# hotlist ---------------------------------------------------------------------------------------------------
def test_the_hotlist_lists_pinned_folders_with_digits_and_goes_to_the_one_picked(world):
    win, _d, left, right, tmp = world
    a, b = make_folders(tmp, "pa", "pb")
    for p in (a, b):
        go(win, p)
        win.pin_folder()
    go(win, str(left))
    menu = win.build_hotlist_menu()
    texts = [x.text() for x in menu.actions() if not x.isSeparator()]
    assert texts[0].startswith("&1") and "pa" in texts[0] and texts[1].startswith("&2") and "pb" in texts[1]
    assert texts[-1].startswith("Pin This Folder")
    [x for x in menu.actions() if "pb" in x.text()][0].trigger()
    pump(win, lambda: win.left.path == b)


def test_an_empty_hotlist_says_so_and_ctrl_b_opens_the_list(world):
    win, *_ = world
    menu = win.build_hotlist_menu()
    assert menu.actions()[0].text() == "No pinned folders yet" and not menu.actions()[0].isEnabled()
    key(win, Qt.Key.Key_B, CTRL)
    assert win._hotlist_menu.isVisible()
    win._hotlist_menu.close()


def test_a_pinned_folder_that_is_gone_is_reported_not_crashed_on(world):
    win, _d, left, right, tmp = world
    (a,) = make_folders(tmp, "pa")
    go(win, a)
    win.pin_folder()
    go(win, str(left))
    import shutil
    shutil.rmtree(a)
    win.build_hotlist_menu().actions()[0].trigger()
    assert "Cannot open" in win.status.text() and win.left.path == str(left)


# the other panel ----------------------------------------------------------------------------------------------
def test_ctrl_right_and_ctrl_left_open_the_folder_under_the_cursor_in_the_other_panel(world):
    win, _d, left, right, tmp = world
    (left / "sub").mkdir()
    (left / "file.txt").write_text("x")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("sub"), 0))
    key(win, Qt.Key.Key_Right, CTRL)
    pump(win, lambda: win.right.path == str(left / "sub"))
    assert win.active is win.left                                         # the focus stays where it was
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("file.txt"), 0))
    key(win, Qt.Key.Key_Left, CTRL)                                       # a file: the folder it is in
    pump(win, lambda: win.right.path == str(left))


def test_the_other_panel_can_be_made_to_show_this_folder(world):
    win, _d, left, right, tmp = world
    win.same_in_other_panel()
    pump(win, lambda: win.right.path == str(left))
    key(win, Qt.Key.Key_Tab)
    (right / "deep").mkdir()
    win.right.set_folder(str(right / "deep"))
    pump(win, lambda: win.right.path == str(right / "deep"))
    key(win, Qt.Key.Key_O, CTRL | Qt.KeyboardModifier.ShiftModifier)
    pump(win, lambda: win.left.path == str(right / "deep"))


def test_the_new_menu_has_its_entries(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert [a.text() for a in menus["Go"].actions() if not a.isSeparator()] == [
        "Back", "Forward", "Folder History...", "Hotlist...", "Home Page", "Edit the Path", "Pin Folder to Home Page", "Quarantine Folder",
        "All Files Below This Folder", "Open Folder in the Other Panel", "Other Panel Shows This Folder", "Swap Panels"]
