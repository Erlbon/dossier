"""The window's side of the assistant feature (spec section 12): the settings dialog, what the window shows to the assistant's server, and the
owner's confirmation of every change an assistant proposes.

The server is a separate program (``dossier mcp``) that shares small files with the window (``assistant/bridge.py``). While the feature is
on, the window publishes what each panel shows and the shared selection (once a second at most, and only when it changed), and looks at
the requests the server leaves. A change to the selection is applied (the owner sees it at once and can undo it by unmarking). A change to
files is never run without the owner: the window makes the plan itself from the request, checks again that every path lies inside the
folders the owner listed and that file changes are allowed, shows the plan in words, and runs it only if the owner presses Run.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit,
                             QPushButton, QSpinBox, QVBoxLayout)

from ..assistant import bridge, calllog, config as config_module, paths as assistant_paths
from ..assistant.scope import Denied, Scope
from ..core import compare as cmp, sync as sync_core
from ..core.ops import Resolution, plan_copy, plan_delete, plan_move, plan_rename
from ..core.sizefmt import human_size

TICK_MS = 1000
HEARTBEAT = 5.0
PREVIEW_LINES = 12
POLICIES = {"skip": Resolution.SKIP, "overwrite": Resolution.OVERWRITE, "keep-both": Resolution.KEEP_BOTH, "newer": Resolution.OVERWRITE_IF_NEWER}


def server_snippet() -> str:
    """The setting to give an assistant's program so it can start the server: this program, with the command ``mcp``."""
    import json
    if getattr(sys, "frozen", False):
        entry = {"command": sys.executable, "args": ["mcp"]}
    else:
        entry = {"command": sys.executable, "args": ["-m", "dossier", "mcp"]}
    return json.dumps({"mcpServers": {"dossier": entry}}, indent=2)


class AssistantDialog(QDialog):
    def __init__(self, parent, current: config_module.AssistantConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assistant Access")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        intro = QLabel("An AI assistant (Claude, for example) can look at your files through Dossier and propose changes. It is off until you "
                       "switch it on, it sees only the folders you list, it can only read unless you allow changes, and every change it "
                       "proposes needs your OK here, in words, before anything happens.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.enabled = QCheckBox("Let an assistant use Dossier")
        self.enabled.setChecked(current.enabled)
        layout.addWidget(self.enabled)
        layout.addWidget(QLabel("The folders it may look into (and everything below them):"))
        self.roots = QListWidget()
        self.roots.addItems(current.roots)
        self.roots.setMaximumHeight(110)
        layout.addWidget(self.roots)
        row = QHBoxLayout()
        add = QPushButton("Add a Folder...")
        remove = QPushButton("Remove")
        for b in (add, remove):
            b.setAutoDefault(False)
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        add.clicked.connect(self._add)
        remove.clicked.connect(lambda: [self.roots.takeItem(self.roots.row(i)) for i in self.roots.selectedItems()])
        form = QFormLayout()
        self.changes = QCheckBox("Let it propose changes to files (copy, move, rename, delete). Each one still needs your OK.")
        self.changes.setChecked(current.allow_file_changes)
        self.log = QCheckBox("Keep a log of every call it makes (file names, never contents)")
        self.log.setChecked(current.log_calls)
        self.read_kb = QSpinBox()
        self.read_kb.setRange(config_module.MIN_READ_KB, config_module.MAX_READ_KB)
        self.read_kb.setSuffix(" KB")
        self.read_kb.setValue(current.max_read_kb)
        form.addRow(self.changes)
        form.addRow(self.log)
        form.addRow("The most of a file it can read in one call", self.read_kb)
        layout.addLayout(form)
        log_row = QHBoxLayout()
        self.open_log = QPushButton("Open the Log")
        self.clear_log = QPushButton("Clear the Log")
        for b in (self.open_log, self.clear_log):
            b.setAutoDefault(False)
            log_row.addWidget(b)
        log_row.addStretch(1)
        layout.addLayout(log_row)
        self.open_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(assistant_paths.log_file())))
        self.clear_log.clicked.connect(calllog.clear)
        layout.addWidget(QLabel("Give the assistant's program this setting, so it can start the server:"))
        self.snippet = QPlainTextEdit(server_snippet())
        self.snippet.setReadOnly(True)
        self.snippet.setMaximumHeight(110)
        layout.addWidget(self.snippet)
        copy = QPushButton("Copy the Setting")
        copy.setAutoDefault(False)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.snippet.toPlainText()))
        layout.addWidget(copy)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "A folder the assistant may look into")
        if folder:
            self.add_root(os.path.normpath(folder))

    def add_root(self, folder: str) -> None:
        if folder not in [self.roots.item(i).text() for i in range(self.roots.count())]:
            self.roots.addItem(folder)

    def values(self) -> config_module.AssistantConfig:
        return config_module.AssistantConfig(self.enabled.isChecked(), [self.roots.item(i).text() for i in range(self.roots.count())],
                                             self.changes.isChecked(), self.log.isChecked(), self.read_kb.value()).cleaned()

    def _accept(self) -> None:
        v = self.values()
        if v.enabled and not v.roots:
            self.problem.setText("List at least one folder: with none, the assistant can see nothing.")
            return
        self.accept()


