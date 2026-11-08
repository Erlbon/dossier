"""The operation queue of the window: plans are worked out in the background, then run one after the other, with a
pause, a list of what waits, and the report at the end."""
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime
from dataclasses import replace
from typing import Optional

from PyQt6.QtGui import QGuiApplication

from ..core import joblog
from ..core.error_log import failed_items
from ..core.ops import ExecOptions, Kind, Plan, selection_effects
from ..core.progress import check
from ..core.platform import home_dir, taskbar_button
from ..core.queue_journal import plan_entry
from ..core.taskbar import TaskbarProgress
from ..core.worker import Job, JobState, run_plan_job
from .background import run_in_background


class OperationQueueMixin:
    """Part of ``MainWindow``."""

    @property
    def busy(self) -> bool:
        """An operation runs or is waiting, or a plan is being worked out."""
        return bool(self._jobs) or bool(self._plans)

    def _plan_in_background(self, title: str, build, then) -> None:
        """Work out a plan on a thread, so choosing many folders never freezes the window: ``build(watch)`` makes the
        plan (``watch(n)`` is its place to be cancelled and to report how far it is), ``then(plan)`` goes on, on the
        window's thread. A box with Cancel appears only when it takes a moment."""
        count = {"n": 0}

        def work(progress, cancel):
            def watch(n: int) -> None:
                check(cancel)
                count["n"] = n
                progress(n, 0)
            watch.cancel = cancel                          # for work that also reads files (skip-same by content) and stops mid-file
            return build(watch)

        run_in_background(self, self.cmd_runner, title, work, on_result=then, tracked=self._plans,
                          detail=lambda: f"{count['n']:,} items found so far", indeterminate=True, on_end=self._update_taskbar)
        self._update_taskbar()

    def _run(self, plan: Plan, *, unmark: Optional[list] = None, select: str = "", remember=None, on_done=None) -> None:
        """Queue a plan. Plans run one after the other (one disk is never fought over); the progress box of a
        plan appears when it starts, and a queued plan waits until the ones before it are done. ``remember`` (an
        ``Entry``) is kept in the journal while the operation is unfinished, when the owner switched that on."""
        journal = self.queue_journal()
        if journal is not None and remember is None:             # not asked for as a copy, move or delete (unpack, sync, the assistant...)
            remember = plan_entry(plan)
        if journal is not None and remember is not None:
            self._journal_put(journal, remember)
        else:
            journal = None
        holder: dict = {}
        shown: dict = {}

        current: dict = {}
        plan_bytes = sum(op.size for op in plan.ops
                         if op.kind is Kind.COPY or (op.kind is Kind.MOVE and not op.is_dir))

        def on_item(op, number: int, count: int) -> None:       # a worker thread: only stores the text
            current["text"] = f"{self.fs.basename(op.src or op.dst)}  ({number} of {count})"
            current["file"] = None                               # a big file says so itself (on_file_bytes)

        def on_file_bytes(op, done: int, size: int) -> None:    # a worker thread, as above: the file bar of a big file
            current["file"] = (self.fs.basename(op.src or op.dst), done, size)

        def on_wait(op, attempt: int, of: int, seconds: float, error: str) -> None:     # a worker thread, as above
            current["text"] = (f"The network is away ({error}). Trying {self.fs.basename(op.src or op.dst)} again in {seconds:.0f} s "
                               f"({attempt} of {of})")
            self.error_log.write(f"{plan.title}: the network went away, try {attempt} of {of} in {seconds:.0f} s",
                                 f"  {op.src or ''} -> {op.dst or ''}: {error}")

        def progress(done: int, total: int) -> None:
            shown.setdefault("started", time.time())               # when it really began (a queued plan waits its turn)
            if "box" not in shown:
                shown["box"] = self.dialogs.make_progress(plan.title, lambda: holder["job"].cancel() if "job" in holder else None,
                                                          self.toggle_pause)
                shown["box"].plan_bytes = plan_bytes
                shown["box"].set_paused(self.paused)
                self._active_box = shown["box"]
            shown["box"].detail = current.get("text", "")
            file = current.get("file")
            shown["box"].set_file(*file) if file else shown["box"].clear_file()
            shown["box"].update(done, total)
            self._job_progress = (done, total)
            self._update_taskbar()

        def finished(job: Job) -> None:
            if journal is not None and not self._closing:      # closing the program cancels the jobs: that is not finishing
                failed = self._failed_steps(job)
                if failed:                                       # not done: it stays, and the next start offers it again
                    self._journal_put(journal, replace(remember, note=f"{failed} failed last time"))
                else:
                    journal.remove(remember.id)
            if "box" in shown:
                shown["box"].close()
                if getattr(self, "_active_box", None) is shown["box"]:
                    self._active_box = None
            if job in self._jobs:
                self._jobs.remove(job)
            self._job = self._jobs[0] if self._jobs else None
            self._job_progress = (0, 0)
            self._update_queue_label()
            self._report_with_red_button(job, unmark)
            self._offer_job_log(job, plan.title, shown.get("started", time.time()))
            keep = select or self.active.current_name()
            self.active.set_folder(self.active.path, select=keep)
            self.other.refresh()
            if on_done is not None:                      # whoever asked for the run (the assistant's request) is told how it ended
                on_done(job)

        job = run_plan_job(self.runner, plan, self.fs, selection=self.selection, undo_log=self.undo_log,
                           on_progress=progress, on_done=finished, options=self._exec_options(on_item, on_wait, on_file_bytes),
                           **({} if self.trasher is None else {"trasher": self.trasher}))
        holder["job"] = job
        if self.paused:
            job.token.pause()
        self._jobs.append(job)
        self._job = self._jobs[0]
        self._update_queue_label()

    @staticmethod
    def _journal_put(journal, entry) -> None:
        """A plan with many steps is written on a thread; the short entry of a copy, move or delete at once."""
        journal.add_later(entry) if entry.ops else journal.add(entry)

    @staticmethod
    def _failed_steps(job: Job) -> int:
        """How many steps of a job that ended on its own failed (an error stops it too: 1). A job the owner cancelled or stopped is not
        counted: they said they were done with it."""
        result = job.result
        if result is None:
            return 1 if job.state is JobState.FAILED else 0
        return 0 if result.cancelled or result.aborted else len(result.failed)

    def toggle_pause(self) -> None:
        """Pause or resume the running operation and the ones waiting behind it."""
        self.paused = not self.paused
        for job in self._jobs:
            job.token.pause() if self.paused else job.token.resume()
        box = getattr(self, "_active_box", None)
        if box is not None:
            box.set_paused(self.paused)                # the box says it, and its button turns into Resume
        self._update_queue_label()

    def cancel_waiting(self) -> None:
        """Drop the operations that have not started; the running one carries on."""
        waiting = [j for j in self._jobs if j.state is JobState.QUEUED]
        for job in waiting:
            job.cancel()
        self._say(f"Cancelled {len(waiting)} waiting operation{'s' if len(waiting) != 1 else ''}" if waiting
                  else "No operations are waiting")

    def _init_taskbar(self) -> None:
        """The taskbar button of this window shows the queue (core/taskbar.py). Only a real Windows window has one: the offscreen
        platform of the tests gets none."""
        button = taskbar_button(self.winId) if QGuiApplication.platformName() == "windows" else None
        self.taskbar = TaskbarProgress(button)
        self._job_progress = (0, 0)                # the running operation's last report
        self._taskbar_red = False                  # a file could not be copied: the owner is being asked, or told

    def _update_taskbar(self) -> None:
        self.taskbar.show(jobs=len(self._jobs), planning=bool(self._plans), done=self._job_progress[0],
                          total=self._job_progress[1], paused=self.paused, error=self._taskbar_red)

    def _red_button(self, on: bool) -> None:
        self._taskbar_red = on
        self._update_taskbar()

    def _report_with_red_button(self, job: Job, unmark: Optional[list]) -> None:
        """The report of an operation that failed somewhere is read with the taskbar button red, so a window in the background
        says so."""
        failed = job.state is JobState.FAILED or bool(getattr(job.result, "failed", None))
        if failed:
            self._red_button(True)
        try:
            self._report(job, unmark)
        finally:
            if failed:
                self._red_button(False)

    def _update_queue_label(self) -> None:
        self._update_taskbar()
        waiting = sum(1 for j in self._jobs if j.state is JobState.QUEUED)
        parts = []
        if self._jobs:
            parts.append(("Paused: " if self.paused else "Running: ") + self._jobs[0].label)
        if waiting:
            parts.append(f"{waiting} waiting")
        self.queue_label.setText((" " + chr(0xB7) + " ").join(parts))
        self.queue_label.setVisible(bool(parts))

    def _exec_options(self, on_item=None, on_wait=None, on_file_bytes=None) -> ExecOptions:
        """The run options from Settings > Copy and Move (gui/copy_settings.py)."""
        s = self.copy_settings()
        options = ExecOptions(limit_bps=int(s["limit_mb"] * 1024 * 1024) or None, on_item=on_item, verify=s["verify"],
                              retries=s["retries"], retry_delay=s["retry_delay"], workers=s["workers"] or None,
                              network_retries=s["network_retries"], network_wait=s["network_wait"], on_wait=on_wait,
                              folder_times=s["folder_times"], on_file_bytes=on_file_bytes,
                              native_copy=s["native"], flush={"auto": None, "always": True, "never": False}[s["flush"]])
        if s["ask_on_error"]:
            skip_all = []

            def on_error(op, text: str) -> str:
                """Called on a worker thread: the question is asked on the window's thread and the worker waits."""
                if skip_all:
                    return "skip"
                if getattr(self, "_closing", False):
                    return "abort"                               # the window is going: nobody is there to answer
                answer: dict = {}
                ready = threading.Event()

                def ask() -> None:
                    try:
                        self._red_button(True)
                        name = self.fs.basename(op.src or op.dst)
                        answer["v"] = self.dialogs.ask_error(name + chr(10) * 2 + text)
                    finally:
                        self._red_button(False)
                        ready.set()

                self.dispatcher(ask)
                while not ready.wait(0.25):
                    if getattr(self, "_closing", False):          # closing waits for this thread: it must not wait for the window
                        return "abort"
                choice = answer.get("v", "skip")
                if choice == "skip_all":
                    skip_all.append(True)
                    return "skip"
                return choice

            options.on_error = on_error
        return options

    # the log of a big job (copy plan step 4): kept in memory, written only when asked ------------------------------------------------
    def _offer_job_log(self, job: Job, title: str, started: float) -> None:
        result = job.result
        finished = time.time()
        if result is None or not result.results or not joblog.is_big(result, finished - started):
            return
        self._last_job_log = (result, title, started, finished)
        self._say((self.status.text() + "  ·  " if self.status.text() else "") + "Tools > Operations > Export Log... saves every step")

    def export_job_log(self) -> None:
        """Tools > Operations > Export Log...: the last big job as a Markdown table, saved where the owner says. Nothing is kept on disk
        otherwise."""
        last = getattr(self, "_last_job_log", None)
        if last is None:
            self._say("There is no big job to log yet (a log is kept for a job of 500 steps, 1 GB or a minute and more)")
            return
        result, title, started, finished = last
        default = os.path.join(home_dir(), f"Dossier log {datetime.fromtimestamp(finished).strftime('%Y-%m-%d %H%M')}.md")
        path = self.dialogs.ask_save_path(default)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(joblog.markdown(result, title, started, finished))
        except OSError as e:
            self.dialogs.info("Export Log", f"The log could not be saved: {e.strerror or e}")
            return
        self._say(f"Saved the log of {len(result.results):,} steps to {path}")

    @staticmethod
    def _moved_to(result) -> list:
        """Where the items that were moved are now. The marks follow a moved file to its new place (so a rename keeps them), but after a
        move or a cut and paste the owner is done with those files: they must not stay marked over there."""
        return list(selection_effects(result).moved.values())

    def _report(self, job: Job, unmark: Optional[list]) -> None:
        if job.state is JobState.FAILED:
            self.error_log.write(f"{job.label}: failed", "".join(traceback.format_exception(job.error)))
            self.dialogs.info("Operation failed", str(job.error))
            return
        result = job.result
        lost = len(getattr(result, "tags_lost", []) or [])
        if result.failed:
            self.error_log.write(f"{job.label}: {len(result.failed)} of {len(result.results)} steps failed", failed_items(result))
            failed = [r.op.src for r in result.failed]
            if unmark:                           # what went well is unmarked; what failed stays marked for a retry
                self.selection.remove([u for u in unmark if not any(f.startswith(u) for f in failed)])
                self.selection.remove(self._moved_to(result))
            lines = [f"{self.fs.basename(r.op.src or r.op.dst)}: {r.error}" for r in result.failed[:10]]
            self.dialogs.info("Some items failed", "\n".join(lines))
        elif job.state is JobState.CANCELLED:
            self._say(f"Cancelled. {len(result.done)} step(s) were done; Ctrl+Z undoes them.")
        else:
            if unmark:
                self.selection.remove(unmark)
                self.selection.remove(self._moved_to(result))
            self._say("Done" if not lost else
                      f"Done. {lost} item{'s were' if lost != 1 else ' was'} copied without tags: the drive cannot store them")
