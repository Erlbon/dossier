"""The command line's name completion (Ctrl+Space) and history list (Ctrl+Down)."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import completion  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def wait(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def type_into(win, text):
    win.cmdline.setFocus()
    win.cmdline.setText(text)
    win.cmdline.setCursorPosition(len(text))


def test_a_unique_name_is_completed_and_a_file_closes_its_quote(world):
    win, d, left, right, tmp = world
    (left / "My Report.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    type_into(win, "notepad My")
    win.complete_command_line()
    wait(lambda: win.cmdline.text() != "notepad My")
    assert win.cmdline.text() == 'notepad "My Report.txt"' and win.cmdline.cursorPosition() == len(win.cmdline.text())
    assert not win.cmdline.popup.isVisible()


def test_several_names_put_in_the_common_start_and_list_the_rest(world):
    win, d, left, right, tmp = world
    for n in ("alpha-one.txt", "alpha-two.txt", "beta.txt"):
        (left / n).write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    type_into(win, "cat a")
    win.complete_command_line()
    wait(lambda: win.cmdline.popup.isVisible())
    assert win.cmdline.text() == "cat alpha-"
    assert [win.cmdline.popup.item(i).text() for i in range(win.cmdline.popup.count())] == ["alpha-one.txt", "alpha-two.txt"]
    win.cmdline.popup._choose(win.cmdline.popup.item(1))
    assert win.cmdline.text() == "cat alpha-two.txt" and not win.cmdline.popup.isVisible()


def test_a_folder_is_chosen_without_closing_so_the_next_press_goes_in(world):
    win, d, left, right, tmp = world
    (left / "docs").mkdir()
    (left / "docs" / "a.txt").write_text("x")
    (left / "data").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    type_into(win, "cd do")
    win.complete_command_line()
    wait(lambda: win.cmdline.text() != "cd do")
    assert win.cmdline.text() == "cd docs" + os.sep


def test_no_match_says_so_and_a_changed_line_is_left_alone(world):
    win, d, left, right, tmp = world
    type_into(win, "cat zzz")
    win.complete_command_line()
    wait(lambda: "No name" in win.status.text())
    assert win.cmdline.text() == "cat zzz"
    (left / "abc.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    type_into(win, "cat a")
    win.complete_command_line()
    win.cmdline.setText("cat q")                                    # typed on before the answer came back
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.005)
    assert win.cmdline.text() == "cat q"


def test_programs_are_read_once_and_reused(world, monkeypatch):
    win, d, left, right, tmp = world
    calls = []
    monkeypatch.setattr(completion, "programs", lambda dirs: calls.append(1) or ["zzprog"])
    type_into(win, "zz")
    win.complete_command_line()
    wait(lambda: win.cmdline.text() == "zzprog")
    type_into(win, "zz")
    win.complete_command_line()
    wait(lambda: win.cmdline.text() == "zzprog")
    assert len(calls) == 1


def test_ctrl_space_asks_for_completion_and_ctrl_down_shows_the_history(world):
    win, d, left, right, tmp = world
    asked = []
    win.cmdline.complete_requested.connect(lambda: asked.append(1))
    QTest.keyClick(win.cmdline, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert asked == [1]
    for cmd in ("git status", "dir", "git log", "git status"):
        win.cmdline.remember(cmd)
    win.cmdline.clear()
    QTest.keyClick(win.cmdline, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    popup = win.cmdline.popup
    assert popup.isVisible() and [popup.item(i).text() for i in range(popup.count())] == ["git status", "git log", "dir"]
    popup._choose(popup.item(1))
    assert win.cmdline.text() == "git log"


def test_the_history_list_follows_what_is_typed(world):
    win, d, left, right, tmp = world
    for cmd in ("git status", "dir", "git log"):
        win.cmdline.remember(cmd)
    type_into(win, "STAT")
    assert win.cmdline.history_choices() == ["git status"]
    type_into(win, "nothing")
    assert win.cmdline.show_history() == 0
    win.show_command_history()
    assert "No earlier command" in win.status.text()


def test_typing_while_the_list_is_open_closes_it_and_reaches_the_line(world):
    win, d, left, right, tmp = world
    win.cmdline.remember("dir")
    win.cmdline.clear()
    win.cmdline.show_history()
    popup = win.cmdline.popup
    popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier, "x"))
    assert not popup.isVisible() and win.cmdline.text() == "x"
    win.cmdline.clear()
    win.cmdline.show_history()
    popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not popup.isVisible()
