"""Auto refresh: a panel follows changes made by another program, with separate switches for this computer's drives and for network drives; and the
Refresh button in each panel's bar."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QToolButton  # noqa: E402

from dossier.gui import auto_refresh as ar  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def wait(until, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(ar, "DEBOUNCE_MS", 40)
    monkeypatch.setattr(ar, "RETRY_MS", 60)
    monkeypatch.setattr(ar, "MIN_GAP", 0.1)


def names(panel):
    return [panel.model.entry_at(r).name for r in range(panel.model.entry_count())]


# the switches ---------------------------------------------------------------------------------------------------------------------------
def test_local_is_on_by_default_and_network_is_off(world, monkeypatch):
    win, d, left, right, tmp = world
    monkeypatch.setattr(ar, "DEFAULT_LOCAL", True)                       # the real default (the test housekeeping turns it off)
    win.settings.remove(ar.KEY_LOCAL)
    win.settings.remove(ar.KEY_NETWORK)
    assert win.auto_refresh_on(False) is True and win.auto_refresh_on(True) is False
    assert ar.DEFAULT_NETWORK is False


def test_the_switches_are_in_the_settings_menu_and_are_remembered(world):
    win, d, left, right, tmp = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    sub = next(a.menu() for a in menus["Settings"].actions() if a.text() == "Auto Refresh")
    assert [a.text() for a in sub.actions()] == ["Drives of This Computer", "Network Drives (can be slow)"]
    assert not win.act_auto_local.isChecked() and not win.act_auto_network.isChecked()           # off in the tests
    win.act_auto_local.setChecked(True)
    win.act_auto_network.setChecked(True)
    assert win.settings.value(ar.KEY_LOCAL) == "true" and win.settings.value(ar.KEY_NETWORK) == "true"
    assert "Auto refresh for network drives is on" in win.status.text()
    win.act_auto_network.setChecked(False)
    assert win.auto_refresh_on(False) and not win.auto_refresh_on(True)


# what is watched ------------------------------------------------------------------------------------------------------------------------
def test_the_folders_the_panels_show_are_watched_and_only_those(world):
    win, d, left, right, tmp = world
    assert win.watched() == []                                           # off: nothing is watched
    win.set_auto_refresh(False, True)
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(left)), os.path.normcase(str(right))}
    (left / "sub").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("sub") >= 0)
    win.left.set_folder(str(left / "sub"))
    pump(win, lambda: win.left.path == str(left / "sub") and not win.left.loading)
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(left / "sub")), os.path.normcase(str(right))}      # it follows the panel
    win.left.go_home()
    pump(win, lambda: win.left.is_home)
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(right))}                                           # the Home page is not a folder
    win.set_auto_refresh(False, False)
    assert win.watched() == []


def test_a_network_folder_is_watched_only_when_the_network_switch_is_on(world, monkeypatch):
    win, d, left, right, tmp = world
    monkeypatch.setattr(ar, "is_network_path", lambda path: os.path.normcase(path) == os.path.normcase(str(left)))
    win.set_auto_refresh(False, True)
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(right))}        # the left folder is "on the network": not watched
    win.set_auto_refresh(True, True)
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(left)), os.path.normcase(str(right))}
    win.set_auto_refresh(False, False)                                                           # local off: only the network one is left
    assert {os.path.normcase(p) for p in win.watched()} == {os.path.normcase(str(left))}


# reacting -------------------------------------------------------------------------------------------------------------------------------
def test_a_file_made_by_another_program_shows_up_by_itself(world, quick):
    win, d, left, right, tmp = world
    win.set_auto_refresh(False, True)
    assert "later.txt" not in names(win.left)
    (left / "later.txt").write_text("made elsewhere")
    assert wait(lambda: "later.txt" in names(win.left))
    (right / "other.txt").write_text("and here")
    assert wait(lambda: "other.txt" in names(win.right))
    (left / "later.txt").unlink()
    assert wait(lambda: "later.txt" not in names(win.left))


def test_nothing_happens_by_itself_when_the_switch_is_off(world, quick):
    win, d, left, right, tmp = world
    (left / "quiet.txt").write_text("x")
    time.sleep(0.3)
    QApplication.processEvents()
    assert "quiet.txt" not in names(win.left)


def test_the_cursor_the_marks_and_the_scroll_stay_where_they_were(world, quick):
    win, d, left, right, tmp = world
    for i in range(300):
        (left / f"file{i:03}.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 300)
    win.set_auto_refresh(False, True)
    table = win.left.table
    table.setCurrentIndex(table.model().index(150, 0))
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum() // 2)
    win.selection.add([str(left / "file200.txt")])
    keep = (win.left.current_name(), table.verticalScrollBar().value())
    (left / "zzz-new.txt").write_text("new")
    assert wait(lambda: "zzz-new.txt" in names(win.left))
    assert (win.left.current_name(), table.verticalScrollBar().value()) == keep
    assert [os.path.basename(p) for p in win.left.marked_here()] == ["file200.txt"]


def test_a_busy_panel_is_left_alone_and_gets_its_refresh_afterwards(world, quick, monkeypatch):
    win, d, left, right, tmp = world
    win.set_auto_refresh(False, True)
    busy = {"on": True}
    monkeypatch.setattr(win, "_panel_busy", lambda panel: busy["on"])
    (left / "during.txt").write_text("x")
    time.sleep(0.4)
    QApplication.processEvents()
    assert "during.txt" not in names(win.left)                           # skipped while busy (a name being edited, an operation running...)
    busy["on"] = False
    assert wait(lambda: "during.txt" in names(win.left))                  # the change was not forgotten


def test_a_burst_of_changes_is_one_or_two_refreshes_not_one_for_each(world, monkeypatch):
    win, d, left, right, tmp = world
    monkeypatch.setattr(ar, "DEBOUNCE_MS", 150)
    monkeypatch.setattr(ar, "MIN_GAP", 0.5)
    win.set_auto_refresh(False, True)
    count = []
    real = type(win.left).refresh
    monkeypatch.setattr(type(win.left), "refresh", lambda self: (count.append(1), real(self))[1])
    for i in range(25):
        (left / f"burst{i}.txt").write_text("x")
        QApplication.processEvents()
        time.sleep(0.01)
    assert wait(lambda: "burst24.txt" in names(win.left))
    time.sleep(0.8)
    QApplication.processEvents()
    assert 1 <= len(count) <= 3, len(count)


def test_a_panel_that_moved_on_forgets_the_old_change(world, quick):
    win, d, left, right, tmp = world
    win.set_auto_refresh(False, True)
    (tmp / "elsewhere").mkdir()
    win.left.set_folder(str(tmp / "elsewhere"))
    pump(win, lambda: win.left.path == str(tmp / "elsewhere") and not win.left.loading)
    (left / "old.txt").write_text("x")                                   # the folder the panel left: no longer watched, no refresh
    time.sleep(0.3)
    QApplication.processEvents()
    assert win.auto_refresh_on(False) and os.path.normcase(str(left)) not in {os.path.normcase(p) for p in win.watched()}


# the Refresh button ---------------------------------------------------------------------------------------------------------------------
def test_the_refresh_button_sits_next_to_sum_and_flatten(world):
    win, d, left, right, tmp = world
    layout = win.left.tool_group.layout()
    items = [layout.itemAt(i).widget() for i in range(layout.count())]
    sizes, flat, refresh = win.left.sizes_button, win.left.flatten_button, win.left.refresh_button
    assert items.index(flat) == items.index(sizes) + 1 and items.index(refresh) == items.index(flat) + 1
    assert layout.spacing() == 0 and win.left.bar.layout().indexOf(win.left.tool_group) > win.left.bar.layout().indexOf(win.left.free)   # close together, after the free space
    assert isinstance(refresh, QToolButton) and refresh.text() == chr(0x21BB) and "Refresh" in refresh.toolTip()
    assert refresh.objectName() == "refreshbtn" and win.right.refresh_button is not refresh                  # each panel has its own


def test_the_refresh_button_reads_the_folder_again(world):
    win, d, left, right, tmp = world
    (left / "fresh.txt").write_text("x")
    assert "fresh.txt" not in names(win.left)
    win.left.refresh_button.click()
    pump(win, lambda: "fresh.txt" in names(win.left))
    (right / "other.txt").write_text("x")
    win.left.refresh_button.click()
    pump(win, lambda: not win.left.loading)
    assert "other.txt" not in names(win.right)                              # the other panel was not asked