class AssistantMixin:
    """Part of ``MainWindow``."""

    def build_assistant(self) -> None:
        self._assistant_state_text = ""
        self._assistant_last_write = 0.0
        self._assistant_busy: set = set()
        self._assistant_timer = QTimer(self)
        self._assistant_timer.setInterval(TICK_MS)
        self._assistant_timer.timeout.connect(self.assistant_tick)
        self._assistant_timer.start()

    def assistant_config(self) -> config_module.AssistantConfig:
        return config_module.load()

    def _ask_assistant_settings(self, dlg) -> bool:           # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def open_assistant_settings(self) -> None:
        dlg = AssistantDialog(self, self.assistant_config())
        if not self._ask_assistant_settings(dlg):
            return
        config_module.save(dlg.values())
        if not dlg.values().enabled:
            bridge.clear_state()
        self._assistant_state_text = ""
        self.assistant_tick()
        self._say("Assistant access is " + ("on" if dlg.values().enabled else "off"))

    # what the window shows ----------------------------------------------------------------------------------------------------------------
    def assistant_state(self) -> dict:
        panels = []
        for side, panel in (("left", self.left), ("right", self.right)):
            entry = panel.current_entry() if not panel.is_home else None
            panels.append({"side": side, "path": panel.path, "home": panel.is_home, "cursor": entry.name if entry is not None else "",
                           "tabs": panel.tab_paths(), "marked": len(self.selection.paths())})
        return {"active": "left" if self.active is self.left else "right", "panels": panels, "selection": self.selection.paths(),
                "version": __import__("dossier.core.version", fromlist=["APP_VERSION"]).APP_VERSION}

    def assistant_tick(self) -> None:
        config = self.assistant_config()
        if not config.enabled:
            return
        try:
            state = self.assistant_state()
            text = repr(state)
            if text != self._assistant_state_text or time.monotonic() - self._assistant_last_write > HEARTBEAT:
                bridge.publish_state(state)
                self._assistant_state_text, self._assistant_last_write = text, time.monotonic()
            self._process_assistant_requests(config)
        except OSError:
            pass                                               # the folder cannot be written: try again at the next tick

    # what the assistant asks ------------------------------------------------------------------------------------------------------------------
    def _process_assistant_requests(self, config) -> None:
        for request in bridge.pending_requests():
            rid = request.get("id", "")
            if rid in self._assistant_busy:
                continue
            kind, payload = request.get("kind"), request.get("payload") or {}
            if kind == "selection":
                self._assistant_selection(rid, payload, config)
            elif kind == "plan":
                self._assistant_busy.add(rid)
                self._assistant_plan(rid, payload, config)
            else:
                bridge.answer(rid, "failed", "this Dossier does not know that kind of request")

    def _assistant_paths(self, payload_paths, config) -> list:
        scope = Scope(config.roots)
        return scope.all(payload_paths if isinstance(payload_paths, list) else [])

    def _assistant_selection(self, rid: str, payload: dict, config) -> None:
        try:
            op = payload.get("op")
            chosen = self._assistant_paths(payload.get("paths"), config) if op != "clear" else []
            if op == "set":
                self.selection.set(chosen)
            elif op == "add":
                self.selection.add(chosen)
            elif op == "remove":
                self.selection.remove(chosen)
            elif op == "clear":
                self.selection.clear()
            else:
                return bridge.answer(rid, "failed", "unknown selection operation")
        except Denied as e:
            return bridge.answer(rid, "failed", str(e))
        bridge.answer(rid, "done", "the selection was changed", size=len(self.selection.paths()))
        self._say(f"An assistant changed the selection ({op}: {len(chosen)} item{'s' if len(chosen) != 1 else ''})")

    def _assistant_plan(self, rid: str, payload: dict, config) -> None:
        """A change to files: checked again here, planned here, and run only when the owner says so."""
        def refuse(message: str, status: str = "rejected") -> None:
            self._assistant_busy.discard(rid)
            bridge.answer(rid, status, message)
        if not config.allow_file_changes:
            return refuse("the owner has not allowed changes to files")
        action = payload.get("action")
        try:
            scope = Scope(config.roots)
            checked = {k: (scope.all(v) if isinstance(v, list) else scope.resolve(v)) for k, v in payload.items()
                       if k in ("sources", "destination", "paths", "path", "left", "right")}
        except Denied as e:
            return refuse(str(e))
        if action not in ("copy", "move", "delete", "rename", "sync"):
            return refuse("unknown kind of change", "failed")

        def build(watch):
            if action == "copy":
                plans = [plan_copy(self.fs, checked["sources"], checked["destination"], watch=watch)]
            elif action == "move":
                plans = [plan_move(self.fs, checked["sources"], checked["destination"], watch=watch)]
            elif action == "delete":
                plans = [plan_delete(self.fs, checked["paths"], to_trash=not payload.get("permanent"))]
            elif action == "rename":
                plans = [plan_rename(self.fs, checked["path"], str(payload.get("new_name", "")))]
            else:
                result = cmp.compare_trees(self.fs, checked["left"], checked["right"], by=payload.get("by") or "size_time")
                actions = [a for a in sync_core.decide_all(result.rows, payload.get("mode", "")) if a.kind]
                plans = sync_core.build_plans(self.fs, checked["left"], checked["right"], actions)
            policy = POLICIES.get(payload.get("on_conflict") or "skip", Resolution.SKIP)
            out = []
            for plan in plans:
                if plan.conflicts and action in ("copy", "move"):
                    plan = plan.resolve(policy, self.fs)
                if plan.conflicts:
                    plan = plan.resolve(Resolution.SKIP, self.fs)
                out.append(plan)
            return out

        def then(plans: list) -> None:
            blocked = [b for p in plans for b in p.blocking]
            steps = sum(len(p.ops) for p in plans)
            if blocked or not steps:
                return refuse("; ".join(blocked) or "there is nothing to do any more", "failed")
            if not self.dialogs.confirm("An assistant asks to change files", self._assistant_summary(action, payload, plans), "Run"):
                return refuse("the owner rejected it")
            self._assistant_run(rid, plans)

        self._plan_in_background("Preparing what the assistant asked for", build, then)

    def _assistant_summary(self, action: str, payload: dict, plans: list) -> str:
        nl = chr(10)
        steps = [op for p in plans for op in p.ops]
        total = sum(op.size for op in steps if op.kind.value in ("copy", "move") and not op.is_dir)
        words = {"copy": "copy", "move": "move", "delete": "delete", "rename": "rename", "sync": "synchronise two folders:"}[action]
        head = f"An assistant asks to {words} {len(steps):,} step{'s' if len(steps) != 1 else ''} ({human_size(total)})."
        reason = " ".join(str(payload.get("reason") or "").split())[:300]
        lines = [head] + ([f'It says: "{reason}"  (what it says is not checked)'] if reason else []) + [""]
        for op in steps[:PREVIEW_LINES]:
            lines.append(f"{op.kind.value}  {op.src}" + (f"  ->  {op.dst}" if op.dst else ""))
        if len(steps) > PREVIEW_LINES:
            lines.append(f"... and {len(steps) - PREVIEW_LINES:,} more")
        warnings = [w for p in plans for w in p.warnings][:5]
        lines += ([""] + warnings) if warnings else []
        lines += ["", "Run it only if you asked for this or recognise it."]
        return nl.join(lines)

    def _assistant_run(self, rid: str, plans: list) -> None:
        state = {"left": len(plans), "done": 0, "failed": 0}

        def finished(job) -> None:
            result = job.result
            state["left"] -= 1
            state["done"] += len(result.done) if result is not None else 0
            state["failed"] += len(result.failed) if result is not None else 1
            if state["left"] == 0:
                self._assistant_busy.discard(rid)
                bridge.answer(rid, "failed" if state["failed"] else "done",
                              f"{state['done']} step{'s' if state['done'] != 1 else ''} done" + (f", {state['failed']} failed" if state["failed"] else ""),
                              done=state["done"], failed=state["failed"])
        for plan in plans:
            self._run(plan, on_done=finished)
