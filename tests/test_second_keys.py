"""Finder's and the Linux desktops' own keys as second keys (card 51A)."""
from __future__ import annotations

import pytest

from dossier.core import second_keys as S

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def test_the_keys_of_each_system():
    assert S.second_keys("mac") == {
        "delete": ("Ctrl+Backspace",), "go_up": ("Ctrl+Up",), "open": ("Ctrl+Down",), "back": ("Ctrl+[",), "forward": ("Ctrl+]",),
        "go_to_folder": ("Ctrl+Shift+G",), "show_hidden": ("Ctrl+Shift+.",), "properties": ("Ctrl+I",), "new_folder": ("Ctrl+Shift+N",)}
    assert S.second_keys("linux") == {"go_up": ("Alt+Up",), "back": ("Alt+Left",), "forward": ("Alt+Right",),
                                      "new_folder": ("Ctrl+Shift+N",)}
    assert S.second_keys("windows") == {} and S.second_keys("anything else") == {}
    assert S.first_key("go_root", "mac") == "Ctrl+Shift+Up"          # Cmd+Backspace is Delete there
    assert S.first_key("go_root", "linux") == S.first_key("go_root", "windows") == "Ctrl+Backspace"


@pytest.mark.parametrize("system", S.SYSTEMS)
def test_no_duplicates_no_ctrl_alt_no_quick_look_key(system):
    every = [k for keys in S.second_keys(system).values() for k in keys] + [S.first_key("go_root", system)]
    assert len(every) == len(set(every)), f"{system}: a key is used twice"
    for k in every:
        parts = k.split("+")
        assert not ({"Ctrl", "Alt"} <= set(parts)), f"{system}: {k} is a Ctrl+Alt key"
        assert "Meta" not in parts and k != "Ctrl+Y"


def test_the_current_system_is_one_of_three():
    assert S.current_system() in S.SYSTEMS


# the window --------------------------------------------------------------------------------------------------------------------
def shortcuts(act):
    return [s.toString(QKeySequence.SequenceFormat.PortableText) for s in act.shortcuts()]


def test_linux_binds_alt_up_beside_backspace(world):
    win, *_ = world
    win.apply_second_keys("linux")
    assert shortcuts(win.act_parent) == ["Alt+Up"]
    assert shortcuts(win.act_back) == ["Alt+Left"] and shortcuts(win.act_forward) == ["Alt+Right"]
    assert shortcuts(win.act_mkdir) == ["F7", "Ctrl+Shift+N"]
    assert shortcuts(win.act_root) == ["Ctrl+Backspace"]
    from dossier.gui.menus import command_keys
    assert command_keys(win.act_parent).startswith("Backspace, ")        # the panel's own key stays first in the hint


def test_mac_binds_finders_keys_and_moves_root_of_the_drive(world):
    win, *_ = world
    win.apply_second_keys("mac")
    assert shortcuts(win.act_delete) == ["Del", "F8", "Ctrl+Backspace"]
    assert shortcuts(win.act_root) == ["Ctrl+Shift+Up"]
    assert shortcuts(win.act_parent) == ["Ctrl+Up"] and shortcuts(win.act_open) == ["Ctrl+Down"]
    assert shortcuts(win.act_back) == ["Alt+Left", "Ctrl+["] and shortcuts(win.act_forward) == ["Alt+Right", "Ctrl+]"]
    assert shortcuts(win.act_edit_path) == ["Ctrl+L", "Ctrl+Shift+G"]
    assert shortcuts(win.act_show_hidden) == ["Ctrl+H", "Ctrl+Shift+."]
    assert shortcuts(win.act_properties)[0] == "Alt+Return" and shortcuts(win.act_properties)[-1] == "Ctrl+I"
    assert shortcuts(win.act_mkdir)[0] == "F7" and shortcuts(win.act_mkdir)[-1] == "Ctrl+Shift+N"


def test_windows_has_none_and_switching_back_takes_the_keys_off(world):
    win, *_ = world
    win.apply_second_keys("mac")
    win.apply_second_keys("windows")
    assert shortcuts(win.act_delete) == ["Del", "F8"] and shortcuts(win.act_root) == ["Ctrl+Backspace"]
    assert shortcuts(win.act_parent) == [] and shortcuts(win.act_open) == []
    assert shortcuts(win.act_back) == ["Alt+Left"] and shortcuts(win.act_show_hidden) == ["Ctrl+H"]


@pytest.mark.parametrize("system", S.SYSTEMS)
def test_no_key_is_bound_to_two_actions_and_none_is_ctrl_alt(world, system):
    win, *_ = world
    win.apply_second_keys(system)
    seen = {}
    for act in win.actions():
        for k in shortcuts(act):
            assert k not in seen or seen[k] is act, f"{system}: {k} is on {seen[k].text()!r} and {act.text()!r}"
            seen[k] = act
            parts = k.split("+")
            assert not ({"Ctrl", "Alt"} <= set(parts)), f"{system}: {k} is a Ctrl+Alt key"
    assert "Ctrl+Y" not in seen


def test_a_second_key_does_the_command(world):
    win, dialogs, left, *_ = world
    sub = left / "sub"
    sub.mkdir()
    (sub / "a.txt").write_text("a")
    win.left.set_folder(str(sub))
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.apply_second_keys("linux")
    key(win, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    pump(win, lambda: win.left.path == str(left))
    assert win.left.path == str(left)


def test_the_command_line_keeps_cmd_backspace_for_its_text(world):
    """On the Mac, Cmd+Backspace in the command line edits the text; it must not delete the marked files."""
    win, dialogs, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.apply_second_keys("mac")
    dialogs.confirm_answer = False
    win.cmdline.setFocus()
    win.cmdline.setText("keep this")
    win.cmdline.setCursorPosition(len("keep this"))
    QApplication.processEvents()
    QTest.keyClick(win.cmdline, Qt.Key.Key_Backspace, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert dialogs.confirms == [] and (left / "a.txt").exists()
    assert win.cmdline.text() != "keep this"                       # the field took the key
    win.cmdline.clearFocus()
    win.active.table.setCurrentIndex(win.active.model.index(win.active.model.row_of("a.txt"), 0))
    win.active.view.setFocus()
    key(win, Qt.Key.Key_Backspace, Qt.KeyboardModifier.ControlModifier)       # in the panel it is Delete
    pump(win, lambda: bool(dialogs.confirms) or not (left / "a.txt").exists())      # the plan is made on a thread
    assert dialogs.confirms != [] or not (left / "a.txt").exists()
