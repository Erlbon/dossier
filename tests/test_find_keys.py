"""Card 59: Ctrl+F (Cmd+F on the Mac) is Search, + and - mark and unmark by pattern (the keypad's too), Ctrl+Shift+F is free."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, pump, world, key  # noqa: E402,F401

NO = Qt.KeyboardModifier.NoModifier


def _all_shortcuts(win):
    return [s.toString() for a in win.actions() for s in a.shortcuts()]


def test_ctrl_f_starts_search_and_ctrl_shift_f_is_free(world, monkeypatch):
    win, dialogs, left, *_ = world
    asked = []
    monkeypatch.setattr(win, "_ask_search", lambda dlg: asked.append(dlg) or False)
    key(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert len(asked) == 1
    keys = _all_shortcuts(win)
    assert keys.count("Ctrl+F") == 1 and "Ctrl+Shift+F" not in keys
    assert "Alt+F7" in keys                      # the old key stays


def _setup(win, dialogs, left):
    (left / "a.txt").write_text("x")
    (left / "b.log").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    dialogs.mark_answer = None
    asked = []

    def ask_mark(title, pattern):
        asked.append(title)
        return ("*.txt", __import__("dossier.core.search", fromlist=["Criteria"]).Criteria(root=""))
    dialogs.ask_mark = ask_mark
    return asked


def test_plus_and_minus_in_the_panel_mark_and_unmark_by_pattern(world):
    win, dialogs, left, *_ = world
    asked = _setup(win, dialogs, left)
    key(win, Qt.Key.Key_Plus)        # a real keyboard may add Shift; Qt's matching strips it for a character key
    assert asked == ["Mark by Pattern"] and str(left / "a.txt") in win.selection
    key(win, Qt.Key.Key_Minus)
    assert asked[-1] == "Unmark by Pattern" and str(left / "a.txt") not in win.selection
    assert win.cmdline.text() == ""


def test_keypad_plus_and_minus_work_the_same(world):
    win, dialogs, left, *_ = world
    asked = _setup(win, dialogs, left)
    key(win, Qt.Key.Key_Plus, Qt.KeyboardModifier.KeypadModifier)
    key(win, Qt.Key.Key_Minus, Qt.KeyboardModifier.KeypadModifier)
    assert asked == ["Mark by Pattern", "Unmark by Pattern"]


def test_plus_typed_in_the_command_line_stays_text(world):
    win, dialogs, left, *_ = world
    asked = _setup(win, dialogs, left)
    win.cmdline.setFocus()
    QTest.keyClicks(win.cmdline, "a+b-c")
    QApplication.processEvents()
    assert win.cmdline.text() == "a+b-c" and asked == []


def test_the_mark_menu_shows_the_new_keys(world):
    win, *_ = world
    keys = {a.text(): a.shortcut().toString() for a in win.actions()}
    assert keys["Mark by Pattern..."] == QKeySequence("+").toString()
    assert keys["Unmark by Pattern..."] == QKeySequence("-").toString()
