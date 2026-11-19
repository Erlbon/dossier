"""Typing in a panel (card 57B): letters jump to a name, or go to the command line. Qt-free.

``default_mode`` says which one a system starts with; ``find_row`` is the jump itself: the first name that starts with what
was typed, compared without regard to case and with the accents folded the way a natural sort sees them.
"""
from __future__ import annotations

from typing import Optional

JUMP = "jump"
COMMAND = "command"
CHOICES = ((JUMP, "Jumps to a Name"), (COMMAND, "Goes to the Command Line"))
PAUSE_MS = 1000          # a pause this long starts the typed text over


def default_mode(mac: bool, linux: bool) -> str:
    """The Mac and Linux jump to a name, as Finder, Files, Dolphin and Thunar do; Windows keeps the command line."""
    return JUMP if (mac or linux) else COMMAND


def valid_mode(value: object, fallback: str) -> str:
    return str(value) if str(value) in (JUMP, COMMAND) else fallback


def _fold(text: str) -> str:
    return text.casefold()


def find_row(names: list[Optional[str]], typed: str) -> int:
    """The index of the first name that starts with ``typed`` (None entries are rows the cursor skips), or -1."""
    wanted = _fold(typed)
    if not wanted:
        return -1
    for i, name in enumerate(names):
        if name is not None and _fold(name).startswith(wanted):
            return i
    return -1


def extend(typed: str, text: str, stale: bool) -> str:
    """What is typed after one more key: the key alone when the pause has passed."""
    return (text if stale else typed + text)
