"""A log of the moments the window stopped answering (opt-in, off by default).

The window's thread calls ``beat()`` every few tens of milliseconds. A watchdog thread looks at how long ago
that was; when it is more than the threshold (200 ms) the window is stalled, and the watchdog writes down
what the window's thread is executing, now and again every half second until it answers. When it does, one
entry goes into the log file: when, how long, what the user had last done, and the stack samples.

What is recorded: times, durations, the names of the program's own functions and files, the kind of the last
input (a key's name, but never the character of a typed letter; a mouse click) and how many operations ran.
Nothing about file names or folders. The file is capped, and the user can open and delete it from Settings.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from typing import Callable, Optional

THRESHOLD = 0.2          # seconds without a heartbeat that count as a stall
SAMPLE_EVERY = 0.5       # seconds between stack samples during a stall
MAX_SAMPLES = 6
MAX_BYTES = 1_000_000
FRAMES = 14


def format_stack(frame, root: str = "") -> list:
    """The innermost frames of ``frame`` as short ``file:line function`` lines, outermost first."""
    lines = []
    for item in traceback.extract_stack(frame)[-FRAMES:]:
        name = item.filename
        if root and name.startswith(root):
            name = name[len(root):].lstrip("\\/")
        else:
            name = os.path.basename(name) if "site-packages" not in name else "..." + name.split("site-packages")[-1]
        lines.append(f"{name.replace(chr(92), '/')}:{item.lineno} {item.name}")
    return lines


class StallWatch:
    def __init__(self, path: str, *, threshold: float = THRESHOLD, interval: float = 0.05,
                 context: Callable[[], str] = lambda: "", sampler: Optional[Callable[[], list]] = None,
                 clock: Callable[[], float] = time.monotonic, max_bytes: int = MAX_BYTES,
                 now: Callable[[], str] = lambda: time.strftime("%Y-%m-%d %H:%M:%S")) -> None:
        self.path = path
        self.threshold, self.interval = threshold, interval
        self._context, self._clock, self._max, self._now = context, clock, max_bytes, now
        self._main = threading.get_ident()           # the thread that starts the watch is the one that is watched
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._sampler = sampler or (lambda: format_stack(sys._current_frames().get(self._main), root))
        self._last = clock()
        self._stalled_since: Optional[float] = None
        self._samples: list = []
        self._next_sample = 0.0
        self._context_at_start = ""
        self._resumed_at: Optional[float] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # the window's side -------------------------------------------------------------------------------------
    def beat(self) -> None:
        now = self._clock()
        with self._lock:
            if self._stalled_since is not None and self._resumed_at is None:
                self._resumed_at = now
            self._last = now

    # the watchdog's side ----------------------------------------------------------------------------------
    def tick(self) -> None:
        """One look at the window. Called by the watchdog thread; called directly by tests."""
        now = self._clock()
        with self._lock:
            last, stalled, resumed = self._last, self._stalled_since, self._resumed_at
        if stalled is None:
            if now - last > self.threshold:
                with self._lock:
                    self._stalled_since = last
                    self._resumed_at = None
                    self._samples = []
                    self._next_sample = now
                self._context_at_start = self._safe(self._context, "")
                self._take_sample(now, last)
            return
        if resumed is not None:                      # the window answered again: write the entry
            self._write(stalled, resumed)
            with self._lock:
                self._stalled_since = None
                self._resumed_at = None
            return
        if now >= self._next_sample and len(self._samples) < MAX_SAMPLES:
            self._take_sample(now, stalled)

    def _take_sample(self, now: float, since: float) -> None:
        self._samples.append((now - since, self._safe(self._sampler, [])))
        self._next_sample = now + SAMPLE_EVERY

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:                            # the log must never be a reason for trouble
            return default

    def _write(self, since: float, resumed: float) -> None:
        seconds = resumed - since
        context = self._context_at_start
        lines = [f"{self._now()}  stalled {seconds:.2f} s" + (f"  |  {context}" if context else "")]
        for age, stack in self._samples:
            lines.append(f"  {age:.1f} s into the stall, the window was in:")
            lines.extend("    " + l for l in (stack or ["(no stack)"]))
        text = chr(10).join(lines) + chr(10) + chr(10)
        try:
            self._append(text)
        except OSError:
            pass

    def _append(self, text: str) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        if size + len(text) > self._max:             # keep the newest half
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
            keep = old[len(old) // 2:]
            cut = keep.find(chr(10) + chr(10))
            keep = keep[cut + 2:] if cut >= 0 else ""
            with open(self.path, "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(keep)
        with open(self.path, "a", encoding="utf-8", newline=chr(10)) as f:
            f.write(text)

    # lifetime ---------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._last = self._clock()

        def run() -> None:
            while not self._stop.wait(self.interval):
                self.tick()

        self._thread = threading.Thread(target=run, name="dossier-stallwatch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
            self._thread = None
