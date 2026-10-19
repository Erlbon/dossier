"""Progress and cancel contract shared by every long operation (spec section 4).

The core never touches a widget. A worker calls ``progress(done, total)`` and checks the
``CancelToken``; the GUI hands in a callable that forwards to the main thread.
"""
from __future__ import annotations

import threading
import time
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


class RateMeter:
    """Speed and time left from a stream of ``(done, total)`` reports. The speed is measured over the last
    few seconds, so it follows the copy (a big file after many small ones) and does not jump on every report."""

    def __init__(self, window: float = 4.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._window, self._clock = window, clock
        self._points: list = []                  # (time, done)

    def add(self, done: int) -> None:
        now = self._clock()
        if self._points and done < self._points[-1][1]:
            self._points.clear()                 # progress went back (a retry): measure again
        self._points.append((now, done))
        while len(self._points) > 2 and now - self._points[1][0] > self._window:
            self._points.pop(0)

    def speed(self) -> float:
        """Bytes per second, 0 until two reports a moment apart have arrived."""
        if len(self._points) < 2:
            return 0.0
        (t0, d0), (t1, d1) = self._points[0], self._points[-1]
        return (d1 - d0) / (t1 - t0) if t1 - t0 >= 0.2 else 0.0

    def seconds_left(self, done: int, total: int) -> Optional[float]:
        rate = self.speed()
        return None if rate <= 0 or total <= done else (total - done) / rate


class SpeedLimit:
    """A shared limit in bytes per second for all copy workers together. ``wait`` is called after every chunk
    and sleeps long enough that the average stays at the limit; the sleep ends at once on cancel."""

    def __init__(self, bytes_per_second: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self.rate = max(1, int(bytes_per_second))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next = clock()

    def wait(self, nbytes: int, token: Optional[CancelToken] = None) -> None:
        with self._lock:
            now = self._clock()
            start = max(self._next, now - 0.25)        # a short burst after a pause is fine
            self._next = start + nbytes / self.rate
            delay = self._next - now                   # until the end of this chunk's slot
        while delay > 0:
            if token is not None and token.cancelled:
                raise Cancelled()
            step = min(delay, 0.1)
            if self._sleep is not None:
                self._sleep(step)
            elif token is not None:
                token._event.wait(step)
            else:
                time.sleep(step)
            delay -= step
        check(token)


def human_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    s = int(round(seconds))
    if s < 60:
        return f"{max(s, 1)} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"
