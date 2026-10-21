"""The tools bar can be moved: the menu bar's row, under the menu bar, or the bottom; by the menu or by dragging its grip."""
import pytest

from dossier.core import barplace

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import tools as T  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_a_drop_height_means_one_of_three_places():
    assert barplace.place_at(5, 27, 60, 460) == "menu_row"
    assert barplace.place_at(40, 27, 60, 460) == "below_menu"
    assert barplace.place_at(200, 27, 60, 460) == "below_menu"
    assert barplace.place_at(300, 27, 60, 460) == "bottom"
    assert barplace.clean("sideways") == barplace.DEFAULT and barplace.clean("bottom") == "bottom"


def where(win):
    bar = win.tools_bar
    if win.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is bar:
        return "menu_row"
    column = win.centralWidget().layout()
    i, s = column.indexOf(bar), column.indexOf(win.split)
    return "below_menu" if i == 0 else "bottom" if i == s + 1 else f"?{i}"


def test_the_bar_starts_under_the_menu_and_moves_by_the_menu_and_stays_one_bar(world):
    win, *_ = world
    win.set_tools([T.Tool("Notes", "notepad.exe", "")])
    assert where(win) == "below_menu" and win.tools_bar.place == "below_menu"
    for place in ("menu_row", "bottom", "below_menu", "menu_row"):
        win.tools_bar_place_actions[place].trigger()
        assert where(win) == place and win.tools_bar.place == place and win.tools_bar.isVisible()
        assert win.settings.value("view/tools_bar_place") == place
        assert [b.text() for b in win.tools_bar.findChildren(type(win.tools_bar.buttons[0])) if b.text() == "Notes"] == ["Notes"]


def test_the_bar_in_the_menu_row_takes_the_room_after_the_menus_and_has_no_edge_line(world):
    win, *_ = world
    win.set_tools([T.Tool("Notes", "notepad.exe", "")])
    win.set_tools_bar_place("menu_row")
    QApplication.processEvents()
    menus = win.menuBar()
    last = menus.actionGeometry(menus.actions()[-1]).right()
    assert win.tools_bar.x() >= last and win.tools_bar.geometry().right() >= menus.width() - 4
    assert "border-bottom" not in win.tools_bar.styleSheet() and "border-top" not in win.tools_bar.styleSheet()
    win.set_tools_bar_place("bottom")
    assert "border-top" in win.tools_bar.styleSheet()
    win.set_tools_bar_place("below_menu")
    assert "border-bottom" in win.tools_bar.styleSheet()


def test_switching_the_bar_off_still_hides_it_in_every_place(world):
    win, *_ = world
    win.act_tools_bar.setChecked(False)
    for place in ("menu_row", "bottom", "below_menu"):
        win.set_tools_bar_place(place)
        assert not win.tools_bar.isVisible()
    win.act_tools_bar.setChecked(True)
    assert win.tools_bar.isVisible()


def test_dragging_the_grip_shows_where_it_lands_and_dropping_moves_the_bar(world):
    win, *_ = world
    win.set_tools([T.Tool("Notes", "notepad.exe", "")])
    menu_y = win.menuBar().geometry().center().y()
    top = win.split.mapTo(win, QPoint(0, 0)).y()

    def at(y):
        return win.mapToGlobal(QPoint(300, y))
    win.tools_bar.drag_moved.emit(at(menu_y))
    assert win._strip.isVisible() and win._drop_place == "menu_row" and win._strip.y() == 0
    win.tools_bar.drag_moved.emit(at(top + win.split.height() - 10))
    assert win._drop_place == "bottom" and win._strip.y() >= top
    win.tools_bar.drag_dropped.emit(at(top + win.split.height() - 10))
    assert not win._strip.isVisible() and where(win) == "bottom"
    win.tools_bar.drag_dropped.emit(at(menu_y))
    assert where(win) == "menu_row"
    win.tools_bar.drag_dropped.emit(at(menu_y))                      # dropped where it already is: nothing changes
    assert where(win) == "menu_row"


