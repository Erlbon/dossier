"""What the program's taskbar button shows while the operation queue works: the green fill of the running copy or move, a
moving bar while a plan is worked out, yellow while paused, red while a file could not be copied, nothing when the queue is
empty. Qt-free: the button itself is ``platform.taskbar_button`` (Windows), or anything with ``set(state, done, total)``."""
from __future__ import annotations

from typing import Optional, Protocol

NONE = "none"
INDETERMINATE = "indeterminate"
NORMAL = "normal"
PAUSED = "paused"
ERROR = "error"

STEPS = 1000                  # the fill is sent in thousandths: a 50 GB copy does not call the system for every block


class Button(Protocol):
    def set(self, state: str, done: int, total: int) -> None: ...


def taskbar_look(*, jobs: int, planning: bool, done: int, total: int, paused: bool, error: bool) -> tuple:
    """``(state, done, total)`` for the button. ``jobs`` counts the running and waiting operations, ``done``/``total`` is the
    running one's progress (0/0 before its first report). Paused and red with no progress yet show a full bar, so the colour
    is seen at all."""
    if not jobs and not planning and not error:
        return NONE, 0, 0
    known = total > 0
    fill = (min(done, total) * STEPS // total) if known else STEPS
    if error:
        return ERROR, fill, STEPS
    if paused and jobs:
        return PAUSED, fill, STEPS
    if jobs and known:
        return NORMAL, fill, STEPS
    return INDETERMINATE, 0, 0


class TaskbarProgress:
    """Sends the look to the button, and only when it changed."""

    def __init__(self, button: Optional[Button]) -> None:
        self._button = button
        self._shown: tuple = (NONE, 0, 0)

    @property
    def shown(self) -> tuple:
        return self._shown

    def show(self, **queue) -> None:
        look = taskbar_look(**queue)
        if look == self._shown:
            return
        self._shown = look
        if self._button is not None:
            self._button.set(*look)
