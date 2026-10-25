"""The function key bar: what each of F1 to F12 does.

The keys are kept as a table per *layer*, so a Shift row or a Ctrl row can be added later as one more entry of ``LAYERS`` (with
``"shift"`` or ``"ctrl"`` as its name) without touching the bar: today only the plain layer ``""`` exists. A key is
``(number, label, icon, command)``; ``command`` is the name of a method of the main window that the bar and the keyboard both call.
The keyboard shortcuts themselves are set on the menu actions (menus.py): the bar only shows and clicks them, so a button and its key can
never do different things.
"""
from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget


class FKey(NamedTuple):
    number: int
    label: str
    icon: str
    command: str


PLAIN = ""

LAYERS: dict = {
    PLAIN: (
        FKey(1, "Keys", "help", "show_keys"),
        FKey(2, "Rename", "pencil", "rename"),
        FKey(3, "View", "file-text", "view_file"),
        FKey(4, "Edit", "file-code", "edit_file"),
        FKey(5, "Copy", "copy", "copy"),
        FKey(6, "Move", "arrows-right-left", "move"),
        FKey(7, "Folder", "folder-plus", "new_folder"),
        FKey(8, "Delete", "trash", "delete"),
        FKey(9, "Properties", "info", "show_properties"),
        FKey(10, "Search", "search", "search_files"),
        FKey(11, "Full screen", "maximize", "toggle_full_screen"),
        FKey(12, "Terminal", "terminal-2", "open_terminal"),
    ),
}


def keys_of(layer: str = PLAIN) -> tuple:
    """The keys of a layer; a layer that does not exist (yet) falls back to the plain one."""
    return LAYERS.get(layer, LAYERS[PLAIN])


def button_text(key: FKey) -> str:
    return f"F{key.number} {key.label}"


def fits(button: QPushButton, width: int) -> bool:
    """True when the full text and icon of the button fit in ``width`` pixels."""
    return button.fontMetrics().horizontalAdvance(button.property("full_text") or button.text()) + button.iconSize().width() + 22 <= width


class ShrinkingKeys(QWidget):
    """The row of function key buttons. The buttons may be narrower than their text, so the window can be made narrow; when a button
    is too narrow for ``F5 Copy`` it shows ``F5`` alone (the full name is its tooltip)."""

    def set_button(self, button: QPushButton, text: str) -> None:
        """Give a button its full text (``F5 Copy``, or empty for no key); also used when the layer changes."""
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
