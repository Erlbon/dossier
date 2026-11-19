"""Card 57B: typing in a panel jumps to a name or goes to the command line, by a setting; Ctrl+E goes to the command line."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import typeahead  # noqa: E402
from tests.test_gui_commander import app, pump, world, key  # noqa: E402,F401

CTRL = Qt.KeyboardModifier.ControlModifier


def test_default_follows_the_system():
    assert typeahead.default_mode(mac=False, linux=False) == "command"
    assert typeahead.default_mode(mac=True, linux=False) == "jump"
    assert typeahead.default_mode(mac=False, linux=True) == "jump"


def test_find_row_is_case_blind_and_skips_none():
    names = [None, "Apple.txt", "banana", "Blue", "x"]
    assert typeahead.find_row(names, "b") == 2 and typeahead.find_row(names, "BL") == 3
    assert typeahead.find_row(names, "q") == -1 and typeahead.find_row(names, "") == -1


def _files(win, left):
    for n in ("apple.txt", "Banana.txt", "blue.txt", "my file.txt"):
        (left / n).write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.left.table.setFocus()


def _current_name(win):
    return win.left.current_name()


def test_windows_default_sends_letters_to_the_command_line(world):
    win, *_ = world
    win.typing_platform = (False, False)
    QTest.keyClicks(win.left.table, "ab")
    assert win.cmdline.text() == "ab" and win.cmdline.hasFocus()


def test_jump_mode_moves_the_cursor_and_not_the_command_line(world):
    win, _d, left, *_ = world
    win.typing_platform = (True, False)
    _files(win, left)
    QTest.keyClicks(win.left.table, "bl")
    assert _current_name(win) == "blue.txt" and win.cmdline.text() == ""
    assert win.left.table.hasFocus()


def test_a_pause_starts_the_typed_text_over(world):
    win, _d, left, *_ = world
    win.typing_platform = (False, True)
    win.typing_pause_ms = 30
    _files(win, left)
    QTest.keyClicks(win.left.table, "b")
    assert _current_name(win) == "Banana.txt"
    pump(win, lambda: win._typed == "")
    QTest.keyClicks(win.left.table, "a")
    assert _current_name(win) == "apple.txt"          # "ba" would have stayed on Banana


def test_the_setting_overrides_the_default_and_the_menu_shows_it(world):
    win, *_ = world
    win.typing_platform = (False, False)
    win.set_typing_mode("jump")
    assert win.typing_mode() == "jump" and win.typing_actions["jump"].isChecked()
    win.set_typing_mode("command")
    assert win.typing_mode() == "command" and win.typing_actions["command"].isChecked()


def test_ctrl_e_focuses_the_command_line_in_both_modes(world):
    win, *_ = world
    for mode in ("command", "jump"):
        win.set_typing_mode(mode)
        win.left.table.setFocus()
        key(win, Qt.Key.Key_E, CTRL)
        assert win.cmdline.hasFocus()
    keys = [s.toString() for a in win.actions() for s in a.shortcuts()]
    assert keys.count("Ctrl+E") == 1


def test_space_marks_and_backspace_goes_up_when_nothing_is_typed(world):
    win, _d, left, *_ = world
    win.set_typing_mode("jump")
    _files(win, left)
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    QTest.keyClick(win.left.table, Qt.Key.Key_Space)
    QApplication.processEvents()
    assert len(win.selection) == 1
    QTest.keyClick(win.left.table, Qt.Key.Key_Backspace)
    pump(win, lambda: win.left.path == str(left.parent))


def test_backspace_takes_a_letter_off_while_typing_and_space_joins_a_name(world):
    win, _d, left, *_ = world
    win.set_typing_mode("jump")
    _files(win, left)
    QTest.keyClicks(win.left.table, "bz")
    assert win._typed == "bz"
    QTest.keyClick(win.left.table, Qt.Key.Key_Backspace)
    assert win._typed == "b" and win.left.path == str(left)
    win._reset_typed()
    QTest.keyClicks(win.left.table, "my")
    QTest.keyClick(win.left.table, Qt.Key.Key_Space)
    QTest.keyClicks(win.left.table, "f")
    assert _current_name(win) == "my file.txt" and len(win.selection) == 0


def test_plus_still_marks_by_pattern_in_jump_mode(world):
    win, dialogs, left, *_ = world
    win.set_typing_mode("jump")
    asked = []
    dialogs.ask_mark = lambda title, pattern: asked.append(title) or None
    key(win, Qt.Key.Key_Plus)
    assert asked == ["Mark by Pattern"] and win.cmdline.text() == ""
