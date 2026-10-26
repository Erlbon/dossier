"""The function key table: the built-in choices, the user's changes, and how the two are put together (no Qt)."""
from dossier.core import fkey_config as cfg


def test_the_plain_and_shift_rows_have_all_twelve_keys_and_ctrl_is_blank():
    assert sorted(cfg.DEFAULTS[cfg.PLAIN]) == list(range(1, 13)) and sorted(cfg.DEFAULTS[cfg.SHIFT]) == list(range(1, 13))
    assert cfg.DEFAULTS[cfg.CTRL] == {}
    assert cfg.DEFAULTS[cfg.PLAIN][8] == "delete" and cfg.DEFAULTS[cfg.SHIFT][8] == "delete_permanently"


def test_key_names_and_which_keys_the_table_owns():
    assert [cfg.key_text(layer, 5) for layer in cfg.LAYERS] == ["F5", "Shift+F5", "Ctrl+F5"]
    assert all(cfg.assignable(k) for k in ("F1", "F12", "Shift+F7", "Ctrl+F10"))
    assert not any(cfg.assignable(k) for k in ("Alt+F5", "Alt+Shift+F7", "Ctrl+Shift+F5", "F13", "F0", "Ctrl+F", "Delete"))


def test_what_is_saved_is_only_the_differences_and_comes_back_the_same():
    table = cfg.resolve()
    table[cfg.CTRL][5] = "pack_to_zip"
    table[cfg.PLAIN].pop(2)                                   # F2 emptied on purpose
    changes = cfg.changes_from(table)
    assert changes == {cfg.CTRL: {5: "pack_to_zip"}, cfg.PLAIN: {2: ""}}
    assert cfg.resolve(cfg.load(cfg.dump(changes))) == table
    assert cfg.dump(cfg.changes_from(cfg.resolve())) == "{}"


def test_a_key_the_user_emptied_stays_empty_and_an_unknown_command_falls_back():
    assert 2 not in cfg.resolve({cfg.PLAIN: {2: ""}})[cfg.PLAIN]
    assert cfg.resolve({cfg.PLAIN: {2: "gone"}}, known={"rename"})[cfg.PLAIN][2] == "rename"
    assert cfg.resolve({cfg.PLAIN: {2: "copy"}}, known={"rename", "copy"})[cfg.PLAIN][2] == "copy"


def test_unreadable_saved_text_is_ignored():
    for text in ("", None, "{", "[]", '{"x": {"1": "copy"}}', '{"": {"99": "copy", "a": "copy", "3": 5}}'):
        assert cfg.load(text) == {}


def test_the_bar_shows_a_row_only_when_it_has_keys():
    table = cfg.resolve()
    assert cfg.layer_for(table, False, False) == cfg.PLAIN
    assert cfg.layer_for(table, True, False) == cfg.SHIFT
    assert cfg.layer_for(table, False, True) == cfg.PLAIN               # Ctrl row empty: holding Ctrl for Ctrl+C keeps the bar as it is
    assert cfg.layer_for(table, True, True) == cfg.SHIFT
    table[cfg.CTRL][5] = "copy"
    assert cfg.layer_for(table, False, True) == cfg.CTRL and cfg.layer_for(table, True, True) == cfg.CTRL