def test_the_place_is_remembered_for_the_next_start(app, tmp_path):
    ini = str(tmp_path / "s.ini")
    (tmp_path / "a").mkdir()
    first = MainWindow(settings_path=ini, start=(str(tmp_path / "a"), str(tmp_path / "a")))
    first.set_tools_bar_place("menu_row")
    first.close()
    second = MainWindow(settings_path=ini, start=(str(tmp_path / "a"), str(tmp_path / "a")))
    second.show()
    pump(second)
    assert where(second) == "menu_row" and second.tools_bar_place_actions["menu_row"].isChecked()
    second.close()


# the function key bar and the command line ------------------------------------------------------------------------------------------------
def order_of(win):
    column = win.centralWidget().layout()
    names = {id(win.tools_bar): "tools", id(win.command_row): "command", id(win.fkeys): "fkeys", id(win.split): "panels"}
    return [names.get(id(column.itemAt(i).widget())) or "status" for i in range(column.count())]


def test_the_default_order_is_as_it_always_was(world):
    win, *_ = world
    assert order_of(win) == ["tools", "panels", "command", "fkeys", "status"]


def test_the_function_key_bar_and_the_command_line_move_above_the_panels_and_back(world):
    win, *_ = world
    win.bar_place_actions["fkeys"]["top"].trigger()
    assert order_of(win) == ["tools", "fkeys", "panels", "command", "status"] and win.settings.value("view/fkeys_place") == "top"
    win.bar_place_actions["command"]["top"].trigger()
    assert order_of(win) == ["tools", "command", "fkeys", "panels", "status"]
    win.bar_place_actions["fkeys"]["bottom"].trigger()
    assert order_of(win) == ["tools", "command", "panels", "fkeys", "status"]
    win.set_tools_bar_place("bottom")
    assert order_of(win) == ["command", "panels", "tools", "fkeys", "status"]
    win.set_tools_bar_place("menu_row")
    win.bar_place_actions["command"]["bottom"].trigger()
    assert order_of(win) == ["panels", "command", "fkeys", "status"]
    assert win.fkeys.isVisible() and win.command_row.isVisible() and win.cmdline.isVisible()


def test_dragging_the_grips_of_these_bars_moves_them_by_the_half_of_the_panels(world):
    win, *_ = world
    top = win.split.mapTo(win, QPoint(0, 0)).y()
    upper = win.mapToGlobal(QPoint(300, top + 20))
    lower = win.mapToGlobal(QPoint(300, top + win.split.height() - 20))
    win._bar_dragging("fkeys", upper)
    assert win._drop_place == "top" and win._strip.isVisible()
    win._bar_dropped("fkeys", upper)
    assert order_of(win)[:3] == ["tools", "fkeys", "panels"] and not win._strip.isVisible()
    win._bar_dropped("command", upper)
    assert order_of(win)[:4] == ["tools", "command", "fkeys", "panels"]
    win._bar_dropped("fkeys", lower)
    win._bar_dropped("command", lower)
    assert order_of(win) == ["tools", "panels", "command", "fkeys", "status"]


def test_every_movable_bar_has_a_grip_and_the_places_are_remembered(app, tmp_path):
    from dossier.gui.bar_grip import BarGrip
    ini = str(tmp_path / "s.ini")
    (tmp_path / "a").mkdir()
    first = MainWindow(settings_path=ini, start=(str(tmp_path / "a"), str(tmp_path / "a")))
    assert first.fkeys.findChildren(BarGrip) and first.command_row.findChildren(BarGrip) and first.tools_bar.findChildren(BarGrip)
    first.set_bar_place("fkeys", "top")
    first.set_bar_place("command", "top")
    first.close()
    second = MainWindow(settings_path=ini, start=(str(tmp_path / "a"), str(tmp_path / "a")))
    second.show()
    pump(second)
    assert order_of(second) == ["tools", "command", "fkeys", "panels", "status"]
    assert second.bar_place_actions["fkeys"]["top"].isChecked() and second.bar_place_actions["command"]["top"].isChecked()
    second.close()


def test_moving_another_bar_leaves_the_programs_bar_where_it_was_and_visible(world):
    win, *_ = world
    win.set_tools_bar_place("menu_row")
    win.set_bar_place("fkeys", "top")
    win.set_bar_place("command", "top")
    QApplication.processEvents()
    assert where(win) == "menu_row" and win.tools_bar.isVisible()
    win.act_tools_bar.setChecked(False)
    win.set_bar_place("fkeys", "bottom")
    assert not win.tools_bar.isVisible()
