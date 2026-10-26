"""Which command each function key runs: the built-in table, the user's changes to it, and the two put together.

There are three rows (layers): the plain keys ``F1``..``F12``, the ``Shift+F1``.. row and the ``Ctrl+F1``.. row. A key runs a *command*, named
by the id of the window's method that does it (``"copy"``, ``"view_file"``). ``""`` means no command. Only the user's changes are saved (a
JSON text in the settings), so a later build can improve a default that the user never touched. No Qt in this module.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Optional

PLAIN, SHIFT, CTRL = "", "shift", "ctrl"
LAYERS = (PLAIN, SHIFT, CTRL)
TITLES = {PLAIN: "Plain", SHIFT: "Shift", CTRL: "Ctrl"}
PREFIX = {PLAIN: "", SHIFT: "Shift+", CTRL: "Ctrl+"}
NUMBERS = tuple(range(1, 13))

Table = Dict[str, Dict[int, str]]

DEFAULTS: Table = {
    PLAIN: {1: "show_keys", 2: "rename", 3: "view_file", 4: "edit_file", 5: "copy", 6: "move", 7: "new_folder", 8: "delete",
            9: "show_properties", 10: "search_files", 11: "toggle_full_screen", 12: "open_terminal"},
    SHIFT: {1: "check_folder_health", 2: "change_dates", 3: "new_link", 4: "new_file", 5: "compare_files", 6: "compare_folders",
            7: "move_to_quarantine", 8: "delete_permanently", 9: "show_checksums", 10: "find_duplicate_files",
            11: "calculate_folder_sizes", 12: "open_admin_terminal"},
    CTRL: {},
}

_ASSIGNABLE = re.compile(r"^(Shift\+|Ctrl\+)?F([1-9]|1[0-2])$")


def key_text(layer: str, number: int) -> str:
    """``F5``, ``Shift+F5`` or ``Ctrl+F5``: the shortcut as Qt writes it."""
    return f"{PREFIX[layer]}F{number}"


def assignable(shortcut: str) -> bool:
    """True for exactly the keys this table owns (a plain, Shift or Ctrl function key). Alt+F5, Alt+Shift+F7 and the like are fixed."""
    return bool(_ASSIGNABLE.match(shortcut))


def load(text: Optional[str]) -> Table:
    """The user's changes from their saved text: ``{layer: {number: command or ""}}``. Anything unreadable is ignored, never an error."""
    result: Table = {}
    try:
        data = json.loads(text) if text else {}
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    for layer, entries in data.items():
        if layer not in LAYERS or not isinstance(entries, dict):
            continue
        for number, command in entries.items():
            if str(number).isdigit() and int(number) in NUMBERS and isinstance(command, str):
                result.setdefault(layer, {})[int(number)] = command
    return result


def dump(changes: Table) -> str:
    return json.dumps({layer: {str(n): c for n, c in sorted(entries.items())} for layer, entries in changes.items() if entries},
                      sort_keys=True)


def resolve(changes: Optional[Table] = None, known=None) -> Table:
    """The table in force: the built-in one with the user's changes on top. A command that no longer exists (``known`` is the set of valid
    ids) falls back to the built-in choice for that key."""
    changes = changes or {}
    table: Table = {}
    for layer in LAYERS:
        row = dict(DEFAULTS[layer])
        for number, command in changes.get(layer, {}).items():
            if command == "" or known is None or command in known:
                row[number] = command
        table[layer] = {n: c for n, c in row.items() if c}
    return table


def changes_from(table: Table) -> Table:
    """What differs from the built-in table: the part worth saving. A key the user emptied is saved as ``""``."""
    changes: Table = {}
    for layer in LAYERS:
        for number in NUMBERS:
            now = table.get(layer, {}).get(number, "")
            if now != DEFAULTS[layer].get(number, ""):
                changes.setdefault(layer, {})[number] = now
    return changes


def has_keys(table: Table, layer: str) -> bool:
    return bool(table.get(layer))


def layer_for(table: Table, shift: bool, ctrl: bool) -> str:
    """The row the bar shows while those modifier keys are held. A row with no key in it is never shown, so holding Ctrl for Ctrl+C does not
    blank the bar when no Ctrl function key is set."""
    if ctrl and has_keys(table, CTRL):
        return CTRL
    if shift and has_keys(table, SHIFT):
        return SHIFT
    return PLAIN
