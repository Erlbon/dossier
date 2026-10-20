"""Background jobs for the Qt-free core (plan step 6).

A job runs on a worker thread. Everything the front end hears about it (progress, the end)
goes through one ``dispatch`` callable, so the GUI passes a dispatcher that queues onto its own
thread and no callback ever touches a widget from a worker. Without a dispatcher callbacks run
inline in the worker thread, which is what the Qt-free tests and a future command line want.

One worker thread by default: file operations run one after the other, so two jobs never fight
over the same folders.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Callable, Optional

from .ops import Plan, execute, selection_effects
from .progress import CancelToken, ProgressFn
from .selection import Dispatcher, SelectionStore
from .undo_log import UndoLog
from .vfs import FileSystem

log = logging.getLogger(__name__)


def run_inline(fn: Callable[[], None]) -> None:
    fn()


class JobState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    def __init__(self, label: str) -> None:
        self.label = label
        self.state = JobState.QUEUED
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self._token = CancelToken()
        self._finished = threading.Event()

    def cancel(self) -> None:
        self._token.cancel()

    @property
    def token(self) -> CancelToken:
        return self._token

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the work has ended (callbacks may still be waiting in the dispatcher)."""
        return self._finished.wait(timeout)


class JobRunner:
    def __init__(self, dispatch: Dispatcher = run_inline, *, workers: int = 1, progress_interval: float = 0.05):
        self._dispatch = dispatch
        self._interval = progress_interval
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dossier-job")

    def submit(
        self,
        label: str,
        fn: Callable[[ProgressFn, CancelToken], Any],
        *,
        on_progress: Optional[ProgressFn] = None,
        on_done: Optional[Callable[[Job], None]] = None,
    ) -> Job:
        """Run ``fn(progress, cancel)`` in the background. Returns at once."""
        job = Job(label)
        self._pool.submit(self._run, job, fn, on_progress, on_done)
        return job

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=cancel_futures)

    # internals -----------------------------------------------------------------------------
    def _post(self, fn: Callable[[], None]) -> None:
        def guarded() -> None:
            try:
                fn()
            except Exception:  # a broken callback must not break the runner or the next job
                log.exception("job callback failed")

        self._dispatch(guarded)

    def _run(self, job: Job, fn, on_progress, on_done) -> None:
        job.state = JobState.RUNNING
        last = [0.0]

        def progress(done: int, total: int) -> None:
            if on_progress is None:
                return
            now = time.monotonic()
            final = total > 0 and done >= total
            if final or now - last[0] >= self._interval:
                last[0] = now
                self._post(lambda: on_progress(done, total))

        try:
            job.result = fn(progress, job.token)
            job.state = JobState.CANCELLED if job.token.cancelled else JobState.DONE
        except BaseException as e:   # reported through the job, never raised into the pool
            job.error = e
            job.state = JobState.CANCELLED if job.token.cancelled and not isinstance(e, Exception) else JobState.FAILED
            log.debug("job %s failed", job.label, exc_info=True)
        finally:
            if on_done is not None:
                self._post(lambda: on_done(job))
            job._finished.set()


def run_plan_job(
    runner: JobRunner,
    plan: Plan,
    fs: FileSystem,
    *,
    selection: Optional[SelectionStore] = None,
    undo_log: Optional[UndoLog] = None,
    on_progress: Optional[ProgressFn] = None,
    on_done: Optional[Callable[[Job], None]] = None,
    trasher=None,
    options=None,
) -> Job:
    """Run a plan in the background. When it ends, on the dispatcher thread, the undo journal gets
    its entry and the selection follows the moved and deleted items; then ``on_done`` is called.
    A cancelled run keeps (and journals) whatever it had already done."""
    kwargs = {} if trasher is None else {"trasher": trasher}
    if options is not None:
        kwargs["options"] = options

    def work(progress: ProgressFn, cancel: CancelToken):
        return execute(plan, fs, progress=progress, cancel=cancel, **kwargs)

    def finished(job: Job) -> None:
        result = job.result
        if result is not None:
            if undo_log is not None and result.action is not None:
                undo_log.push(result.action)
            if selection is not None:
                effects = selection_effects(result)
                selection.remap(effects.moved)
                selection.remove(effects.removed)
        if on_done is not None:
            on_done(job)

    return runner.submit(plan.title, work, on_progress=on_progress, on_done=finished)
