"""Spring-loaded folders (card 62A): holding a drag over a folder, a tab or a drive for about a second opens it, so the drop can go deeper.

One timer for the whole panel. Hovering a new target restarts it; leaving, dropping or hovering nothing cancels it. A target that has
already sprung does not spring again until the pointer has left it, so a folder that fails to open is not tried again every second.

If nothing is dropped in the panel, it goes back to where it was before the first spring. When the drag began in Dossier, the end of the
drag is known exactly: ``drag_finished()`` is called when ``QDrag.exec()`` returns (a drop in a panel has called ``dropped()`` before
that). A drag from another program gives the target no such signal; there the panel goes back ``LEAVE_MS`` after the pointer has left
it for good (Esc, a drop outside the panel or the window all end in a leave event, a drop in the panel does not).
"""
from __future__ import annotations

import weakref
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer


class SpringTimer(QObject):
    DELAY_MS = 1000          # tests shorten it
    LEAVE_MS = 600           # a drag from another program: how long the pointer may be away before the panel goes back
    internal = False         # a drag that began in Dossier is running: its end is told by drag_finished()
    _all: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, enabled: Callable[[], bool], on_revert: Optional[Callable[[], None]] = None, parent=None) -> None:
        super().__init__(parent)
        self._enabled = enabled
        self._on_revert = on_revert
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._leave = QTimer(self)
        self._leave.setSingleShot(True)
        self._leave.timeout.connect(self.revert)
        self._key = None
        self._action: Optional[Callable[[], None]] = None
        self.armed = False                # something has sprung in this drag: a revert has something to undo
        SpringTimer._all.add(self)

    def hover(self, key, action: Callable[[], None]) -> None:
        """The pointer is over the target ``key`` with a drag: run ``action`` if it stays for the delay."""
        self._leave.stop()
        if key is None or not self._enabled():
            self.cancel()
            return
        if key == self._key:
            return                        # the same target keeps its timer (or has already sprung)
        self._key, self._action = key, action
        self._timer.start(self.DELAY_MS)

    def cancel(self) -> None:
        self._timer.stop()
        self._key = None
        self._action = None

    def pending(self) -> bool:
        return self._timer.isActive()

    def over(self) -> None:
        """The drag is still over this panel (a move, even where nothing springs)."""
        self._leave.stop()

    def left(self) -> None:
        """The drag left the panel's widgets. For a drag from another program this starts the way back."""
        self.cancel()
        if self.armed and not SpringTimer.internal:
            self._leave.start(self.LEAVE_MS)

    def dropped(self) -> None:
        """Files were dropped in this panel: it stays where it sprang to."""
        self.cancel()
        self._leave.stop()
        self.armed = False

    def revert(self) -> None:
        """The drag ended without a drop here: back to where the panel was."""
        self.cancel()
        self._leave.stop()
        if self.armed:
            self.armed = False
            if self._on_revert is not None:
                self._on_revert()

    @classmethod
    def drag_finished(cls) -> None:
        """A drag that began in Dossier is over (``QDrag.exec()`` returned): every panel that sprang and got no drop goes back."""
        for timer in list(cls._all):
            try:
                timer.revert()
            except RuntimeError:                  # the panel's window is gone (its Qt object was deleted)
                cls._all.discard(timer)

    def _fire(self) -> None:
        action, self._action = self._action, None       # the key stays: no second spring over the same target
        if action is not None and self._enabled():
            action()
