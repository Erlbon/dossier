"""The base of every dialog of the window.

A dialog is made with the window as its parent, and a Qt widget with a parent is kept alive by it: letting go of the Python name does not free
it. Without more, every dialog that was opened stayed in memory, with all its fields, until the program closed (a Properties dialog about
half a megabyte each time). ``OwnedDialog`` asks Qt to delete the dialog as soon as it has been closed (accepted, rejected or closed), so
a window that stays open for weeks does not grow with every dialog it opens.

The deletion is deferred until control is back in the event loop, so what the caller reads from the dialog right after ``exec()`` returns
(its values, its result) is still there. A dialog that is to be shown again must be made again, not kept.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog


class OwnedDialog(QDialog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
