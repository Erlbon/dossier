"""The operation queue of the window: plans are worked out in the background, then run one after the other, with a
pause, a list of what waits, and the report at the end."""
from __future__ import annotations

import threading
from typing import Optional

from ..core.ops import ExecOptions, Kind, Plan
from ..core.progress import check
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
            return build(watch)

        run_in_background(self, self.cmd_runner, title, work, on_result=then, tracked=self._plans,
                          detail=lambda: f"{count['n']:,} items found so far", indeterminate=True)

    def _run(self, plan: Plan, *, unmark: Optional[list] = None, select: str = "", remember=None) -> None:
        """Queue a plan. Plans run one after the other (one disk is never fought over); the progress box of a
        plan appears when it starts, and a queued plan waits until the ones before it are done. ``remember`` (an
        ``Entry``) is kept in the journal while the operation is unfinished, when the owner switched that on."""
        journal = self.queue_journal() if remember is not None else None
        if journal is not None:
            journal.add(remember)
        holder: dict = {}
        shown: dict = {}

        current: dict = {}
        plan_bytes = sum(op.size for op in plan.ops
                         if op.kind is Kind.COPY or (op.kind is Kind.MOVE and not op.is_dir))

        def on_item(op, number: int, count: int) -> None:       # a worker thread: only stores the text
            current["text"] = f"{self.fs.basename(op.src or op.dst)}  ({number} of {count})"

        def progress(done: int, total: int) -> None:
            if "box" not in shown:
                shown["box"] = self.dialogs.make_progress(plan.title, lambda: holder["job"].cancel() if "job" in holder else None)
                shown["box"].plan_bytes = plan_bytes
            shown["box"].detail = current.get("text", "")
            shown["box"].update(done, total)

        def finished(job: Job) -> None:
            if journal is not None and not self._closing:      # closing the program cancels the jobs: that is not finishing
                journal.remove(remember.id)
            if "box" in shown:
                shown["box"].close()
            if job in self._jobs:
                self._jobs.remove(job)
            self._job = self._jobs[0] if self._jobs else None
            self._update_queue_label()
            self._report(job, unmark)
            keep = select or self.active.current_name()
            self.active.set_folder(self.active.path, select=keep)
            self.other.refresh()

        job = run_plan_job(self.runner, plan, self.fs, selection=self.selection, undo_log=self.undo_log,
                           on_progress=progress, on_done=finished, options=self._exec_options(on_item),
                           **({} if self.trasher is None else {"trasher": self.trasher}))
        holder["job"] = job
        if self.paused:
            job.token.pause()
        self._jobs.append(job)
        self._job = self._jobs[0]
        self._update_queue_label()

    def toggle_pause(self) -> None:
        """Pause or resume the running operation and the ones waiting behind it."""
        self.paused = not self.paused
        for job in self._jobs:
            job.token.pause() if self.paused else job.token.resume()
        self._update_queue_label()

    def cancel_waiting(self) -> None:
        """Drop the operations that have not started; the running one carries on."""
        waiting = [j for j in self._jobs if j.state is JobState.QUEUED]
        for job in waiting:
            job.cancel()
        self._say(f"Cancelled {len(waiting)} waiting operation{'s' if len(waiting) != 1 else ''}" if waiting
                  else "No operations are waiting")

    def _update_queue_label(self) -> None:
        waiting = sum(1 for j in self._jobs if j.state is JobState.QUEUED)
        parts = []
        if self._jobs:
            parts.append(("Paused: " if self.paused else "Running: ") + self._jobs[0].label)
        if waiting:
            parts.append(f"{waiting} waiting")
        self.queue_label.setText((" " + chr(0xB7) + " ").join(parts))
        self.queue_label.setVisible(bool(parts))

    def _exec_options(self, on_item=None) -> ExecOptions:
        """The run options from Settings > Copy and Move (gui/copy_settings.py)."""
        s = self.copy_settings()
        options = ExecOptions(limit_bps=int(s["limit_mb"] * 1024 * 1024) or None, on_item=on_item, verify=s["verify"],
                              retries=s["retries"], retry_delay=s["retry_delay"], workers=s["workers"] or None,
                              native_copy=s["native"], flush={"auto": None, "always": True, "never": False}[s["flush"]])
        if s["ask_on_error"]:
            skip_all = []

            def on_error(op, text: str) -> str:
                """Called on a worker thread: the question is asked on the window's thread and the worker waits."""
                if skip_all:
                    return "skip"
                answer: dict = {}
                ready = threading.Event()

                def ask() -> None:
                    try:
                        name = self.fs.basename(op.src or op.dst)
                        answer["v"] = self.dialogs.ask_error(name + chr(10) * 2 + text)
                    finally:
                        ready.set()

                self.dispatcher(ask)
                ready.wait()
                choice = answer.get("v", "skip")
                if choice == "skip_all":
                    skip_all.append(True)
                    return "skip"
                return choice

            options.on_error = on_error
        return options

    def _report(self, job: Job, unmark: Optional[list]) -> None:
        if job.state is JobState.FAILED:
            self.dialogs.info("Operation failed", str(job.error))
            return
        result = job.result
        lost = len(getattr(result, "tags_lost", []) or [])
        if result.failed:
            failed = [r.op.src for r in result.failed]
            if unmark:                           # what went well is unmarked; what failed stays marked for a retry
                self.selection.remove([u for u in unmark if not any(f.startswith(u) for f in failed)])
            lines = [f"{self.fs.basename(r.op.src or r.op.dst)}: {r.error}" for r in result.failed[:10]]
            self.dialogs.info("Some items failed", "\n".join(lines))
        elif job.state is JobState.CANCELLED:
            self._say(f"Cancelled. {len(result.done)} step(s) were done; Ctrl+Z undoes them.")
        else:
            if unmark:
                self.selection.remove(unmark)
            self._say("Done" if not lost else
                      f"Done. {lost} item{'s were' if lost != 1 else ' was'} copied without tags: the drive cannot store them")
