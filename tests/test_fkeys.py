"""The function key bar: all twelve keys do something, the bar and the keyboard run the same command, and a Shift or Ctrl row can be
added later as another layer."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeySequence  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from dossier.gui import fkeys, icon_set  # noqa: E402
from dossier.gui.keys_help import KeysDialog, shortcut_rows  # noqa: E402
from tests.test_gui_commander import app, world  # noqa: E402,F401


def test_all_twelve_keys_are_used_once_and_every_command_exists(world):
    win, *_ = world
    keys = fkeys.keys_of(fkeys.PLAIN)
    assert [k.number for k in keys] == list(range(1, 13))
    assert len({k.label for k in keys}) == 12
    for key in keys:
        assert callable(getattr(win, key.command)), key
        assert icon_set.icon(key.icon).isNull() is False, key


def test_every_key_of_the_bar_is_bound_on_the_keyboard_to_the_same_command(world):
    """F1..F12 each have exactly one action, and it is the action of the command the button runs."""
    win, *_ = world
    bound = {}
    for action in win.actions():
        for shortcut in action.shortcuts():
            text = shortcut.toString()
            if text.startswith("F") and text[1:].isdigit():
                assert text not in bound, f"{text} is on two actions"
                bound[text] = action
    assert sorted(bound, key=lambda t: int(t[1:])) == [f"F{n}" for n in range(1, 13)]
    names = {"F1": "Keyboard Shortcuts...", "F9": "Properties", "F10": "Search...", "F11": "Full Screen", "F12": "Terminal Here"}
    for key, text in names.items():
        assert bound[key].text() == text


def test_a_layer_that_does_not_exist_falls_back_to_the_plain_keys():
    assert fkeys.keys_of("shift") is fkeys.keys_of(fkeys.PLAIN)


def test_the_keys_list_shows_the_shortcuts_of_the_menus_and_filters(world):
    win, *_ = world
    rows = shortcut_rows(win.menuBar())
    keys = {k.strip() for r in rows for k in r[0].split(",")}
    assert {"F1", "F9", "F10", "F11", "F12", "F5", "Ctrl+Z"} <= keys
    dlg = KeysDialog(rows, win)
    assert dlg.table.rowCount() == len(rows)
    dlg.filter.setText("full screen")
    shown = [r for r in range(dlg.table.rowCount()) if not dlg.table.isRowHidden(r)]
    assert shown and all("full screen" in dlg.table.item(r, 1).text().lower() for r in shown)
    dlg.deleteLater()


def test_f1_opens_the_keys_list_through_the_real_exec(world):
    from PyQt6.QtCore import QTimer
    win, *_ = world
    seen = []

    def close_it():
        box = QApplication.activeModalWidget()
        seen.append(type(box).__name__)
        box.reject()
    QTimer.singleShot(50, close_it)
    win.show_keys()
    assert seen == ["KeysDialog"]


def test_full_screen_toggles_and_puts_the_window_back(world):
    win, *_ = world
    win.show()
    assert not win.isFullScreen()
    win.toggle_full_screen()
    assert win.isFullScreen()
    win.toggle_full_screen()
    assert not win.isFullScreen()


def test_another_layer_relabels_the_bar_and_the_buttons_run_its_commands(world, monkeypatch):
    """The Shift and Ctrl rows planned for later are just more entries of LAYERS: the same buttons show them and run their commands."""
    win, *_ = world
    calls = []
    monkeypatch.setattr(win, "pack_to_zip", lambda: calls.append("pack"), raising=False)
    layers = dict(fkeys.LAYERS)
    layers["ctrl"] = (fkeys.FKey(5, "Pack", "archive", "pack_to_zip"), fkeys.FKey(6, "Sizes", "folder", "calculate_folder_sizes"))
    monkeypatch.setattr(fkeys, "LAYERS", layers)
    win.set_fkey_layer("ctrl")
    texts = [b.property("full_text") for b in win._fkey_buttons]
    assert texts[4] == "F5 Pack" and texts[5] == "F6 Sizes" and texts[0] == "" and not win._fkey_buttons[0].isEnabled()
    win._fkey_buttons[4].click()
    assert calls == ["pack"]
    win.set_fkey_layer(fkeys.PLAIN)
    assert [b.property("full_text") for b in win._fkey_buttons][4] == "F5 Copy" and win._fkey_buttons[0].isEnabled()
