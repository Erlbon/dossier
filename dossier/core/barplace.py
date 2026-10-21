"""Where the tools bar (the programs bar) can sit, and which place a drop at a given height means. Qt-free.

``below_menu``  its own row under the menu bar (the original place);
``menu_row``    in the row of the menu bar, after the menus, which saves a whole row of the screen;
``bottom``      under the panels, above the command line.
"""
from __future__ import annotations

PLACES = (("menu_row", "In the Menu Bar Row"), ("below_menu", "Under the Menu Bar"), ("bottom", "At the Bottom"))
DEFAULT = "below_menu"


def clean(value) -> str:
    return value if value in dict(PLACES) else DEFAULT


def place_at(y: int, menu_bottom: int, panels_top: int, panels_bottom: int) -> str:
    """The place a bar dropped at height ``y`` (in window coordinates) goes to: the menu bar's row, the strip above the panels, or the
    lower half of the panels and everything under them."""
    if y < menu_bottom:
        return "menu_row"
    if y < panels_top + (panels_bottom - panels_top) // 2:
        return "below_menu"
    return "bottom"


# the function key bar (F2 Rename ... F8 Delete) and the command line can sit under the panels, as they always did, or above them
FKEY_PLACES = (("bottom", "At the Bottom"), ("top", "Above the Panels"))
FKEY_DEFAULT = "bottom"


def fkey_clean(value) -> str:
    return value if value in dict(FKEY_PLACES) else FKEY_DEFAULT


def half_place_at(y: int, panels_top: int, panels_bottom: int) -> str:
    """Dropped in the upper half of the panels (or above them) the bar goes above the panels, else under them."""
    return "top" if y < panels_top + (panels_bottom - panels_top) // 2 else "bottom"
