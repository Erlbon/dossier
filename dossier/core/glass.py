"""The see-through look of the picture viewer: three modes, how much of the desktop shows through, and what to fall back to.

* ``frosted``: the desktop behind the window is blurred (Windows' own blur effect) under a dark layer.
* ``dim``: the same dark layer, with the desktop showing through sharp.
* ``solid``: no transparency at all.

The viewer asks for a mode (the default is ``dim``) and gets the best one the computer can do: frosted falls back to dim, dim to solid.
A remote desktop session, or a system without window transparency, ends in solid. The level is how much of the desktop shows through,
in percent: 0 is solid, 50 is half. No Qt in this module; the Windows calls are in ``platform.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SOLID, DIM, FROSTED = "solid", "dim", "frosted"
MODES = (FROSTED, DIM, SOLID)
DEFAULT_MODE = DIM                                       # the owner found Windows' acrylic blur a flat grey blob; sharp is closest to Picasa
DEFAULT_LEVEL = {FROSTED: 65, DIM: 50, SOLID: 0}          # percent of the desktop that shows through
MAX_LEVEL = 90                                           # never fully clear: the picture and the bar must stay readable
_ORDER = {FROSTED: (FROSTED, DIM, SOLID), DIM: (DIM, SOLID), SOLID: (SOLID,)}


@dataclass(frozen=True)
class Capabilities:
    transparent: bool = False        # a window can be see-through here
    blur: bool = False               # and the desktop behind it can be blurred


def detect() -> Capabilities:
    """What this computer can do, asked of the system (a remote desktop session or a system without a compositor: nothing)."""
    from . import platform
    if platform.is_remote_session():
        return Capabilities(False, False)
    return Capabilities(True, platform.IS_WINDOWS)


def resolve(requested: str, caps: Capabilities) -> str:
    """The best mode at or below ``requested`` that ``caps`` allows."""
    for mode in _ORDER.get(requested, _ORDER[DEFAULT_MODE]):
        if mode == FROSTED and caps.transparent and caps.blur:
            return FROSTED
        if mode == DIM and caps.transparent:
            return DIM
        if mode == SOLID:
            return SOLID
    return SOLID


def parse(text: str) -> tuple:
    """``(mode or None, level or None)`` from what the owner typed: a mode name (``frosted``, ``dim``, ``solid``), a number 0 to 100 (how
    much shows through; 0 is solid), or both written ``frosted:60``. Raises ``ValueError`` with a sentence for anything else."""
    mode: Optional[str] = None
    level: Optional[int] = None
    for part in str(text).lower().replace(",", ":").split(":"):
        part = part.strip()
        if not part:
            continue
        if part in MODES:
            mode = part
        elif part.isdigit():
            level = max(0, min(100, int(part)))
        else:
            raise ValueError(f"'{part}' is not a glass setting: use frosted, dim, solid, a number from 0 to 100, or frosted:60")
    if level == 0:
        mode = SOLID
    return mode, level


def level_for(mode: str, level: Optional[int]) -> int:
    """How much shows through in ``mode``: the given level (0 to ``MAX_LEVEL``), else the mode's own default. Solid shows nothing."""
    if mode == SOLID:
        return 0
    return DEFAULT_LEVEL[mode] if level is None else max(1, min(MAX_LEVEL, level))


def alpha_for(mode: str, level: Optional[int] = None) -> int:
    """The opacity (0 to 255) of the dark layer drawn over the desktop."""
    return round(255 * (100 - level_for(mode, level)) / 100)
