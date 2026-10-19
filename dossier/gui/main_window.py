"""The commander window: two panels, one shared selection, F-key bar, status line.

Every command works on the marked items, or the item under the cursor when nothing is marked
(S4), and goes through the core's plans: planned, confirmed, run in the background with progress
and cancel, undoable with Ctrl+Z.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

from PyQt6.QtCore import QSettings, QSize, QStandardPaths, Qt
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QSplitter,
                             QToolButton, QVBoxLayout, QWidget)

from ..core.ops import (Plan, Resolution, check_name, plan_copy, plan_delete, plan_move, plan_rename)
from ..core.commandline import Placeholders, expand, run_command
from ..core.platform import IS_WINDOWS, is_elevated, machine_name
from ..core.selection import SelectionStore
from ..core.textedit import BinaryFile, EncodingProblem, FileTooLarge, load_document
from ..core.terminals import (UnsafeArgument, builtin_profiles, default_launcher, default_profile, detect,
                              session_launch)
from ..core.undo_log import Step, UndoAction, UndoLog
from ..core.vfs import FileSystem, LocalFileSystem
from ..core.worker import Job, JobRunner, JobState, run_plan_job
from .command_line import CommandLine
from .dialogs import Dialogs
from . import icon_set, theme
from .models import human_size
from .panel import Panel
from .qt_bridge import QtDispatcher
from .theme import ThemeManager
from .viewer import TextViewerWindow

BIN = "recycle bin" if IS_WINDOWS else "trash"
SIZE_LIMIT = 1000    # the status line sizes at most this many marked items


class MainWindow(QMainWindow):
    def __init__(self, fs: Optional[FileSystem] = None, *, settings_path: Optional[str] = None, start=(None, None),
                 dialogs=None, trasher=None, terminal_launcher=None, which=None) -> None:
        super().__init__()
        self.elevated = is_elevated()
        self.setWindowTitle("Dossier")
        self.fs = fs or LocalFileSystem()
        self.trasher = trasher
        self.launch_terminal = terminal_launcher or default_launcher      # tests pass a recorder: no windows, no UAC
        self._which = which or shutil.which
        self.dialogs = dialogs or Dialogs(self)
        self.settings = self._open_settings(settings_path)
        icon_set.set_user_dir(os.path.join(os.path.dirname(self.settings.fileName()), "icon-sets"))
        icon_set.use(str(self.settings.value("view/icon_set", icon_set.DEFAULT_SET)))
        self.theme = ThemeManager(QApplication.instance(), str(self.settings.value("view/scheme", "auto")))

        self.dispatcher = QtDispatcher(self)
        self.selection = SelectionStore(dispatch=self.dispatcher)
        self.undo_log = UndoLog()
        self.runner = JobRunner(self.dispatcher)
        self.cmd_runner = JobRunner(self.dispatcher)      # commands wait on their own thread, never behind a copy
        self.profiles = detect(builtin_profiles(), self._which)
        self.profile = self._chosen_profile()
        self.windows_terminal = self._which("wt.exe") if IS_WINDOWS else None
        self.busy = False
        self._job: Optional[Job] = None
        self.viewers: list = []
        self.editors: list = []

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
        box.addWidget(self._build_command_row())
        box.addWidget(self.fkeys)
        box.addLayout(status_row)
        self.setCentralWidget(central)
        self._build_menus()

        for panel in (self.left, self.right):
            panel.activated.connect(self._set_active)
            panel.table.switch_panel.connect(self.switch_panel)
            panel.table.mark_toggle.connect(self.toggle_mark)
            panel.table.space.connect(self._space_pressed)
            panel.table.type_text.connect(self._type_to_command)
            panel.enter_hook = self._enter_runs_command
            panel.backspace_hook = self._backspace_edits_command
            panel.folder_changed.connect(lambda _p: self._update_prompt())
            panel.folder_changed.connect(lambda _p: self._update_title())
            panel.message.connect(self._say)
        self.selection.subscribe(lambda _s: self._update_status())
        self.theme.changed.connect(self._on_theme_changed)

        self._restore(start)
        self.set_drive_style(str(self.settings.value("view/drive_selector", "menu")))
        self.set_notes_visible(self.act_notes.isChecked())
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
        self.act_view = self._action("View", "F3", self.view_file)
        self.act_edit = self._action("Edit", "F4", self.edit_file)
        self.act_rename = self._action("Rename", "F2", self.rename)
        self.act_copy = self._action("Copy to Other Panel", "F5", self.copy)
        self.act_move = self._action("Move to Other Panel", "F6", self.move)
        self.act_mkdir = self._action("New Folder", "F7", self.new_folder)
        self.act_delete = self._action("Delete", ["F8", "Delete"], self.delete)
        self.act_delete_perm = self._action("Delete Permanently", "Shift+F8", lambda: self.delete(permanent=True))
        quit_ = self._action("Quit", "Ctrl+Q", self.close)
        for a in (self.act_view, self.act_edit, self.act_rename, self.act_copy, self.act_move, self.act_mkdir, self.act_delete,
                  self.act_delete_perm):
            files.addAction(a)
        files.addSeparator()
        files.addAction(quit_)
        mark = bar.addMenu("&Mark")
        for a in (self._action("Select All", "Ctrl+A", self.select_all),
                  self._action("Invert Selection", "*", self.invert_selection),
                  self._action("Deselect All", "Ctrl+Shift+A", self.selection.clear)):
            mark.addAction(a)
        view_menu = bar.addMenu("&View")
        self.view_mode_actions = {}
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        details = QAction("Details", self)
        details.setCheckable(True)
        details.setChecked(True)
        mode_group.addAction(details)
        view_menu.addAction(details)
        self.view_mode_actions["details"] = details          # List, Icons and Thumbnails join here when built
        view_menu.addSeparator()
        self.act_notes = QAction("Folder Notes", self)
        self.act_notes.setCheckable(True)
        self.act_notes.setChecked(str(self.settings.value("view/notes", "true")).lower() != "false")
        self.act_notes.toggled.connect(self.set_notes_visible)
        view_menu.addAction(self.act_notes)
        view_menu.addAction(self._action("Refresh", "Ctrl+R", self.refresh))
        tabs_menu = view_menu.addMenu("Tabs")
        for text, keys, slot in (("New Tab", "Ctrl+T", lambda: self.active.new_tab()),
                                 ("Close Tab", "Ctrl+W", lambda: self.active.close_tab(self.active.tabs.currentIndex())),
                                 ("Next Tab", "Ctrl+Tab", lambda: self.active.next_tab(1)),
                                 ("Previous Tab", "Ctrl+Shift+Tab", lambda: self.active.next_tab(-1)),
                                 ("Open Folder in New Tab", "Ctrl+Return", lambda: self.active.open_current(True))):
            tabs_menu.addAction(self._action(text, keys, slot))
        commands = bar.addMenu("&Commands")
        for a in (self._action("Undo", "Ctrl+Z", self.undo), self._action("Swap Panels", "Ctrl+U", self.swap_panels)):
            commands.addAction(a)
        commands.addSeparator()
        for a in (self._action("Terminal Here", "Ctrl+Shift+T", self.open_terminal),
                  self._action("Administrator Terminal Here", None, lambda: self.open_terminal(admin=True))):
            commands.addAction(a)
        view = bar.addMenu("&Settings")
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
        self.icon_menu = view.addMenu("Icon Set")
        self.icon_group = QActionGroup(self)
        self.icon_group.setExclusive(True)
        self.icon_set_actions = {}
        self.icon_menu.aboutToShow.connect(self._rebuild_icon_menu)   # picks up sets the user just added
        self._rebuild_icon_menu()
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

    def _build_fkey_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._fkey_buttons = []
        self._fkey_icons = []
        for label, icon_name_, slot in (("F2 Rename", "pencil", lambda: self.rename()),
                                        ("F3 View", "file-text", lambda: self.view_file()),
                                        ("F4 Edit", "file-code", lambda: self.edit_file()),
                                        ("F5 Copy", "copy", lambda: self.copy()),
                                        ("F6 Move", "arrows-right-left", lambda: self.move()),
                                        ("F7 Folder", "folder-plus", lambda: self.new_folder()),
                                        ("F8 Delete", "trash", lambda: self.delete())):
            b = QPushButton(label)
            b.setFlat(True)
            b.setIconSize(QSize(16, 16))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(b, 1)
            self._fkey_buttons.append(b)
            self._fkey_icons.append(icon_name_)
        self._apply_fkey_icons()
        return bar

    def _apply_fkey_icons(self) -> None:
        color = theme.current()["fg"]
        for b, name in zip(self._fkey_buttons, self._fkey_icons):
            b.setIcon(icon_set.icon(name, color))

    def _on_theme_changed(self) -> None:
        icon_set.clear_cache()
        self._apply_fkey_icons()
        self._style_terminal_button()
        for p in (self.left, self.right):
            p.restyle()

    # panels ----------------------------------------------------------------------------
    @property
    def other(self) -> Panel:
        return self.right if self.active is self.left else self.left

    def _set_active(self, panel: Panel) -> None:
        self.active = panel
        self.left.set_active(panel is self.left)
        self.right.set_active(panel is self.right)
        if hasattr(self, "prompt"):
            self._update_prompt()
        self._update_title()

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

    def _rebuild_icon_menu(self) -> None:
        for act in list(self.icon_set_actions.values()):
            self.icon_group.removeAction(act)
            self.icon_menu.removeAction(act)
            act.deleteLater()
        self.icon_set_actions = {}
        for s in icon_set.available_sets():
            act = QAction(s.title + ("" if s.builtin else " (yours)"), self)
            act.setCheckable(True)
            act.setChecked(s.id == icon_set.active())
            act.setToolTip(s.licence)
            act.triggered.connect(lambda _c=False, sid=s.id: self.set_icon_set(sid))
            self.icon_group.addAction(act)
            self.icon_menu.addAction(act)
            self.icon_set_actions[s.id] = act

    def set_profile(self, profile_id: str) -> None:
        for p, path in self.profiles:
            if p.id == profile_id and path:
                self.profile = p
                self.settings.setValue("terminal/profile", profile_id)
                return

    def set_icon_set(self, set_id: str) -> None:
        if icon_set.use(set_id):
            self.settings.setValue("view/icon_set", set_id)
            self._on_theme_changed()          # clears the cache and repaints every icon
            if set_id in self.icon_set_actions:
                self.icon_set_actions[set_id].setChecked(True)

    def set_notes_visible(self, on: bool) -> None:
        for panel in (self.left, self.right):
            panel.set_notes_enabled(on)
        self.settings.setValue("view/notes", "true" if on else "false")

    def view_file(self) -> None:
        """F3: view the marked files (or the one under the cursor), stepping through them in one window."""
        paths = []
        for p in self.active.targets():
            try:
                if not self.fs.stat(p).is_dir:
                    paths.append(p)
            except OSError:
                pass
        if not paths:
            self.dialogs.info("View", "Select a file to view.")
            return
        win = TextViewerWindow(paths, 0, dispatch=self.dispatcher)
        self.viewers.append(win)
        win.edit_requested.connect(lambda p, replace: self.edit_file(p, replace))
        win.destroyed.connect(lambda _o=None, w=win: self.viewers.remove(w) if w in self.viewers else None)
        win.show()

    def edit_file(self, path: Optional[str] = None, show_replace: bool = False) -> None:
        """F4: open one file in the notepad. A file that is already open is brought forward, not opened twice."""
        if path is None:
            targets = [p for p in self.active.targets()]
            files = []
            for p in targets:
                try:
                    if not self.fs.stat(p).is_dir:
                        files.append(p)
                except OSError:
                    pass
            if len(files) != 1:
                self.dialogs.info("Edit", "Select one file to edit.")
                return
            path = files[0]
        for w in self.editors:
            if os.path.normcase(w.doc.path) == os.path.normcase(path):
                w.raise_()
                w.activateWindow()
                if show_replace:
                    w.bar.show_replace()
                return
        try:
            from .notepad import NotepadWindow
            doc = load_document(path)
        except ImportError:
            self.dialogs.info("Edit", "The editor needs the PyQt6-QScintilla package: pip install PyQt6-QScintilla")
            return
        except FileTooLarge as e:
            self.dialogs.info("Edit", f"{e}. Use View (F3) to read it, or an external editor to change it.")
            return
        except BinaryFile:
            self.dialogs.info("Edit", "This looks like a binary file, not text. Use View (F3).")
            return
        except (OSError, EncodingProblem) as e:
            self.dialogs.info("Edit", f"The file could not be opened: {getattr(e, 'strerror', None) or e}")
            return
        win = NotepadWindow(doc, self.dialogs, show_replace=show_replace)
        self.editors.append(win)
        win.closed.connect(lambda w: self.editors.remove(w) if w in self.editors else None)
        win.saved.connect(lambda _p: self.refresh())
        win.show()

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

    # command line and terminals --------------------------------------------------------------------
    def _chosen_profile(self):
        wanted = str(self.settings.value("terminal/profile", ""))
        for p, path in self.profiles:
            if p.id == wanted and path:
                return p
        return default_profile(self.profiles)

    def _build_command_row(self) -> QWidget:
        """One line under the panels: the prompt, the command line, and one Terminal button. The button opens a
        terminal in this folder; a right-click on it offers the administrator terminal and the interpreter."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)
        self.prompt = QLabel(">")
        self.cmdline = CommandLine()
        self.cmdline.returnPressed.connect(self.run_command_line)
        self.cmdline.escape_pressed.connect(lambda: self.active.table.setFocus())
        self.cmdline.tab_pressed.connect(lambda: self.active.table.setFocus())
        self.term_button = QToolButton()
        self.term_button.setAutoRaise(True)
        self.term_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.term_button.setIconSize(QSize(18, 18))
        self.term_button.setToolTip("Open a terminal in this folder (Ctrl+Shift+T). "
                                    "Right-click: administrator, interpreter.")
        self.term_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.term_button.clicked.connect(lambda: self.open_terminal())
        self.term_button.customContextMenuRequested.connect(
            lambda pos: self.build_terminal_menu().popup(self.term_button.mapToGlobal(pos)))
        self._style_terminal_button()
        lay.addWidget(self.prompt)
        lay.addWidget(self.cmdline, 1)
        lay.addWidget(self.term_button)
        return row

    def _style_terminal_button(self) -> None:
        self.term_button.setIcon(icon_set.icon("terminal-2", theme.current()["fg"]))

    def build_terminal_menu(self) -> QMenu:
        """The right-click menu of the Terminal button."""
        menu = QMenu(self)
        menu.addAction("Open as Administrator").triggered.connect(lambda _c=False: self.open_terminal(admin=True))
        sub = menu.addMenu("Interpreter")
        group = QActionGroup(menu)
        group.setExclusive(True)
        for p, path in self.profiles:
            act = sub.addAction(p.title if path else f"{p.title} (not found)")
            act.setCheckable(True)
            act.setEnabled(bool(path))
            act.setChecked(self.profile is not None and p.id == self.profile.id)
            group.addAction(act)
            act.triggered.connect(lambda _c=False, prof=p: self.set_profile(prof.id))
        return menu

    def _update_title(self) -> None:
        """The file manager is titled 'Dossier <machine name>', so several computers' windows are told apart.
        (Viewer and notepad windows are titled 'Dossier, Subject - <file name>'.)"""
        self.setWindowTitle(f"Dossier {machine_name()}" + (" (Administrator)" if self.elevated else ""))

    def _update_prompt(self) -> None:
        text = self.active.path
        metrics = self.prompt.fontMetrics()
        self.prompt.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, 360) + ">")

    def _space_pressed(self) -> None:
        if self.cmdline.text():
            self.cmdline.insert(" ")
            self.cmdline.setFocus()
        else:
            self.toggle_mark()

    def _type_to_command(self, text: str) -> None:
        self.cmdline.setFocus()
        self.cmdline.insert(text)

    def _enter_runs_command(self) -> bool:
        if self.cmdline.text().strip():
            self.run_command_line()
            return True
        return False

    def _backspace_edits_command(self) -> bool:
        if self.cmdline.text():
            self.cmdline.setFocus()
            self.cmdline.backspace()
            return True
        return False

    def run_command_line(self) -> None:
        """Run what is typed under the panels in the active panel's folder, as the normal user."""
        text = self.cmdline.text().strip()
        if not text:
            return
        if self.profile is None:
            self.dialogs.info("Command", "No command interpreter was found.")
            return
        entry = self.active.current_entry()
        ph = Placeholders(current_name=os.path.basename(entry.path) if entry else "",
                          current_path=entry.path if entry else "",
                          marked=tuple(self.selection.paths()), folder=self.active.path, other=self.other.path)
        try:
            command = expand(text, ph, self.profile)
        except (UnsafeArgument, ValueError) as e:
            self.dialogs.info("Command", str(e))
            return                                             # the text stays so it can be corrected
        self.cmdline.remember(text)
        self.cmdline.clear()
        cwd, profile = self.active.path, self.profile
        self._say(f"Running: {command}")

        def finished(job: Job) -> None:
            if job.state is JobState.FAILED:
                self.dialogs.info("Command", f"The command could not be run: {job.error}")
                return
            res = job.result
            if res.finished:
                if res.output.strip():
                    self.dialogs.show_output(command, res.output + ("\n[output cut]" if res.truncated else ""))
                self._say(f"Done (exit code {res.exit_code}): {command}")
            else:
                self._say(f"Still running (process {res.pid}): {command}")
            self.refresh()                                      # a command may have changed the files

        def ended_later(res) -> None:                           # from the watcher thread: hop to the GUI thread
            def show() -> None:
                if res.output.strip():
                    self.dialogs.show_output(command, res.output + ("\n[output cut]" if res.truncated else ""))
                self._say(f"Finished (exit code {res.exit_code}): {command}")
                self.refresh()
            self.dispatcher(show)

        self.cmd_runner.submit("Command",
                               lambda progress, cancel: run_command(profile, command, cwd, on_finish=ended_later),
                               on_done=finished)

    def open_terminal(self, admin: bool = False, profile=None) -> None:
        """Open an interactive session in the panel's folder. Administrator (the right-click menu of the
        Terminal button) means the system's own permission prompt (Windows) or ``sudo -s`` typed inside the
        terminal: Dossier never sees a password and never raises its own rights."""
        profile = profile or self.profile
        panel = self.active                          # for the other panel's folder: switch to it (Tab), then open
        if profile is None:
            self.dialogs.info("Terminal", "No command interpreter was found.")
            return
        if "://" in panel.path:
            self.dialogs.info("Terminal", "A terminal can only open in a folder on this computer.")
            return
        try:
            launch = session_launch(profile, panel.path, admin=admin, windows_terminal=self.windows_terminal,
                                    which=self._which)
            self.launch_terminal(launch)
        except (OSError, UnsafeArgument) as e:
            self.dialogs.info("Terminal", str(e))
            return
        self._say(("Administrator terminal" if admin else "Terminal") + f" opened in {panel.path}")

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
            saved = self.settings.value(f"panel/{key}_tabs", [])
            saved = [str(p) for p in (saved if isinstance(saved, list) else [saved]) if p]
            path = given or self.settings.value(f"panel/{key}", home) or home
            if not panel.set_folder(path):
                panel.set_folder(home)
            if saved and not given:                   # the saved tabs, unless the caller asked for a folder
                panel.restore_tabs(saved, int(self.settings.value(f"panel/{key}_tab", 0) or 0))
            state = self.settings.value(f"panel/{key}_header")
            if state is not None:
                panel.table.horizontalHeader().restoreState(state)
        sizes = self.settings.value("window/split")
        if sizes:
            self.split.setSizes([int(s) for s in sizes])

    def closeEvent(self, event) -> None:
        for v in list(self.viewers):
            v.close()
        for ed in list(self.editors):
            if not ed.close():                       # the user cancelled a save question: stay open
                event.ignore()
                return
        if self._job is not None:
            self._job.cancel()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/split", self.split.sizes())
        self.settings.setValue("panel/left", self.left.path)
        self.settings.setValue("panel/right", self.right.path)
        for key, panel in (("left", self.left), ("right", self.right)):
            self.settings.setValue(f"panel/{key}_tabs", panel.tab_paths())
            self.settings.setValue(f"panel/{key}_tab", panel.tabs.currentIndex())
        self.settings.setValue("panel/left_header", self.left.table.horizontalHeader().saveState())
        self.settings.setValue("panel/right_header", self.right.table.horizontalHeader().saveState())
        self.settings.sync()
        self.runner.shutdown(wait=True)
        super().closeEvent(event)
