"""Bridge from worker threads to the Qt main thread.

``QtDispatcher`` is the ``dispatch`` callable the core asks for (``JobRunner``,
``SelectionStore``). Calling it from any thread queues the function; Qt runs it on the thread
the dispatcher lives in, which is the GUI thread when it is created there. Create exactly one,
in the main thread, after the ``QApplication`` exists, and keep a reference to it.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot


class QtDispatcher(QObject):
    _call = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Queued: the slot runs in this object's thread whatever thread emitted.
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def __call__(self, fn: Callable[[], None]) -> None:
        self._call.emit(fn)

    @pyqtSlot(object)
    def _run(self, fn) -> None:
        fn()
