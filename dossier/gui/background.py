"""One way to run work on a thread with a box that appears only when it takes a moment, and a Cancel.

Making a plan, adding up folder sizes and unpacking an archive member each did this by hand: a holder for the job, a box
made on the first progress report, closing it, the cancelled and failed cases. They are one function now.
"""
from __future__ import annotations

import threading
from typing import Callable

from ..core.worker import Job, JobState


def run_in_background(window, runner, title: str, work, *, on_result: Callable, tracked: list,
                      detail: Callable[[], str] = lambda: "", plan_bytes=None, indeterminate: bool = False,
                      partial_on_cancel: bool = False, failed_title: str = "") -> Job:
    """Run ``work(progress, cancel)`` on ``runner``. Progress reports go to a box (made on the first one, so a quick job
    shows none) whose second line is ``detail()``. When the job ends, on the window's thread: the box is closed, the job
    leaves ``tracked``, and ``on_result(result)`` is called, unless it was cancelled (the window says "Cancelled", unless
    ``partial_on_cancel``: then what was done is handed over) or failed (the error is shown)."""
    holder: dict = {}
    shown: dict = {}
    lock = threading.Lock()
    ended = {"yes": False}                     # a job can end before submit() has returned (callbacks run inline in tests)

    def on_progress(done: int, total: int) -> None:
        if "box" not in shown:
            shown["box"] = window.dialogs.make_progress(title, lambda: holder["job"].cancel() if "job" in holder else None)
            if plan_bytes is not None:
                shown["box"].plan_bytes = plan_bytes
            if indeterminate:
                make_indeterminate = getattr(shown["box"], "indeterminate", None)
                if make_indeterminate is not None:
                    make_indeterminate()
        shown["box"].detail = detail()
        shown["box"].update(done, total)

    def finished(job: Job) -> None:
        if "box" in shown:
            shown["box"].close()
        with lock:
            ended["yes"] = True
            if job in tracked:
                tracked.remove(job)
        if job.token.cancelled and not partial_on_cancel:
            window._say("Cancelled")
        elif job.state is JobState.FAILED:
            window.dialogs.info(failed_title or title, str(job.error))
        else:
            on_result(job.result)

    job = runner.submit(title, work, on_progress=on_progress, on_done=finished)
    holder["job"] = job
    with lock:
        if not ended["yes"]:
            tracked.append(job)
    return job
