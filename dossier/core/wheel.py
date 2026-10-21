"""What the mouse wheel does in the picture viewer: one action for the plain wheel, one for Ctrl+wheel and one for Shift+wheel.

The owner can change them around (Settings > Mouse Wheel...); the choice is kept as three short words. Qt-free: the viewer looks the
action up and carries it out.
"""
from __future__ import annotations

ACTIONS = (("scroll_step", "Scroll the picture, then the next or previous one"), ("step", "Next or previous picture"),
           ("zoom", "Zoom in and out"), ("scroll", "Scroll up and down"), ("scroll_sideways", "Scroll left and right"),
           ("none", "Nothing"))
KEYS = (("plain", "Wheel"), ("ctrl", "Ctrl + wheel"), ("shift", "Shift + wheel"))
DEFAULTS = {"plain": "scroll_step", "ctrl": "zoom", "shift": "scroll"}


def clean(values) -> dict:
    """A complete table from whatever was stored: a missing or unknown choice falls back to the default."""
    known = {key for key, _label in ACTIONS}
    values = values if isinstance(values, dict) else {}
    return {key: (values.get(key) if values.get(key) in known else DEFAULTS[key]) for key, _label in KEYS}


def key_for(ctrl: bool, shift: bool) -> str:
    """Which of the three the pressed keys make (Ctrl wins when both are down)."""
    return "ctrl" if ctrl else "shift" if shift else "plain"
