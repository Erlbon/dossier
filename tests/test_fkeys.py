"""The function key bar and keys: three rows (plain, Shift, Ctrl), every key bound once from the table, the bar and the keyboard run the same
command, the rows can be changed in Settings > Function Keys, and the choice is saved."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import fkey_config as cfg  # noqa: E402
from dossier.gui import fkeys, icon_set  # noqa: E402
from dossier.gui.fkey_settings import FunctionKeysDialog  # noqa: E402
from dossier.gui.keys_help import KeysDialog, shortcut_rows  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def bound_keys(win) -> dict:
    """Every function key (plain, Shift or Ctrl) that is on an action of the window, with its action; fails on a key used twice."""
    bound = {}
    for action in win.actions():
        for shortcut in action.shortcuts():
            text = shortcut.toString()
            if cfg.assignable(text):
                assert text not in bound, f"{text} is on two actions"
                bound[text] = action
    return bound


def test_every_command_a_key_can_run_has_a_menu_action_and_a_method_and_an_icon(world):
    win, *_ = world
    assert set(win._command_actions) == set(fkeys.COMMANDS)
    for command, meta in fkeys.COMMANDS.items():
        assert callable(getattr(win, command)), command
        assert icon_set.icon(meta.icon).isNull() is False, (command, meta.icon)
    for layer in cfg.LAYERS:
        assert set(cfg.DEFAULTS[layer].values()) <= set(fkeys.COMMANDS)


def test_every_key_of_the_table_is_bound_once_to_the_action_of_its_command(world):
    win, *_ = world
    expected = {cfg.key_text(layer, n): command for layer, row in win._fkey_table.items() for n, command in row.items()}
    bound = bound_keys(win)
    assert set(bound) == set(expected) and len(expected) == 24
    for key, command in expected.items():
        assert bound[key] is win._command_actions[command][0], key


def test_the_bar_shows_the_plain_row_and_the_shift_row_while_shift_is_held(world):
    win, *_ = world
    assert [b.property("full_text") for b in win._fkey_buttons] == ["F1 Keys", "F2 Rename", "F3 View", "F4 Edit", "F5 Copy", "F6 Move", "F7 Folder",
                                                                    "F8 Delete", "F9 Properties", "F10 Search", "F11 Full screen", "F12 Terminal"]
    win.show_modifier_row(True, False)
    assert [b.property("full_text") for b in win._fkey_buttons][:4] == ["F1 Health", "F2 Dates", "F3 Link", "F4 New file"]
    assert win._fkey_buttons[7].property("full_text") == "F8 Erase" and all(b.isEnabled() for b in win._fkey_buttons)
    win.show_modifier_row(False, True)                                    # the Ctrl row is empty: the bar stays as the plain row
    assert win._fkey_buttons[0].property("full_text") == "F1 Keys"
    win.show_modifier_row(False, False)
    assert win._fkey_layer == cfg.PLAIN


def test_holding_and_letting_go_of_shift_swaps_the_row_through_the_real_key_events(world):
    win, *_ = world
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    if not win.isActiveWindow():
        pytest.skip("the offscreen platform cannot activate the window")
    shift_down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
    shift_up = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win.left.view, shift_down)
    assert win._fkey_layer == cfg.SHIFT
    QApplication.sendEvent(win.left.view, shift_up)
    assert win._fkey_layer == cfg.PLAIN


def test_a_button_runs_the_command_of_the_row_shown(world, monkeypatch):
    win, *_ = world
    calls = []
    monkeypatch.setattr(win, "check_folder_health", lambda: calls.append("health"))
    win.show_modifier_row(True, False)
    win._fkey_buttons[0].click()
    assert calls == ["health"]


def test_changing_the_keys_rebinds_the_keyboard_redraws_the_bar_and_is_saved(world):
    win, *_ = world
    table = cfg.resolve()
    table[cfg.CTRL][5] = "pack_to_zip"                                    # a new Ctrl key
    table[cfg.PLAIN][2] = "refresh"                                       # F2 now refreshes
    table[cfg.PLAIN].pop(9)                                               # F9 emptied
    win.set_fkey_table(table)
    bound = bound_keys(win)
    assert bound["Ctrl+F5"] is win._command_actions["pack_to_zip"][0] and bound["F2"] is win._command_actions["refresh"][0]
    assert "F9" not in bound and not win._command_actions["rename"][0].shortcuts()
    assert "Alt+Return" in [s.toString() for s in win._command_actions["show_properties"][0].shortcuts()]       # its fixed key stays
    assert win._fkey_buttons[1].property("full_text") == "F2 Refresh" and win._fkey_buttons[8].property("full_text") == ""
    win.show_modifier_row(False, True)
    assert win._fkey_buttons[4].property("full_text") == "F5 Pack"        # a Ctrl row with a key is shown while Ctrl is held
    saved = cfg.load(str(win.settings.value("fkeys/config")))
    assert saved == {cfg.CTRL: {5: "pack_to_zip"}, cfg.PLAIN: {2: "refresh", 9: ""}}
    win.set_fkey_table(cfg.resolve())                                     # back to the built-in table: nothing is saved
    assert win.settings.value("fkeys/config") == "{}" and "Ctrl+F5" not in bound_keys(win)


def test_the_settings_page_shows_the_table_and_hands_back_the_choice(world):
    win, *_ = world
    dlg = FunctionKeysDialog(win._fkey_table, win)
    assert dlg.tabs.count() == 3 and [dlg.tabs.tabText(i) for i in range(3)] == ["Plain", "Shift", "Ctrl"]
    assert dlg.table() == win._fkey_table
    dlg.combos[(cfg.CTRL, 3)].setCurrentIndex(dlg.combos[(cfg.CTRL, 3)].findData("refresh"))
    dlg.combos[(cfg.PLAIN, 1)].setCurrentIndex(0)                         # "(none)"
    chosen = dlg.table()
    assert chosen[cfg.CTRL] == {3: "refresh"} and 1 not in chosen[cfg.PLAIN]
    dlg._restore([cfg.PLAIN])
    assert dlg.table()[cfg.PLAIN][1] == "show_keys" and dlg.table()[cfg.CTRL] == {3: "refresh"}
    dlg._restore(list(cfg.LAYERS))
    assert dlg.table() == win._fkey_table
    dlg.deleteLater()


def test_the_settings_page_through_a_real_exec_saves_what_was_chosen(world):
    win, *_ = world

    def choose():
        box = QApplication.activeModalWidget()
        assert isinstance(box, FunctionKeysDialog)
        box.combos[(cfg.CTRL, 1)].setCurrentIndex(box.combos[(cfg.CTRL, 1)].findData("refresh"))
        box.accept()
    QTimer.singleShot(50, choose)
    win.open_function_keys_settings()
    assert win._fkey_table[cfg.CTRL] == {1: "refresh"} and "Ctrl+F1" in bound_keys(win)
    assert cfg.load(str(win.settings.value("fkeys/config"))) == {cfg.CTRL: {1: "refresh"}}


def test_new_file_makes_an_empty_text_file_in_the_active_folder(world):
    win, d, left, right, tmp = world
    d.texts.append("note")
    win.new_file()
    pump(win, lambda: any(p.name.startswith("note") for p in left.iterdir()))
    made = [p for p in left.iterdir() if p.name.startswith("note")]
    assert len(made) == 1 and made[0].read_bytes() == b""


def test_the_keys_list_shows_the_shortcuts_of_the_menus_and_filters(world):
    win, *_ = world
    rows = shortcut_rows(win.menuBar())
    keys = {k.strip() for r in rows for k in r[0].split(",")}
    assert {"F1", "F9", "F10", "F11", "F12", "Shift+F8", "Shift+F1", "F5", "Ctrl+Z", "Alt+Return"} <= keys
    dlg = KeysDialog(rows, win)
    assert dlg.table.rowCount() == len(rows)
    dlg.filter.setText("full screen")
    shown = [r for r in range(dlg.table.rowCount()) if not dlg.table.isRowHidden(r)]
    assert shown and all("full screen" in dlg.table.item(r, 1).text().lower() for r in shown)
    dlg.deleteLater()


def test_f1_opens_the_keys_list_through_the_real_exec(world):
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
