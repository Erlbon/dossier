"""Finder's and the Linux desktops' own keys, as SECOND keys (card 51A, the owner 2026-11-18).

The function keys and today's keys stay first everywhere; a key here is added after them, so a person who knows Finder or Files finds
the key he is used to. Windows has none. Keys are written as Qt writes them: on the Mac Qt's ``Ctrl`` is the Command key (card 39A), so
``Ctrl+Backspace`` there is Cmd+Backspace. Never a Ctrl+Alt key, and never ``Ctrl+Y`` (Quick Look has it, card 45). No Qt in this module.

A command is named by the window's own id: ``delete``, ``go_up``, ``open``, ``back``, ``forward``, ``go_to_folder``, ``show_hidden``,
``properties``, ``new_folder``, ``go_root``.
"""
from __future__ import annotations

from typing import Dict, Tuple

from .platform import IS_LINUX, IS_MACOS

MAC, LINUX, WINDOWS = "mac", "linux", "windows"
SYSTEMS = (MAC, LINUX, WINDOWS)

Keys = Dict[str, Tuple[str, ...]]

_SECOND: Dict[str, Keys] = {
    MAC: {
        "delete": ("Ctrl+Backspace",),             # Cmd+Backspace: to the Trash (Root of the Drive moves to Cmd+Shift+Up, below)
        "go_up": ("Ctrl+Up",),                     # Cmd+Up: the parent folder
        "open": ("Ctrl+Down",),                    # Cmd+Down: open the item under the cursor
        "back": ("Ctrl+[",),
        "forward": ("Ctrl+]",),
        "go_to_folder": ("Ctrl+Shift+G",),         # Go to Folder: Dossier's "Edit the Path"
        "show_hidden": ("Ctrl+Shift+.",),
        "properties": ("Ctrl+I",),                 # Get Info
        "new_folder": ("Ctrl+Shift+N",),
    },
    LINUX: {
        "go_up": ("Alt+Up",),
        "back": ("Alt+Left",),                     # already the first key of Back on every system; listed so the table says it
        "forward": ("Alt+Right",),
        "new_folder": ("Ctrl+Shift+N",),
    },
    WINDOWS: {},
}

# A key that moves to another command on one system, because a second key took its place there.
_FIRST_KEY: Dict[str, Dict[str, str]] = {
    MAC: {"go_root": "Ctrl+Shift+Up"},            # was Ctrl+Backspace, which is Cmd+Backspace = Delete on the Mac
}

DEFAULT_FIRST_KEYS: Dict[str, str] = {"go_root": "Ctrl+Backspace"}


def current_system() -> str:
    """``"mac"``, ``"linux"`` or ``"windows"`` (anything else counts as Windows: no second keys)."""
    return MAC if IS_MACOS else LINUX if IS_LINUX else WINDOWS


def second_keys(system: str) -> Keys:
    """The second keys of a system, command to keys: ``second_keys("linux")["go_up"] == ("Alt+Up",)``."""
    return {command: tuple(keys) for command, keys in _SECOND.get(system, {}).items()}


def first_key(command: str, system: str) -> str:
    """The first key of a command that a second key moved on this system (``go_root``), else its usual one."""
    return _FIRST_KEY.get(system, {}).get(command, DEFAULT_FIRST_KEYS.get(command, ""))


def second_key_set(system: str) -> frozenset:
    """Every second key of the system, for the guard that leaves them to a text field that has the focus."""
    return frozenset(key for keys in _SECOND.get(system, {}).values() for key in keys)
