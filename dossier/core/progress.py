"""Progress and cancel contract shared by every long operation (spec section 4).

The core never touches a widget. A worker calls ``progress(done, total)`` and checks the
``CancelToken``; the GUI hands in a callable that forwards to the main thread.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

# done, total (both in bytes or items; total is 0 when unknown)
ProgressFn = Callable[[int, int], None]


class Cancelled(Exception):
    """Raised inside an operation when its token was cancelled."""


class CancelToken:
    """Thread-safe flag a worker polls between small units of work."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()


def check(token: Optional[CancelToken]) -> None:
    """``token.check()`` that accepts ``None`` (no cancel wanted)."""
    if token is not None:
        token.check()
