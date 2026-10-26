"""The function key bar: what each button shows and how it shrinks.

Which command each of F1 to F12 (and Shift+F1.., Ctrl+F1..) runs is a table (``core/fkey_config.py``: the built-in choices and the user's
changes). This module knows the commands themselves: a short name and an icon for the bar. A command is the name of a method of the main
window; the bar and the keyboard both call that method, and the keyboard shortcuts are set on the menu actions of the same command
(``keys_help.py``), so a button and its key can never do different things.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget

from ..core import fkey_config
from ..core.fkey_config import PLAIN


class FKey(NamedTuple):
    number: int
    label: str
    icon: str
    command: str


class Command(NamedTuple):
    label: str          # on the bar and in the settings list
    icon: str


# every command a function key can run; each is also a menu action registered with ``command=`` (a test keeps the two lists equal)
COMMANDS: dict = {
    "show_keys": Command("Keys", "help"),
    "rename": Command("Rename", "pencil"),
    "view_file": Command("View", "file-text"),
    "edit_file": Command("Edit", "file-code"),
    "copy": Command("Copy", "copy"),
    "move": Command("Move", "arrows-right-left"),
    "new_folder": Command("Folder", "folder-plus"),
    "new_file": Command("New file", "file"),
    "delete": Command("Delete", "trash"),
    "delete_permanently": Command("Erase", "trash"),
    "show_properties": Command("Properties", "info"),
    "search_files": Command("Search", "search"),
    "toggle_full_screen": Command("Full screen", "maximize"),
    "open_terminal": Command("Terminal", "terminal-2"),
    "open_admin_terminal": Command("Admin terminal", "terminal-2"),
    "check_folder_health": Command("Health", "file-settings"),
    "change_dates": Command("Dates", "settings"),
    "new_link": Command("Link", "link"),
    "compare_files": Command("Compare files", "arrows-right-left"),
    "compare_folders": Command("Compare folders", "folder-open"),
    "move_to_quarantine": Command("Quarantine", "archive"),
    "show_checksums": Command("Checksums", "database"),
    "verify_checksum": Command("Verify hash", "database"),
    "find_duplicate_files": Command("Duplicates", "copy"),
    "calculate_folder_sizes": Command("Sizes", "disc"),
    "refresh": Command("Refresh", "refresh"),
    "pack_to_zip": Command("Pack", "file-zip"),
    "unpack_archive": Command("Unpack", "file-zip"),
    "paste_as_new_file": Command("Paste as file", "file"),
    "swap_panels": Command("Swap panels", "arrows-right-left"),
    "show_hotlist": Command("Hotlist", "book"),
    "show_history": Command("History", "book-2"),
    "select_all": Command("Select all", "file"),
    "invert_selection": Command("Invert marks", "file"),
    "mark_by_pattern": Command("Mark pattern", "file"),
    "undo": Command("Undo", "corner-left-up"),
    "edit_folder_note": Command("Folder note", "file-text"),
    "toggle_pause": Command("Pause queue", "player-play"),
}


def keys_of(layer: str = PLAIN, table: Optional[dict] = None) -> tuple:
    """The keys of one row as ``FKey``s: only the numbers that have a command (a number without one is simply not there)."""
    table = table if table is not None else fkey_config.resolve(known=COMMANDS)
    row = table.get(layer, {})
    return tuple(FKey(n, COMMANDS[row[n]].label, COMMANDS[row[n]].icon, row[n]) for n in fkey_config.NUMBERS if row.get(n) in COMMANDS)


def button_text(key: FKey) -> str:
    return f"F{key.number} {key.label}"


def fits(button: QPushButton, width: int) -> bool:
    """True when the full text and icon of the button fit in ``width`` pixels."""
    return button.fontMetrics().horizontalAdvance(button.property("full_text") or button.text()) + button.iconSize().width() + 22 <= width


class ShrinkingKeys(QWidget):
    """The row of function key buttons. The buttons may be narrower than their text, so the window can be made narrow; when a button
    is too narrow for ``F5 Copy`` it shows ``F5`` alone (the full name is its tooltip)."""

    def set_button(self, button: QPushButton, text: str) -> None:
        """Give a button its full text (``F5 Copy``, or empty for no key); also used when the row changes."""
        button.setProperty("full_text", text)
        button.setText(text)
        button.setToolTip(text)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        button.setMinimumWidth(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relabel()

    def relabel(self) -> None:
        for b in self.findChildren(QPushButton):
            full = b.property("full_text")
            if not full:
                b.setText("")
                continue
            b.setText(full if fits(b, b.width()) else full.split(" ", 1)[0])
