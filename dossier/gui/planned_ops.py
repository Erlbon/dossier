"""Planned operations: Shift+F5 / Shift+F6 put a copy or move of the marked items on a list, Ctrl+F3 shows the list, and from there they
are reviewed, changed (Edit... opens the Ctrl+F5 box), kept for reuse and run, one or all, through the operation queue. The list itself
is ``core/planned.py``; the owner's decisions are in CLAUDE.md, "Planned operations" (2026-11-11).

Each entry is planned again when it runs, from what is on disk then. Run All runs the entries top to bottom, each planned only when
the one before it has finished, so a move earlier in the list is seen by a copy after it. An entry that is not kept leaves the list
once it ran without failures; a kept one stays with when it ran and how it went. A kept copy with the rule "missing or changed"
copies what is missing and replaces what changed, with no questions.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout)

from ..core.ops import Plan, Resolution, plan_copy, plan_move, skip_same
from ..core.planned import PlannedEntry, PlannedList, default_name
from ..core.progress import check
from ..core.sizefmt import human_size
from ..core.vfs import stat_or_none
from ..core.worker import JobState
from .background import run_in_background
from .owned_dialog import OwnedDialog
from .zip_edit import zip_parts

RULE_TEXT = {"missing or changed": "Missing or changed", "newer only": "Newer only", "ask": "Ask"}


def result_of(job, failed: int) -> str:
    if job.state is JobState.CANCELLED:
        return "cancelled"
    if job.state is not JobState.DONE:
        return "failed"
    return f"{failed} failed" if failed else "done"


class PlannedMixin:
    """Part of ``MainWindow``."""

    def planned_list(self) -> PlannedList:
        path = os.path.join(os.path.dirname(self.settings.fileName()), "planned.json")
        if getattr(self, "_planned", None) is None or self._planned.path != path:
            self._planned = PlannedList(path)
        return self._planned

    # Shift+F5 / Shift+F6 ---------------------------------------------------------------------------------------------------------
    def plan_copy(self) -> None:
        self._add_planned("copy")

    def plan_move(self) -> None:
        self._add_planned("move")

    def _add_planned(self, kind: str) -> None:
        title = "Plan a Move" if kind == "move" else "Plan a Copy"
        if self._home_blocked(title):
            return
        sources = self.active.targets()
        if not sources:
            return
        if self.other.loading:
            self.dialogs.info(title, f"The other panel is still opening {self.other.pending_path}. Wait for it, or press Esc in that "
                                     "panel, and try again.")
            return
        dest = self.other.path
        if zip_parts(dest) is not None:
            self.dialogs.info(title, "A planned operation cannot go into an archive. Open the archive in the other panel and copy into "
                                     "it now with F5.")
            return
        entry = PlannedEntry(kind, tuple(sources), dest, origin=self.active.real_folder(), verify=self.act_verify.isChecked())
        self.planned_list().add(entry)
        n = len(sources)
        count = len(self.planned_list().load())
        self._say(f"Planned: {kind} {n} item{'s' if n != 1 else ''} to {dest}. {count} on the list (Ctrl+F3 shows it)")
        self._refresh_planned_window()

    # the window ----------------------------------------------------------------------------------------------------------------
    def show_planned(self) -> None:
        """Ctrl+F3: the list of planned operations, one window, brought to the front when it is open already."""
        window = getattr(self, "_planned_window", None)
        if window is None:
            window = self._planned_window = PlannedWindow(self)
            window.finished.connect(lambda _r: setattr(self, "_planned_window", None))
        window.reload()
        self._show_planned_window(window)

    def _show_planned_window(self, window) -> None:              # a seam for tests
        window.show()
        window.raise_()
        window.activateWindow()

    def _refresh_planned_window(self) -> None:
        window = getattr(self, "_planned_window", None)
        if window is not None:
            window.reload()

    # running --------------------------------------------------------------------------------------------------------------------
    def run_planned(self, ids: list) -> None:
        """Run the entries ``ids`` in that order, each planned when the one before it has finished."""
        todo = list(ids)
        if not todo:
            return
        self._run_next_planned(todo)

    def _run_next_planned(self, todo: list) -> None:
        while todo:
            entry = self.planned_list().get(todo.pop(0))
            if entry is not None:
                break
        else:
            return

        def build(watch):
            return self._plan_for_entry(entry, watch)

        def then(plan: Plan) -> None:
            if entry.newer:
                plan = plan.resolve(Resolution.OVERWRITE_IF_NEWER, self.fs)          # an older file is replaced, a newer one stays
            elif entry.keep and entry.skip_same:
                plan = plan.resolve(Resolution.OVERWRITE, self.fs)                   # missing or changed: what changed is replaced
            plan = self._settle(plan)                                                 # blocking problems and (rule "ask") conflicts
            if plan is None:
                self._finish_planned(entry, "not run", todo, ran=False)
                return
            self._run(plan, remember=self.intent_for(plan, list(entry.sources), entry.dest), verify=entry.verify,
                      on_done=lambda job: self._finish_planned(entry, result_of(job, self._failed_steps(job)), todo))

        self._plan_in_background(f"Preparing: {entry.name or default_name(entry)}", build, then)

    def _plan_for_entry(self, entry: PlannedEntry, watch) -> Plan:
        """The entry's plan from what is on disk now (on a thread): the items still there, the destination as the box reads it."""
        sources = [s for s in entry.sources if stat_or_none(self.fs, s) is not None]
        if not sources:
            return Plan(entry.title, blocking=("The items of this planned operation are gone: " + ", ".join(entry.sources[:3]),))
        folder, new_name, make, problem = self._transfer_target(entry.dest, entry.dest, sources)
        if problem:
            return Plan(entry.title, blocking=(problem,))
        if zip_parts(folder) is not None:
            return Plan(entry.title, blocking=("A planned operation cannot go into an archive",))
        if entry.kind == "move":
            return plan_move(self.fs, sources, folder, watch=watch, make_dest=make, new_name=new_name)
        plan = plan_copy(self.fs, sources, folder, watch=watch, make_dest=make, new_name=new_name, only=entry.only,
                         flatten=entry.flatten)
        if entry.skip_same:
            plan = skip_same(plan, self.fs, by_content=entry.verify, cancel=getattr(watch, "cancel", None), watch=watch)
        return plan

    def _finish_planned(self, entry: PlannedEntry, result: str, todo: list, ran: bool = True) -> None:
        current = self.planned_list().get(entry.id)
        if current is not None:
            if ran and result == "done" and not current.keep:
                self.planned_list().remove(entry.id)              # done: a one-off leaves the list
            else:
                from dataclasses import replace
                self.planned_list().update(replace(current, last_run=time.time() if ran else current.last_run,
                                                   last_result=result))
        self._refresh_planned_window()
        self._run_next_planned(todo)

    # Edit... --------------------------------------------------------------------------------------------------------------------
    def edit_planned(self, entry: PlannedEntry) -> Optional[PlannedEntry]:
        """The Ctrl+F5 box for a planned entry; the changed entry is saved and returned (None when cancelled)."""
        from dataclasses import replace
        answer = self.dialogs.ask_transfer(f"Edit: {entry.title}", self._planned_summary(entry), "Save", entry.dest, entry.verify,
                                           entry.kind == "move", local="://" not in entry.dest,
                                           options={"only": entry.only, "flatten": entry.flatten, "newer": entry.newer,
                                                    "skip_same": entry.skip_same})
        if answer is None:
            return None
        changed = replace(entry, dest=answer.dest or entry.dest, verify=answer.verify, only=answer.only, flatten=answer.flatten,
                          newer=answer.newer, skip_same=answer.skip_same)
        self.planned_list().update(changed)
        self._refresh_planned_window()
        return changed

    @staticmethod
    def _planned_summary(entry: PlannedEntry) -> str:
        lines = [f"{entry.title} {len(entry.sources)} item{'s' if len(entry.sources) != 1 else ''}", f"from {entry.origin}",
                 f"to {entry.dest}", ""]
        lines += [f"  {os.path.basename(s.rstrip(chr(92) + '/'))}" for s in entry.sources[:12]]
        if len(entry.sources) > 12:
            lines.append(f"  ... and {len(entry.sources) - 12} more")
        if entry.keep:
            lines += ["", "When it runs again: " + RULE_TEXT[entry.rerun_rule()].lower()
                      + " (skip what is there and the same = missing or changed; newer only; neither = ask)"]
        return chr(10).join(lines)


