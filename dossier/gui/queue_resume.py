"""Continue unfinished copies, moves and deletes after a restart (opt-in: Settings > Copy and Move).

``_run`` writes what was asked for into the journal (``core/queue_journal.py``) when a job is queued and takes it off when the job
ends, however it ends. When the program is closed or killed in between, the entry stays; the next start offers to continue: the plan
is made again from what is still there, so what was done is not done twice. Nothing is written unless the owner switched it on.
"""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Optional

from PyQt6.QtCore import QTimer

from ..core.ops import plan_copy, plan_delete, plan_move
from ..core.queue_journal import Entry, Journal, remaining_plan, skip_identical

KIND_OF_TITLE = (("Copy", "copy"), ("Move", "move"), ("Delete", "delete"))


class QueueResumeMixin:
    """Part of ``MainWindow``."""

    def queue_journal(self) -> Optional[Journal]:
        """The journal when remembering is on; None when it is off (nothing is then read or written)."""
        if not self.copy_settings()["remember_queue"]:
            return None
        return self._journal_file()

    def _journal_file(self) -> Journal:
        path = os.path.join(os.path.dirname(self.settings.fileName()), "queue.json")
        if getattr(self, "_journal", None) is None or self._journal.path != path:      # one object: it orders the writes and knows what was taken off
            self._journal = Journal(path)
        return self._journal

    def intent_for(self, plan, sources: list, dest: str = "") -> Optional[Entry]:
        """What to remember about ``plan``: its kind, the items and where they go; None when remembering is off or the plan is not a
        copy, move or delete."""
        if not self.copy_settings()["remember_queue"]:
            return None
        kind = next((k for title, k in KIND_OF_TITLE if plan.title.startswith(title)), "")
        if not kind or not sources:
            return None
        return Entry(kind, list(sources), dest, to_trash=plan.title != "Delete", title=plan.title)   # "Delete" = for good

    def forget_queue_journal(self) -> None:
        self._journal_file().clear()

    # at start-up -------------------------------------------------------------------------------------------------------------
    def schedule_resume_offer(self) -> None:
        """Once, after the window has been shown."""
        if not getattr(self, "_resume_offered", False):
            self._resume_offered = True
            QTimer.singleShot(0, self.offer_resume)

    def offer_resume(self, manual: bool = False) -> None:
        """Ask about the unfinished operations. ``manual``: the owner asked (Tools > Operations), so say when there is nothing."""
        journal = self.queue_journal()
        entries = journal.load() if journal is not None else []
        if not entries:
            if manual:
                self._say("No unfinished operations are remembered" if journal is not None else
                          "Unfinished operations are not remembered: switch it on in Settings > Copy and Move")
            return
        answer = self.dialogs.ask_resume([e.describe() for e in entries])
        if answer == "discard":
            journal.clear()
        elif answer == "continue":
            for entry in entries:
                self._resume(entry)
        else:                                                     # "later": the list stays, and the status line says how to get back to it
            n = len(entries)
            self._say(f"{n} unfinished operation{'s' if n != 1 else ''} remembered: Tools > Operations > Unfinished Operations...")

    def _resume(self, entry: Entry) -> None:
        """Make the plan again from what is still there, skip what the interrupted run had already copied, and queue it."""
        def build(watch):
            if entry.kind == "plan":
                return remaining_plan(entry, self.fs)
            if entry.kind == "delete":
                return plan_delete(self.fs, entry.sources, to_trash=entry.to_trash)
            plan = (plan_move if entry.kind == "move" else plan_copy)(self.fs, entry.sources, entry.dest, watch=watch)
            return skip_identical(plan, self.fs)

        def go(plan) -> None:
            plan = self._settle(plan) if plan.ops or plan.blocking else plan
            journal = self.queue_journal()
            if plan is None or not plan.ops:
                if journal is not None:
                    journal.remove(entry.id)
                if plan is not None:
                    self._say(f"Nothing left to do: {entry.describe()}")
                return
            kept = replace(entry, ops=list(plan.ops), note="") if entry.kind == "plan" else entry     # the steps still to do, not the old list
            self._run(plan, unmark=entry.sources if entry.kind in ("copy", "move") else None, remember=kept)

        self._plan_in_background("Preparing to continue", build, go)
