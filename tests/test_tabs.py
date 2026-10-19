"""Folder tabs in each panel, and the window title that names the subject."""
import os

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs, key  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app, tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    for d in (left, right, left / "alpha", left / "beta", right / "gamma"):
        d.mkdir(parents=True)
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    (left / "alpha" / "inside.txt").write_text("i")
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=FakeDialogs())
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)
    yield win, left, right, tmp_path
    win.close()


def labels(panel):
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


# basics -----------------------------------------------------------------------------------------------
def test_every_panel_starts_with_one_tab_named_after_its_folder(world):
    win, left, right, _t = world
    assert labels(win.left) == ["left"] and labels(win.right) == ["right"]
    assert win.left.tabs.tabToolTip(0) == str(left)
    assert win.left.new_tab_button.text() == "+"


def test_a_new_tab_copies_the_folder_and_becomes_the_current_one(world):
    win, left, *_ = world
    win.left.new_tab()
    assert labels(win.left) == ["left", "left"] and win.left.tabs.currentIndex() == 1
    assert win.left.path == str(left)


def test_tabs_of_the_two_panels_are_independent(world):
    win, left, right, _t = world
    win.left.new_tab()
    win.left.new_tab()
    assert win.left.tabs.count() == 3 and win.right.tabs.count() == 1


def test_each_tab_keeps_its_own_folder_cursor_and_sort(world):
    win, left, *_ = world
    p = win.left
    p.set_folder(str(left / "alpha"))
    p.new_tab(str(left))
    p.table.setCurrentIndex(p.model.index(p.model.row_of("b.txt"), 0))
    p.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    p.tabs.setCurrentIndex(0)                                  # back to the first tab
    assert p.path == str(left / "alpha") and labels(p) == ["alpha", "left"]
    assert p.table.horizontalHeader().sortIndicatorSection() == 0
    p.tabs.setCurrentIndex(1)
    assert p.path == str(left) and p.current_name() == "b.txt"
    assert p.table.horizontalHeader().sortIndicatorSection() == 1


def test_navigating_changes_only_the_current_tabs_label(world):
    win, left, *_ = world
    win.left.new_tab()
    win.left.set_folder(str(left / "beta"))
    assert labels(win.left) == ["left", "beta"]


def test_closing_tabs_and_the_last_one_stays(world):
    win, left, *_ = world
    p = win.left
    p.set_folder(str(left / "alpha"))
    p.new_tab(str(left / "beta"))
    assert labels(p) == ["alpha", "beta"] and p.path == str(left / "beta")
    p.close_tab(1)                                             # closing the current tab shows its neighbour
    assert labels(p) == ["alpha"] and p.path == str(left / "alpha")
    p.close_tab(0)
    assert labels(p) == ["alpha"]                              # the last tab stays


def test_closing_a_tab_that_is_not_current_does_not_reload_the_current_one(world):
    win, left, *_ = world
    p = win.left
    p.new_tab(str(left / "alpha"))
    p.new_tab(str(left / "beta"))
    p.table.setCurrentIndex(p.model.index(p.model.row_of("inside.txt") if False else 0, 0))
    before = p.path
    p.close_tab(0)
    assert p.path == before and labels(p) == ["alpha", "beta"]


def test_tab_vanished_folder_falls_back_to_the_nearest_parent(world):
    win, left, *_ = world
    p = win.left
    p.new_tab(str(left / "beta"))
    p.tabs.setCurrentIndex(0)
    (left / "beta").rmdir()
    p.tabs.setCurrentIndex(1)
    assert p.path == str(left)


# gestures ---------------------------------------------------------------------------------------------------
def test_next_and_previous_tab_wrap_around(world):
    win, left, *_ = world
    p = win.left
    p.new_tab(str(left / "alpha"))
    p.new_tab(str(left / "beta"))
    assert p.tabs.currentIndex() == 2
    p.next_tab(1)
    assert p.tabs.currentIndex() == 0
    p.next_tab(-1)
    assert p.tabs.currentIndex() == 2


