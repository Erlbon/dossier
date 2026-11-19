"""Folder rules in the window (card 68A): Tools > Rules > Run Rules and Folder Rules..., and the hint in the status line.

``core/folder_rules.py`` holds the rules and works out what they would do with a listing. This file reads the listing on a thread, shows
the result and turns it into the plans the window already knows: the same preview the Health window shows for a fix, then the ordinary
queue (conflict box, progress, Cancel, the recycle bin). Rules never act alone, and opening a folder never opens a box: when the rules of
a folder match something, the status line says so, with a link that shows the plan. The rules are kept in the settings under
``folder-rules/rules``, keyed by folder, beside the folder layouts; never as a file in the folder.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel

from ..core import folder_rules as R
from ..core.layouts import has_rules_for, key_of
from ..core.ops import plan_copy, plan_delete, plan_move
from .background import run_in_background
from .folder_rules_dialog import FolderRulesDialog
from .health_window import PlanPreview

RULES_KEY = "folder-rules/rules"


class FolderRulesMixin:
    """Part of ``MainWindow``."""

    # the store ------------------------------------------------------------------------------------------------------------------
    def rule_store(self) -> R.RuleStore:
        store = getattr(self, "_rule_store", None)
        if store is None:
            store = self._rule_store = R.RuleStore.from_json(self.settings.value(RULES_KEY, ""))
        return store

    def _save_rules(self) -> None:
        if len(self.rule_store()):
            self.settings.setValue(RULES_KEY, self.rule_store().to_json())
        else:
            self.settings.remove(RULES_KEY)

    def folder_rules_of(self, panel) -> list:
        """The rules of the folder this panel shows (none on the Home page, in archives and where nothing is set)."""
        if panel is None or panel.is_home or not has_rules_for(panel.path):
            return []
        return self.rule_store().rules_for(panel.path)

    # the hint in the status line ---------------------------------------------------------------------------------------------------
    def make_rules_label(self) -> QLabel:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(lambda _href: self.run_folder_rules())
        label.hide()
        return label

    def build_folder_rules(self) -> None:
        self._rule_hints: dict = {}                  # id(panel) -> (folder key, proposals found)
        self._rule_checks: dict = {}                 # id(panel) -> number of the latest check, so an old answer is dropped
        for panel in (self.left, self.right):
            panel.folder_changed.connect(self._check_rules_for)

    def _check_rules_for(self, panel) -> None:
        """A panel showed a folder: if it has rules, look on a thread for what they would do. The window's thread never touches the disk."""
        number = self._rule_checks.get(id(panel), 0) + 1
        self._rule_checks[id(panel)] = number
        rules = self.folder_rules_of(panel)
        if not rules:
            self._rule_hints.pop(id(panel), None)
            self.update_rules_label()
            return
        folder, fs, now = panel.path, self.fs, time.time()

        def work(progress, cancel):
            try:
                return R.proposals(rules, fs.list(folder), folder, now, join=fs.join, case_sensitive=fs.case_sensitive)
            except OSError:
                return []                            # an unreadable folder is the listing's business: no box from a hint

        def done(found) -> None:
            if self._rule_checks.get(id(panel)) != number or key_of(panel.path) != key_of(folder):
                return                               # the panel has moved on
            if found:
                self._rule_hints[id(panel)] = (key_of(folder), found)
            else:
                self._rule_hints.pop(id(panel), None)
            self.update_rules_label()

        run_in_background(self, self.cmd_runner, "Checking the rules of this folder", work, on_result=done, tracked=self._size_jobs)

    def update_rules_label(self) -> None:
        label = getattr(self, "rules_label", None)
        if label is None or not hasattr(self, "active"):
            return
        hint = self._rule_hints.get(id(self.active)) if hasattr(self, "_rule_hints") else None
        if hint is None or hint[0] != key_of(self.active.path):
            label.hide()
            return
        text = R.summary(hint[1])
        label.setText(f"Rules for this folder would {text}. <a href=\"plan\">Show the Plan</a>")
        label.setToolTip("The rules of this folder make a plan. Nothing changes until you press Run (Tools > Rules > Folder Rules... edits them).")
        label.show()

    # Tools > Rules ----------------------------------------------------------------------------------------------------------------
    def run_folder_rules(self) -> None:
        """Tools > Rules > Run Rules: this folder's rules make a plan, shown before anything is run."""
        panel = self.active
        rules = self.folder_rules_of(panel)
        if not rules:
            self._say("No rules for this folder (Tools > Rules > Folder Rules... adds some)")
            return
        folder, fs, now = panel.path, self.fs, time.time()

        def build(watch):
            found = R.proposals(rules, fs.list(folder), folder, now, join=fs.join, case_sensitive=fs.case_sensitive)
            return found, [self._rule_plan(g, watch) for g in R.groups(found)]

        self._plan_in_background("Preparing the rules", build, lambda made: self._rules_planned(panel, *made))

    def _rule_plan(self, group: R.Group, watch):
        """The plan for one group: the same planners Copy, Move and Delete use (a missing destination folder is made when the plan runs)."""
        if group.action == "delete":
            return plan_delete(self.fs, group.paths, to_trash=True)
        planner = plan_move if group.action == "move" else plan_copy
        return planner(self.fs, group.paths, group.dest, watch=watch, make_dest=True)

    def _rules_planned(self, panel, found: list, plans: list) -> None:
        if not found or not plans:
            self._say("Nothing in this folder matches its rules")
            return
        dialog = PlanPreview(self, plans, "Plan from the rules of this folder")
        self._show_rules_preview(dialog)
        if dialog.result() != QDialog.DialogCode.Accepted or any(p.blocking for p in plans):
            return
        for plan in plans:
            ready = self._settle(plan)                 # conflicts are asked about, never replaced
            if ready is not None:
                self._run(ready)

    def _show_rules_preview(self, dialog) -> None:              # a seam for tests
        dialog.exec()

    def edit_folder_rules(self) -> None:
        """Tools > Rules > Folder Rules...: this folder's rules, with Add, Edit and Remove."""
        panel = self.active
        if panel.is_home or not has_rules_for(panel.path):
            self._say("Open a folder on a drive of this computer first: rules belong to one folder")
            return
        folder = panel.path
        answer = self._ask_folder_rules(folder, self.rule_store().rules_for(folder))
        if answer is None:
            return
        self.rule_store().set_rules(folder, answer)
        self._save_rules()
        self._check_rules_for(panel)
        n = len(self.rule_store().rules_for(folder))
        self._say(f"{n} rule{'s' if n != 1 else ''} for this folder" if n else "This folder has no rules now")

    def _ask_folder_rules(self, folder: str, rules: list) -> Optional[list]:      # a seam for tests
        dialog = FolderRulesDialog(self, folder, rules)
        return list(dialog.rules) if dialog.exec() == QDialog.DialogCode.Accepted else None