class PlannedWindow(OwnedDialog):
    COLUMNS = ("What", "From", "To", "Items", "Kept", "When it runs again", "Last run")

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Planned Operations")
        self.setModal(False)
        self.resize(1080, 460)
        self.entries: list = []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        # Resizable but not sortable, on purpose (the owner, 2026-11-11): the row order is the running order of Run All.
        self.table.setSortingEnabled(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for c, width in enumerate((60, 230, 230, 180, 170, 140)):
            self.table.setColumnWidth(c, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda _i: self.edit())
        layout.addWidget(self.table, 1)
        self.facts = QLabel("")
        self.facts.setWordWrap(True)
        layout.addWidget(self.facts)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text, slot in (("run", "Run Selected", self.run_selected), ("run_all", "Run All", self.run_all),
                                ("edit", "Edit...", self.edit), ("keep", "Keep / Don't Keep", self.toggle_keep),
                                ("up", "Up", lambda: self.move(-1)), ("down", "Down", lambda: self.move(1)),
                                ("remove", "Remove", self.remove), ("clear", "Clear the List", self.clear)):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self._count_job = None

    # contents -------------------------------------------------------------------------------------------------------------------
    def reload(self) -> None:
        keep = {e.id for e in self.selected()}
        self.entries = self.win.planned_list().load()
        self.table.setRowCount(len(self.entries))
        for r, e in enumerate(self.entries):
            named = [os.path.basename(s.rstrip(chr(92) + "/")) for s in e.sources]
            items = ", ".join(named[:3]) + (f" and {len(named) - 3} more" if len(named) > 3 else "")
            when = time.strftime("%d %b %H:%M", time.localtime(e.last_run)) if e.last_run else ""
            last = f"{when} {e.last_result}".strip() if (when or e.last_result) else ""
            cells = (e.title, e.origin, e.dest, items, "★ " + e.name if e.keep else "",
                     RULE_TEXT[e.rerun_rule()] if e.keep else "", last)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text if c != 3 else chr(10).join(e.sources[:20]))
                self.table.setItem(r, c, item)
        self.table.clearSelection()
        model, chosen = self.table.model(), self.table.selectionModel()
        for r, e in enumerate(self.entries):
            if e.id in keep:                                     # through the model: selectRow would read held modifier keys
                chosen.select(model.index(r, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._update_buttons()
        self.setWindowTitle(f"Planned Operations ({len(self.entries)})")

    def selected(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.entries[r] for r in rows if r < len(self.entries)]

    def _update_buttons(self) -> None:
        chosen = self.selected()
        for key in ("run", "remove", "keep"):
            self.buttons[key].setEnabled(bool(chosen))
        for key in ("edit", "up", "down"):
            self.buttons[key].setEnabled(len(chosen) == 1)
        self.buttons["run_all"].setEnabled(bool(self.entries))
        self.buttons["clear"].setEnabled(bool(self.entries))

    def _selection_changed(self) -> None:
        self._update_buttons()
        chosen = self.selected()
        if len(chosen) != 1:
            self.facts.setText("")
            return
        entry = chosen[0]
        self.facts.setText("Counting what it would copy now...")

        def work(progress, cancel):
            def watch(n):
                check(cancel)
            watch.cancel = cancel
            plan = self.win._plan_for_entry(entry, watch)
            files = [op for op in plan.ops if not op.is_dir and op.kind.value in ("copy", "move")]
            return entry.id, plan.blocking, len(files), sum(op.size for op in files)

        def counted(result) -> None:
            entry_id, blocking, n, size = result
            if [e.id for e in self.selected()] != [entry_id]:
                return
            self.facts.setText(blocking[0] if blocking else
                               f"Counted now: {n:,} file{'s' if n != 1 else ''}, {human_size(size)} to {entry.title.lower()}")

        run_in_background(self, self.win.cmd_runner, "Counting", work, on_result=counted, tracked=[], indeterminate=True)

    # buttons --------------------------------------------------------------------------------------------------------------------
    def run_selected(self) -> None:
        self.win.run_planned([e.id for e in self.selected()])

    def run_all(self) -> None:
        self.win.run_planned([e.id for e in self.entries])

    def edit(self) -> None:
        chosen = self.selected()
        if len(chosen) == 1 and self.win.edit_planned(chosen[0]) is not None:
            self.reload()

    def toggle_keep(self) -> None:
        lst = self.win.planned_list()
        for e in self.selected():
            if e.keep:
                lst.update(e.kept(False))
                continue
            name = self.win.dialogs.ask_text("Keep for Reuse", "A name for it:", e.name or default_name(e))
            if name is None:
                return
            lst.update(e.kept(True, name.strip() or default_name(e)))
        self.reload()

    def move(self, delta: int) -> None:
        chosen = self.selected()
        if len(chosen) == 1:
            self.win.planned_list().move(chosen[0].id, delta)
            self.reload()

    def remove(self) -> None:
        chosen = self.selected()
        if not chosen:
            return
        kept = [e for e in chosen if e.keep]
        if kept and not self.win.dialogs.confirm("Remove", f"Remove {len(chosen)} planned operation"
                                                           f"{'s' if len(chosen) != 1 else ''}, {len(kept)} of them kept for reuse?",
                                                 "Remove"):
            return
        for e in chosen:
            self.win.planned_list().remove(e.id)
        self.reload()

    def clear(self) -> None:
        if self.entries and self.win.dialogs.confirm("Clear the List", f"Remove all {len(self.entries)} planned operations, kept ones "
                                                                       "included? Nothing is copied or deleted.", "Clear"):
            self.win.planned_list().clear()
            self.reload()