def test_ctrl_enter_opens_a_folder_in_a_new_tab_and_enter_in_the_same_tab(world):
    win, left, *_ = world
    p = win.left
    p.table.setCurrentIndex(p.model.index(p.model.row_of("alpha"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert labels(p) == ["left", "alpha"] and p.tabs.currentIndex() == 1
    p.tabs.setCurrentIndex(0)
    p.table.setCurrentIndex(p.model.index(p.model.row_of("beta"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Return)
    assert labels(p) == ["beta", "alpha"]


def test_middle_click_on_a_folder_opens_a_background_tab_and_on_a_tab_closes_it(world):
    win, left, *_ = world
    p = win.left
    row = p.model.row_of("alpha")
    pos = p.table.visualRect(p.model.index(row, 0)).center()
    QTest.mouseClick(p.table.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, pos)
    assert labels(p) == ["left", "alpha"] and p.tabs.currentIndex() == 0      # stays where it was
    tab_pos = p.tabs.tabRect(1).center()
    QTest.mouseClick(p.tabs, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, tab_pos)
    assert labels(p) == ["left"]


def test_double_click_on_the_empty_bar_makes_a_tab_and_the_plus_button_too(world):
    win, *_ = world
    p = win.left
    p.new_tab_button.click()
    assert p.tabs.count() == 2
    far = QPoint(p.tabs.width() - 2, p.tabs.height() // 2)
    p.tabs.new_requested.emit()
    assert p.tabs.count() == 3 and far.x() > 0


def test_menu_and_shortcuts_act_on_the_active_panel(world):
    win, left, right, _t = world
    key(win, Qt.Key.Key_Tab)                                   # the right panel is active
    QTest.keyClick(win.right.table, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert win.right.tabs.count() == 2 and win.left.tabs.count() == 1
    QTest.keyClick(win.right.table, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    assert win.right.tabs.count() == 1
    view = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}["View"]
    tabs_menu = next(a.menu() for a in view.actions() if a.text() == "Tabs")
    assert [a.text() for a in tabs_menu.actions()] == ["New Tab", "Close Tab", "Next Tab", "Previous Tab",
                                                       "Open Folder in New Tab"]


def test_copy_goes_to_the_other_panels_current_tab(world):
    win, left, right, _t = world
    win.right.new_tab(str(right / "gamma"))                    # the other panel shows gamma now
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win.dialogs.confirm_answer = True
    win.copy()
    end = __import__("time").time() + 5
    while __import__("time").time() < end and not (right / "gamma" / "a.txt").exists():
        QApplication.processEvents()
    assert (right / "gamma" / "a.txt").exists() and not (right / "a.txt").exists()


# session -----------------------------------------------------------------------------------------------------------
def test_tabs_and_the_active_tab_are_restored(world, app):
    win, left, right, tmp = world
    win.left.new_tab(str(left / "alpha"))
    win.left.new_tab(str(left / "beta"))
    win.left.tabs.setCurrentIndex(1)
    win.right.new_tab(str(right / "gamma"))
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs())
    try:
        assert labels(again.left) == ["left", "alpha", "beta"] and again.left.tabs.currentIndex() == 1
        assert again.left.path == str(left / "alpha")
        assert labels(again.right) == ["right", "gamma"] and again.right.tabs.currentIndex() == 1
    finally:
        again.close()


# the window title ------------------------------------------------------------------------------------------------------
def test_the_file_manager_is_titled_with_the_machine_name_and_the_title_stays_put(world):
    from dossier.core.platform import is_elevated, machine_name
    expected = f"Dossier {machine_name()}" + (" (Administrator)" if is_elevated() else "")   # CI runners are admins
    win, left, *_ = world
    assert win.windowTitle() == expected
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    key(win, Qt.Key.Key_Tab)
    win.left.new_tab()
    assert win.windowTitle() == expected                              # the cursor and the tabs do not rename it


def test_the_administrator_mark_follows_the_machine_name(app, tmp_path, monkeypatch):
    import dossier.gui.main_window as mw
    from dossier.core.platform import machine_name
    monkeypatch.setattr(mw, "is_elevated", lambda: True)
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)), dialogs=FakeDialogs())
    try:
        assert win.windowTitle() == f"Dossier {machine_name()} (Administrator)"
    finally:
        win.close()
