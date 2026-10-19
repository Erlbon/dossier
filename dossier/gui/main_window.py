"""The commander window: two panels, one shared selection, F-key bar, status line.

Every command works on the marked items, or the item under the cursor when nothing is marked
(S4), and goes through the core's plans: planned, confirmed, run in the background with progress
and cancel, undoable with Ctrl+Z.
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSettings, QStandardPaths, Qt
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSplitter, QVBoxLayout,
                             QWidget)

from ..core.ops import (Plan, Resolution, check_name, plan_copy, plan_delete, plan_move, plan_rename)
from ..core.platform import IS_WINDOWS
from ..core.selection import SelectionStore
from ..core.undo_log import Step, UndoAction, UndoLog
from ..core.vfs import FileSystem, LocalFileSystem
from ..core.worker import Job, JobRunner, JobState, run_plan_job
from .dialogs import Dialogs
from .models import human_size
from .panel import Panel
from .qt_bridge import QtDispatcher
from .theme import ThemeManager

BIN = "recycle bin" if IS_WINDOWS else "trash"
SIZE_LIMIT = 1000    # the status line sizes at most this many marked items


class MainWindow(QMainWindow):
    def __init__(self, fs: Optional[FileSystem] = None, *, settings_path: Optional[str] = None, start=(None, None),
                 dialogs=None, trasher=None) -> None:
        super().__init__()
        self.setWindowTitle("Dossier")
        self.fs = fs or LocalFileSystem()
        self.trasher = trasher
        self.dialogs = dialogs or Dialogs(self)
        self.settings = self._open_settings(settings_path)
        self.theme = ThemeManager(QApplication.instance(), str(self.settings.value("view/scheme", "auto")))

        self.dispatcher = QtDispatcher(self)
        self.selection = SelectionStore(dispatch=self.dispatcher)
        self.undo_log = UndoLog()
        self.runner = JobRunner(self.dispatcher)
        self.busy = False
        self._job: Optional[Job] = None

        self.left = Panel(self.fs, self.selection, dispatch=self.dispatcher)
        self.right = Panel(self.fs, self.selection, dispatch=self.dispatcher)
        self.active = self.left
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.left)
        self.split.addWidget(self.right)
        self.split.setChildrenCollapsible(False)

        self.fkeys = self._build_fkey_bar()
        self.status = QLabel()
        self.hint = QLabel("Tab switches panel, Space marks")
        self.hint.setEnabled(False)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(8, 2, 8, 2)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.hint)

        central = QWidget()
        box = QVBoxLayout(central)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.split, 1)
        box.addWidget(self.fkeys)
        box.addLayout(status_row)
        self.setCentralWidget(central)
        self._build_menus()

        for panel in (self.left, self.right):
            panel.activated.connect(self._set_active)
            panel.table.switch_panel.connect(self.switch_panel)
            panel.table.mark_toggle.connect(self.toggle_mark)
            panel.message.connect(self._say)
        self.selection.subscribe(lambda _s: self._update_status())
        self.theme.changed.connect(lambda: [p.restyle() for p in (self.left, self.right)])

        self._restore(start)
        self.set_drive_style(str(self.settings.value("view/drive_selector", "menu")))
        self._set_active(self.left)
        self.left.table.setFocus()
        self._update_status()

    # setup ---------------------------------------------------------------------------
    @staticmethod
    def _open_settings(path: Optional[str]) -> QSettings:
        if path is None:
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "dossier.ini")      # a plain file, never the registry
        return QSettings(path, QSettings.Format.IniFormat)

    def _action(self, text: str, keys, slot) -> QAction:
        act = QAction(text, self)
        if keys:
            act.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
        act.triggered.connect(lambda _checked=False: slot())
        self.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        files = bar.addMenu("&Files")
        self.act_rename = self._action("Rename", "F2", self.rename)
        self.act_copy = self._action("Copy to Other Panel", "F5", self.copy)
        self.act_move = self._action("Move to Other Panel", "F6", self.move)
        self.act_mkdir = self._action("New Folder", "F7", self.new_folder)
        self.act_delete = self._action("Delete", ["F8", "Delete"], self.delete)
        self.act_delete_perm = self._action("Delete Permanently", "Shift+F8", lambda: self.delete(permanent=True))
        quit_ = self._action("Quit", "Ctrl+Q", self.close)
        for a in (self.act_rename, self.act_copy, self.act_move, self.act_mkdir, self.act_delete, self.act_delete_perm):
            files.addAction(a)
        files.addSeparator()
        files.addAction(quit_)
        mark = bar.addMenu("&Mark")
        for a in (self._action("Select All", "Ctrl+A", self.select_all),
                  self._action("Invert Selection", "*", self.invert_selection),
                  self._action("Deselect All", "Ctrl+Shift+A", self.selection.clear)):
            mark.addAction(a)
        view = bar.addMenu("&View")
        scheme_menu = view.addMenu("Color Scheme")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.scheme_actions = {}
        for key, label in (("auto", "Follow System"), ("light", "Light"), ("dark", "Dark")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.theme.scheme == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_scheme(k))
            group.addAction(act)
            scheme_menu.addAction(act)
            self.scheme_actions[key] = act
        drive_menu = view.addMenu("Drive Selector")
        drive_group = QActionGroup(self)
        drive_group.setExclusive(True)
        self.drive_style_actions = {}
        wanted = str(self.settings.value("view/drive_selector", "menu"))
        for key, label in (("menu", "Dropdown in the Address Bar"), ("strip", "Button Strip Above the Panel")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(wanted == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_drive_style(k))
            drive_group.addAction(act)
            drive_menu.addAction(act)
            self.drive_style_actions[key] = act
        self._action("Drives of Left Panel", "Alt+F1", lambda: self.left.open_drive_menu())
        self._action("Drives of Right Panel", "Alt+F2", lambda: self.right.open_drive_menu())
        commands = bar.addMenu("&Commands")
        for a in (self._action("Undo", "Ctrl+Z", self.undo),
                  self._action("Refresh", "Ctrl+R", self.refresh),
                  self._action("Swap Panels", "Ctrl+U", self.swap_panels)):
            commands.addAction(a)

    def _build_fkey_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._fkey_buttons = []
        for label, slot in (("F2 Rename", lambda: self.rename()), ("F5 Copy", lambda: self.copy()),
                            ("F6 Move", lambda: self.move()), ("F7 Folder", lambda: self.new_folder()),
                            ("F8 Delete", lambda: self.delete())):
            b = QPushButton(label)
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(b, 1)
            self._fkey_buttons.append(b)
        return bar

    # panels ----------------------------------------------------------------------------
    @property
    def other(self) -> Panel:
        return self.right if self.active is self.left else self.left

    def _set_active(self, panel: Panel) -> None:
        self.active = panel
        self.left.set_active(panel is self.left)
        self.right.set_active(panel is self.right)

    def switch_panel(self) -> None:
        target = self.other          # taken once: focusing it already makes it the active panel
        target.table.setFocus()
        self._set_active(target)

    def swap_panels(self) -> None:
        a, b = self.left.path, self.right.path
        self.left.set_folder(b)
        self.right.set_folder(a)

    def refresh(self) -> None:
        self.left.refresh()
        self.right.refresh()

    def set_drive_style(self, style: str) -> None:
        if style not in self.drive_style_actions:
            return
        for panel in (self.left, self.right):
            panel.drive_bar.set_style(style)
        self.settings.setValue("view/drive_selector", style)
        self.drive_style_actions[style].setChecked(True)

    def set_scheme(self, scheme: str) -> None:
        self.theme.set_scheme(scheme)
        self.settings.setValue("view/scheme", self.theme.scheme)
        self.scheme_actions[self.theme.scheme].setChecked(True)

    def _say(self, text: str) -> None:
        self.status.setText(text)

    # marks -------------------------------------------------------------------------------
    def toggle_mark(self) -> None:
        entry = self.active.current_entry()
        if entry is None:
            return
        self.selection.toggle(entry.path)
        table = self.active.table
        nxt = table.currentIndex().row() + 1
        if nxt < self.active.model.entry_count():
            table.setCurrentIndex(self.active.model.index(nxt, 0))

    def _entry_paths(self) -> list:
        m = self.active.model
        return [m.entry_at(r).path for r in range(m.entry_count()) if not m.is_up_row(r)]

    def select_all(self) -> None:
        self.selection.add(self._entry_paths())

    def invert_selection(self) -> None:
        self.selection.invert(self._entry_paths())

    def _update_status(self) -> None:
        paths = self.selection.paths()
        if not paths:
            self.status.setText("No items marked")
            return
        total, counted = 0, 0
        for p in paths[:SIZE_LIMIT]:
            try:
                e = self.fs.stat(p)
                total += 0 if e.is_dir else e.size
                counted += 1
            except OSError:
                pass
        more = "" if len(paths) <= SIZE_LIMIT else "+"
        self.status.setText(f"{len(paths)} marked, {human_size(total)}{more}, across both panels")

    # commands -------------------------------------------------------------------------------
    def _summary(self, plan: Plan, dest: str = "") -> str:
        files = [op for op in plan.ops if op.kind.value in ("copy", "move", "rename", "delete") and not op.is_dir]
        size = sum(op.size for op in plan.ops if op.kind.value == "copy")
        n = len([op for op in plan.ops if op.kind.value != "mkdir"])
        text = f"{plan.title}: {n} item{'s' if n != 1 else ''}"
        if size:
            text += f" ({human_size(size)})"
        if dest:
            text += f"\nto {dest}"
        if plan.warnings:
            text += "\n\n" + "\n".join(plan.warnings[:8])
        return text

    def _settle(self, plan: Plan) -> Optional[Plan]:
        """Show blocking problems, ask about conflicts. Returns a plan ready to run, or None."""
        if plan.blocking:
            self.dialogs.info(plan.title, "\n".join(plan.blocking))
            return None
        if not plan.ops:
            self.dialogs.info(plan.title, "Nothing to do.\n" + "\n".join(plan.warnings[:8]))
            return None
        if plan.conflicts:
            names = [os.path.basename(plan.ops[i].dst) for i in plan.conflicts[:6]]
            more = "" if len(plan.conflicts) <= 6 else f"\nand {len(plan.conflicts) - 6} more"
            choice = self.dialogs.ask_conflict(f"{len(plan.conflicts)} already exist:\n" + "\n".join(names) + more)
            if choice is None:
                return None
            plan = plan.resolve(choice, self.fs)
            if plan.conflicts:
                self.dialogs.info(plan.title, "Some items cannot be overwritten (folders, or the item itself). "
                                              "Choose Skip or Keep Both.")
                return None
            if not plan.ops:
                return None
        return plan

    def _transfer(self, move: bool) -> None:
        sources = self.active.targets()
        if not sources or self.busy:
            return
        dest = self.other.path
        plan = (plan_move if move else plan_copy)(self.fs, sources, dest)
        plan = self._settle(plan)
        if plan is None or not self.dialogs.confirm(plan.title, self._summary(plan, dest), plan.title):
            return
        self._run(plan, unmark=sources)

    def copy(self) -> None:
        self._transfer(move=False)

    def move(self) -> None:
        self._transfer(move=True)

    def rename(self) -> None:
        entry = self.active.current_entry()
        if entry is None or self.busy:
            return
        old = os.path.basename(entry.path)
        new = self.dialogs.ask_text("Rename", "New name:", old)
        if not new or new == old:
            return
        plan = plan_rename(self.fs, entry.path, new)
        if plan.conflicts:
            self.dialogs.info("Rename", f"An item named {new} already exists here.")
            return
        plan = self._settle(plan)
        if plan is not None:
            self._run(plan, select=new)

    def new_folder(self) -> None:
        name = self.dialogs.ask_text("New Folder", "Folder name:")
        if not name:
            return
        why = check_name(name)
        if why:
            self.dialogs.info("New Folder", why[0].upper() + why[1:] + ".")
            return
        path = os.path.join(self.active.path, name)
        try:
            self.fs.mkdir(path)
        except FileExistsError:
            self.dialogs.info("New Folder", f"An item named {name} already exists here.")
            return
        except OSError as e:
            self.dialogs.info("New Folder", f"Could not create the folder: {e.strerror or e}")
            return
        self.undo_log.push(UndoAction("New folder", [Step("created_dir", path)]))
        self.active.set_folder(self.active.path, select=name)
        if self.other.path == self.active.path:
            self.other.refresh()

    def delete(self, permanent: bool = False) -> None:
        sources = self.active.targets()
        if not sources or self.busy:
            return
        plan = plan_delete(self.fs, sources, to_trash=not permanent)
        if plan.blocking or not plan.ops:
            self._settle(plan)
            return
        names = "\n".join(os.path.basename(op.src) for op in plan.ops[:6])
        more = "" if len(plan.ops) <= 6 else f"\nand {len(plan.ops) - 6} more"
        if permanent:
            ok = self.dialogs.confirm("Delete Permanently", f"Delete {len(plan.ops)} item(s) permanently? "
                                      f"This cannot be undone.\n\n{names}{more}", "Delete permanently")
        else:
            ok = self.dialogs.confirm("Delete", f"Move {len(plan.ops)} item(s) to the {BIN}?\n\n{names}{more}", "Delete")
        if ok:
            self._run(plan)

    def undo(self) -> None:
        if self.busy:
            return
        report = self.undo_log.undo_last(self.fs)
        if report is None:
            self._say("Nothing to undo")
            return
        self.selection.remap(report.moved)
        self.selection.remove(report.removed)
        self.refresh()
        if report.problems:
            self.dialogs.info("Undo " + report.label.lower(),
                              "Some steps could not be undone:\n" + "\n".join(report.problems[:10]))
        else:
            self._say(f"Undid: {report.label}")

    # running a plan -----------------------------------------------------------------------------
    def _run(self, plan: Plan, *, unmark: Optional[list] = None, select: str = "") -> None:
        self.busy = True
        holder: dict = {}
        box = self.dialogs.make_progress(plan.title, lambda: holder["job"].cancel() if "job" in holder else None)

        def finished(job: Job) -> None:
            box.close()
            self.busy = False
            self._job = None
            self._report(job, unmark)
            keep = select or self.active.current_name()
            self.active.set_folder(self.active.path, select=keep)
            self.other.refresh()

        job = run_plan_job(self.runner, plan, self.fs, selection=self.selection, undo_log=self.undo_log,
                           on_progress=box.update, on_done=finished,
                           **({} if self.trasher is None else {"trasher": self.trasher}))
        holder["job"] = job
        self._job = job

    def _report(self, job: Job, unmark: Optional[list]) -> None:
        if job.state is JobState.FAILED:
            self.dialogs.info("Operation failed", str(job.error))
            return
        result = job.result
        if result.failed:
            lines = [f"{os.path.basename(r.op.src or r.op.dst)}: {r.error}" for r in result.failed[:10]]
            self.dialogs.info("Some items failed", "\n".join(lines))
        elif job.state is JobState.CANCELLED:
            self._say(f"Cancelled. {len(result.done)} step(s) were done; Ctrl+Z undoes them.")
        else:
            if unmark:
                self.selection.remove(unmark)
            self._say("Done")

    # session ----------------------------------------------------------------------------------------
    def _restore(self, start) -> None:
        home = os.path.expanduser("~")
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1100, 640)
        for panel, given, key in ((self.left, start[0], "left"), (self.right, start[1], "right")):
            path = given or self.settings.value(f"panel/{key}", home) or home
            if not panel.set_folder(path):
                panel.set_folder(home)
            state = self.settings.value(f"panel/{key}_header")
            if state is not None:
                panel.table.horizontalHeader().restoreState(state)
        sizes = self.settings.value("window/split")
        if sizes:
            self.split.setSizes([int(s) for s in sizes])

    def closeEvent(self, event) -> None:
        if self._job is not None:
            self._job.cancel()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/split", self.split.sizes())
        self.settings.setValue("panel/left", self.left.path)
        self.settings.setValue("panel/right", self.right.path)
        self.settings.setValue("panel/left_header", self.left.table.horizontalHeader().saveState())
        self.settings.setValue("panel/right_header", self.right.table.horizontalHeader().saveState())
        self.settings.sync()
        self.runner.shutdown(wait=True)
        super().closeEvent(event)
