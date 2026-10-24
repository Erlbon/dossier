"""The base of every dialog of the window.

A dialog is made with the window as its parent, and a Qt widget with a parent is kept alive by it: letting go of the Python name does not free
it. Without more, every dialog that was opened stayed in memory, with all its fields, until the program closed (a Properties dialog about
half a megabyte each time). ``OwnedDialog`` deletes the dialog once it has been closed, so a window that stays open for weeks does not grow
with every dialog it opens.

How, and why not simply ``WA_DeleteOnClose``: ``QDialog.exec()`` deletes a dialog with that flag *the moment it returns*, before the caller
can read what the user typed (its fields, its answer): every caller would fail. So the flag is not used. ``exec()`` here runs the dialog and
then asks Qt to delete it with ``deleteLater()``, which waits until control is back in the event loop that the caller itself runs in: what the
caller reads right after ``exec()`` returns is still there, and a nested loop the caller starts (a follow-up dialog) does not delete it
early. A dialog that is shown without ``exec()`` (a window that stays open next to the main one) is deleted when it is closed. A dialog that
is to be shown again must be made again, not kept.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog


class OwnedDialog(QDialog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._running = False
        self.finished.connect(self._closed)

    def exec(self) -> int:
        self._running = True
        try:
            return super().exec()
        finally:
            self._running = False
            self.deleteLater()                     # after the caller has read the answer: at its own loop level, never in a nested one

    def _closed(self, _result: int) -> None:
        if not self._running:                      # shown without exec(): nobody will call deleteLater for it
            self.deleteLater()
