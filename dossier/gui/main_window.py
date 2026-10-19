"""The commander window: two panels, one shared selection, F-key bar, status line.

Every command works on the marked items, or the item under the cursor when nothing is marked
(S4), and goes through the core's plans: planned, confirmed, run in the background with progress
and cancel, undoable with Ctrl+Z.
"""
from __future__ import annotations

import os
import shutil
import threading
from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QSettings, QSize, QStandardPaths, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QSplitter,
                             QToolButton, QVBoxLayout, QWidget)

from ..core.ops import (ExecOptions, Kind, Plan, Resolution, check_name, plan_copy, plan_delete, plan_move, plan_rename)
from ..core.home import ADD_NETWORK, HomeFileSystem, HomeProvider, RouterFileSystem, removable_from_home
from ..core.commandline import Placeholders, expand, run_command
from ..core import patterns, zipfs
from ..core.platform import IS_WINDOWS, has_scheme, is_elevated, machine_name, path_key, set_window_border
from ..core.selection import SelectionStore
from ..core.version import APP_NAME, APP_REPO_URL, APP_VERSION
from ..core.stallwatch import StallWatch
from ..core.textedit import BinaryFile, EncodingProblem, FileTooLarge, load_document
from ..core.terminals import (UnsafeArgument, builtin_profiles, default_launcher, default_profile, detect,
                              session_launch)
from ..core.undo_log import Step, UndoAction, UndoLog
from ..core.vfs import FileSystem, LocalFileSystem
from ..core.worker import Job, JobRunner, JobState, run_plan_job
from .appicon import app_icon
from .command_line import CommandLine
from .dialogs import Dialogs
from . import file_clipboard, icon_set, theme
from .models import human_size
from .panel import Panel
from .qt_bridge import QtDispatcher
from .theme import ThemeManager
from .viewer import TextViewerWindow

BIN = "recycle bin" if IS_WINDOWS else "trash"
STAT_LIMIT = 200      # at most this many sizes are read from the disk for one status line
SUMMARY_ITEMS = 12    # the confirmation lists this many items, then says how many more
SIZE_LIMIT = 1000    # the status line sizes at most this many marked items


class _LastInput(QObject):
    """Remembers what the user last did, as a name: which key (never the letter typed) or a mouse click."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = ""

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            printable = bool(event.text()) and event.text().isprintable() and not (
                mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
            self.text = "a typed character" if printable else QKeySequence(int(mods.value) | key).toString()
        elif kind == QEvent.Type.MouseButtonPress:
            self.text = "a mouse click"
        return False


class MainWindow(QMainWindow):
    def __init__(self, fs: Optional[FileSystem] = None, *, settings_path: Optional[str] = None, start=(None, None),
                 dialogs=None, trasher=None, terminal_launcher=None, which=None) -> None:
        super().__init__()
        self.elevated = is_elevated()
        self.setWindowTitle("Dossier")
        QApplication.setWindowIcon(app_icon())
        self.setWindowIcon(app_icon())
        self.fs = fs or LocalFileSystem()
        self.trasher = trasher
        self.launch_terminal = terminal_launcher or default_launcher      # tests pass a recorder: no windows, no UAC
        self._which = which or shutil.which
        self.dialogs = dialogs or Dialogs(self)
        self.settings = self._open_settings(settings_path)
        self.home_provider = HomeProvider(pins=lambda: self._saved_list("home/pins"),
                                          network=lambda: self._saved_list("home/network"))
        self.fs = RouterFileSystem(self.fs, HomeFileSystem(self.home_provider))     # home:// and the disk as one
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
        self.paused = False
        self._jobs: list = []                      # running first, then the ones waiting
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
        self.queue_label = QLabel()
        self.queue_label.hide()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.queue_label)
        status_row.addWidget(self.hint)
        self.build_label = QLabel(f"build {APP_VERSION}")
        self.build_label.setEnabled(False)
        self.build_label.setToolTip(f"{APP_NAME} build {APP_VERSION}")
        status_row.addWidget(self.build_label)

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
        self._build_help_menu()

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
            panel.folder_changed.connect(self._remember_sizes)
            panel.message.connect(self._say)
            panel.home_action.connect(self._home_action)
        self._sizes: dict = {}                       # path -> size (0 for a folder), from the listings on screen
        self.selection.subscribe(lambda _s: self._update_status())
        self.theme.changed.connect(self._on_theme_changed)

        self._restore(start)
        if self.act_stall_log.isChecked():
            self.set_stall_log(True)
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
                  self._action("Mark by Pattern...", "Ctrl+F", self.mark_by_pattern),
                  self._action("Unmark by Pattern...", "Ctrl+Shift+F", lambda: self.mark_by_pattern(False)),
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
        view_menu.addAction(self._action("Home Page", "Alt+Home", lambda: self.active.go_home()))
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
        for a in (self._action("Copy Files to Clipboard", "Ctrl+C", self.clip_copy),
                  self._action("Cut Files to Clipboard", "Ctrl+X", self.clip_cut),
                  self._action("Paste Files Here", "Ctrl+V", self.clip_paste)):
            commands.addAction(a)
        commands.addSeparator()
        for a in (self._action("Pause or Resume Operations", "Ctrl+Shift+P", self.toggle_pause),
                  self._action("Cancel Waiting Operations", None, self.cancel_waiting)):
            commands.addAction(a)
        commands.addSeparator()
        for a in (self._action("Pin Folder to Home Page", "Ctrl+D", self.pin_folder),
                  self._action("Add Network Location...", None, self.add_network_location)):
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
        limit_menu = view.addMenu("Copy Speed Limit")
        limit_group = QActionGroup(self)
        limit_group.setExclusive(True)
        self.limit_actions = {}
        current = str(self.settings.value("copy/limit_mb", "0") or "0")
        for mb, label in ((0, "Unlimited"), (1, "1 MB/s"), (5, "5 MB/s"), (20, "20 MB/s"), (50, "50 MB/s")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(float(current) == mb)
            act.triggered.connect(lambda _c=False, m=mb: self.settings.setValue("copy/limit_mb", m))
            limit_group.addAction(act)
            limit_menu.addAction(act)
            self.limit_actions[mb] = act
        self.act_verify = QAction("Verify Copies After Copying", self)
        self.act_verify.setCheckable(True)
        self.act_verify.setChecked(str(self.settings.value("copy/verify", "false")).lower() == "true")
        self.act_verify.toggled.connect(lambda on: self.settings.setValue("copy/verify", "true" if on else "false"))
        view.addAction(self.act_verify)
        self.act_ask_error = QAction("Ask When a File Cannot Be Copied", self)
        self.act_ask_error.setCheckable(True)
        self.act_ask_error.setChecked(str(self.settings.value("copy/ask_on_error", "false")).lower() == "true")
        self.act_ask_error.toggled.connect(lambda on: self.settings.setValue("copy/ask_on_error", "true" if on else "false"))
        view.addAction(self.act_ask_error)
        slow_menu = view.addMenu("Slowness Log")
        self.act_stall_log = QAction("Record Slow Moments (window stalls over 200 ms)", self)
        self.act_stall_log.setCheckable(True)
        self.act_stall_log.setChecked(str(self.settings.value("debug/stall_log", "false")).lower() == "true")
        self.act_stall_log.toggled.connect(self.set_stall_log)
        slow_menu.addAction(self.act_stall_log)
        slow_menu.addAction(self._action("Open the Log", None, self.open_stall_log))
        slow_menu.addAction(self._action("Delete the Log", None, self.delete_stall_log))
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

    def _tint_window_border(self) -> None:
        """Windows 11 draws a thin grey border round every window; it shows as a line beside the gold panel
        frame, so this window asks for none."""
        if self.isVisible():
            set_window_border(int(self.winId()), None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tint_window_border()

    def _on_theme_changed(self) -> None:
        self._tint_window_border()
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
        changed = getattr(self, "active", None) is not panel
        self.active = panel
        self.left.set_active(panel is self.left)
        self.right.set_active(panel is self.right)
        if hasattr(self, "prompt"):
            self._update_prompt()
        self._update_title()
        if changed:                                  # the other panel's marks are what the line is about now
            self._update_status()

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
        if self._home_blocked("View"):
            return
        paths = []
        for p in self.active.targets():
            try:
                if not self.fs.stat(p).is_dir:
                    paths.append(p if not has_scheme(p) else zipfs.local_copy(self.fs, p))   # the viewer reads real files
            except OSError as e:
                self.dialogs.info("View", f"Cannot read {self.fs.basename(p)}: {e.strerror or e}")
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
        if path is None and self._home_blocked("Edit"):
            return
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
        if has_scheme(path):
            self.dialogs.info("Edit", "Items inside an archive are read-only. Copy the file out to edit it.")
            return
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
        if self._home_blocked("Command"):
            return
        if self.profile is None:
            self.dialogs.info("Command", "No command interpreter was found.")
            return
        entry = self.active.current_entry()
        ph = Placeholders(current_name=self.fs.basename(entry.path) if entry else "",
                          current_path=entry.path if entry else "",
                          marked=tuple(self.active.marked_here()), folder=self.active.path, other=self.other.path)
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

    # the Home page -------------------------------------------------------------------------------------
    def _saved_list(self, key: str) -> list:
        value = self.settings.value(key, [])
        return [str(v) for v in (value if isinstance(value, list) else [value]) if v]

    def _save_list(self, key: str, items: list) -> None:
        self.settings.setValue(key, items)
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()

    def _home_blocked(self, what: str) -> bool:
        """True (after saying why) when the active panel shows the Home page: its entries are shortcuts, not files."""
        if self.active.is_home:
            self.dialogs.info(what, "The Home page lists shortcuts, not files. Open a folder first.")
            return True
        return False

    def _home_action(self, path: str) -> None:
        if path == ADD_NETWORK:
            self.add_network_location()

    def pin_folder(self) -> None:
        """Pin the active panel's folder to the Home page."""
        if self.active.is_home or not self.active.path:
            self.dialogs.info("Pin", "Open the folder you want to pin first.")
            return
        path = self.active.path
        pins = self._saved_list("home/pins")
        if any(path_key(p) == path_key(path) for p in pins):
            self._say(f"{path} is already on the Home page")
            return
        self._save_list("home/pins", pins + [path])
        self._say(f"Pinned {path} to the Home page")

    def add_network_location(self) -> None:
        """Save the address of a network folder on the Home page. Nothing is contacted: the address is only
        stored, and opened when the user opens it."""
        text = self.dialogs.ask_text("Add Network Location", "Address, for example \\\\server\\share:")
        if not text or not text.strip():
            return
        address = text.strip()
        if IS_WINDOWS and address.startswith("//"):
            address = address.replace("/", "\\")
        if "://" in address:
            self.dialogs.info("Add Network Location", "Only addresses that open as a folder can be saved for now, "
                              "such as \\\\server\\share. Servers (SFTP, WebDAV, FTP) are planned.")
            return
        saved = self._saved_list("home/network")
        if any(path_key(a) == path_key(address) for a in saved):
            self._say(f"{address} is already on the Home page")
            return
        self._save_list("home/network", saved + [address])
        self._say(f"Saved {address} on the Home page")

    def remove_from_home(self) -> None:
        """Take a pinned folder or a saved network location off the Home page. The folder itself is not touched."""
        row = self.active.table.currentIndex().row()
        entry = self.active.model.entry_at(row)
        if entry is None or not removable_from_home(entry.kind):
            self.dialogs.info("Remove", "Only pinned folders and saved network locations can be removed "
                              "from the Home page.")
            return
        if not self.dialogs.confirm("Remove from the Home page",
                                    f"Remove {entry.name} from the Home page?\n\nThe folder itself is not touched.",
                                    "Remove"):
            return
        key = "home/pins" if entry.kind == "pin" else "home/network"
        self._save_list(key, [p for p in self._saved_list(key) if path_key(p) != path_key(entry.path)])
        self._say(f"Removed {entry.name} from the Home page")

    # marks -------------------------------------------------------------------------------
    def toggle_mark(self) -> None:
        if self.active.is_home:
            return                                   # entries of the Home page are shortcuts: nothing to mark
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

    def mark_by_pattern(self, mark: bool = True) -> None:
        """Ctrl+F: ask for wildcard patterns and mark (or, with Ctrl+Shift+F, unmark) the matching items of the
        active panel. Files by default; a pattern ending in / is for folders."""
        if self.active.is_home:
            return
        title = "Mark by Pattern" if mark else "Unmark by Pattern"
        last = str(self.settings.value("mark/pattern", "*.*") or "*.*")
        text = self.dialogs.ask_text(title, "Pattern (for example *.jpg;*.png  or  *.log !debug*  or  backup*/ for folders):", last)
        if not text or not text.strip():
            return
        why = patterns.describe(text)
        if why:
            self.dialogs.info(title, why)
            return
        self.settings.setValue("mark/pattern", text.strip())
        wanted = patterns.parse(text, case_sensitive=self.fs.case_sensitive)
        model = self.active.model
        hits = []
        for r in range(model.entry_count()):
            e = model.entry_at(r)
            if e is not None and not model.is_up_row(r) and e.kind not in ("header", "action") \
                    and wanted.matches(self.fs.basename(e.path), e.is_dir):
                hits.append(e.path)
        if mark:
            self.selection.add(hits)
        else:
            self.selection.remove(hits)
        n = len(hits)
        self._say(f"{'Marked' if mark else 'Unmarked'} {n} item{'s' if n != 1 else ''} matching {text.strip()}" if n
                  else f"Nothing matches {text.strip()}")

    def select_all(self) -> None:
        if self.active.is_home:
            return
        self.selection.add(self._entry_paths())

    def invert_selection(self) -> None:
        if self.active.is_home:
            return
        self.selection.invert(self._entry_paths())

    def _remember_sizes(self, panel) -> None:
        """Keep the sizes of the items just listed, so the status line never has to ask the disk for them."""
        model = panel.model
        if model.is_home:
            return
        for r in range(model.entry_count()):
            e = model.entry_at(r)
            if e is not None and not model.is_up_row(r):
                self._sizes[e.path] = 0 if e.is_dir else e.size
        if len(self._sizes) > 200_000:               # a long session: start again from what is on screen
            self._sizes.clear()

    def _update_status(self) -> None:
        here = self.active.marked_here()
        elsewhere = len(self.selection) - len(here)
        note = f"; {elsewhere} more in the other panel (not used here)" if elsewhere > 0 else ""
        if not here:
            self.status.setText("No items marked here" + note)
            return
        total, asked = 0, 0
        for p in here[:SIZE_LIMIT]:
            size = self._sizes.get(p)
            if size is None:                         # not in a listing we kept: ask once, remember
                if asked >= STAT_LIMIT:
                    continue
                asked += 1
                try:
                    e = self.fs.stat(p)
                    size = 0 if e.is_dir else e.size
                except OSError:
                    size = 0
                self._sizes[p] = size
            total += size
        more = "" if len(here) <= SIZE_LIMIT and asked < STAT_LIMIT else "+"
        self.status.setText(f"{len(here)} marked, {human_size(total)}{more}, in this panel{note}")

    # commands -------------------------------------------------------------------------------
    def _summary(self, plan: Plan, dest: str = "", sources=None, origin: str = "") -> str:
        """The text of the confirmation: how much, from where to where, and the items themselves (those of the
        panel the command was started from), folders with what is in them."""
        n_files = len([op for op in plan.ops if op.kind.value in ("copy", "move") and not op.is_dir])
        size = sum(op.size for op in plan.ops if op.kind.value in ("copy", "move") and not op.is_dir)
        top = list(sources) if sources else []
        count = len(top) if top else len([op for op in plan.ops if op.kind.value != "mkdir"])
        text = f"{plan.title} {count} item{'s' if count != 1 else ''}"
        if size:
            text += f" ({human_size(size)}" + (f", {n_files} files" if n_files != count else "") + ")"
        if origin:
            text += f"{chr(10)}from {origin}"
        if dest:
            text += f"{chr(10)}to {dest}"
        if top:
            sep = self.fs.sep
            lines = []
            for src in top[:SUMMARY_ITEMS]:
                below = [op for op in plan.ops if op.src == src or op.src.startswith(src.rstrip(sep) + sep)]
                files = [op for op in below if not op.is_dir and op.kind.value in ("copy", "move")]
                name = self.fs.basename(src)
                if any(op.src != src for op in below):                      # a folder with files in it
                    lines.append(f"  {name}{sep}   {len(files)} files, {human_size(sum(op.size for op in files))}")
                elif len(files) == 1 and files[0].src == src:
                    lines.append(f"  {name}   {human_size(files[0].size)}")
                else:
                    lines.append(f"  {name}")
            if len(top) > SUMMARY_ITEMS:
                lines.append(f"  ... and {len(top) - SUMMARY_ITEMS} more")
            text += chr(10) * 2 + chr(10).join(lines)
        if plan.warnings:
            text += chr(10) * 2 + chr(10).join(plan.warnings[:8])
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
            names = [self.fs.basename(plan.ops[i].dst) for i in plan.conflicts[:6]]
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
        if self._home_blocked("Move" if move else "Copy"):
            return
        sources = self.active.targets()
        if not sources:
            return                                   # a busy window queues the operation
        dest = self.other.path
        plan = (plan_move if move else plan_copy)(self.fs, sources, dest)
        plan = self._settle(plan)
        if plan is None:
            return
        verify = self.dialogs.confirm_transfer(plan.title, self._summary(plan, dest, sources, self.active.path), plan.title,
                                                self.act_verify.isChecked())
        if verify is None:
            return
        self.act_verify.setChecked(verify)           # the choice is remembered for the next time (and shown in Settings)
        self._run(plan, unmark=sources)

    def copy(self) -> None:
        self._transfer(move=False)

    def move(self) -> None:
        self._transfer(move=True)

    # the system clipboard: Ctrl+C / Ctrl+X / Ctrl+V, also with Explorer and other file managers ----------
    def _to_clipboard(self, cut: bool) -> None:
        if self.active.is_home:
            return
        sources = self.active.targets()
        if not sources:
            return
        file_clipboard.put(sources, cut)
        n = len(sources)
        self._say(f"{'Cut' if cut else 'Copied'} {n} item{'s' if n != 1 else ''} to the clipboard")

    def clip_copy(self) -> None:
        self._to_clipboard(False)

    def clip_cut(self) -> None:
        self._to_clipboard(True)

    def clip_paste(self) -> None:
        if self._home_blocked("Paste"):
            return
        sources, cut = file_clipboard.get()
        if not sources:
            self._say("The clipboard holds no files")
            return
        dest = self.active.path
        def there(path: str) -> bool:
            try:
                self.fs.stat(path)
                return True
            except OSError:
                return False
        sources = [s for s in sources if there(s)]
        if not sources:
            self.dialogs.info("Paste", "The copied items no longer exist.")
            return
        plan = (plan_move if cut else plan_copy)(self.fs, sources, dest)
        plan = self._settle(plan)
        if plan is None:
            return
        if cut:
            self._run(plan, unmark=sources)
            file_clipboard.clear_if_ours(sources)
        else:
            self._run(plan, unmark=sources)

    def rename(self) -> None:
        if self._home_blocked("Rename"):
            return
        entry = self.active.current_entry()
        if entry is None or self.busy:
            return
        old = self.fs.basename(entry.path)
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
        if self.active.is_home:
            self.add_network_location()              # on the Home page F7 adds an entry instead of a folder
            return
        if not self.fs.is_writable(self.active.path):
            self.dialogs.info("New Folder", "This folder is read-only (an archive cannot be changed yet).")
            return
        name = self.dialogs.ask_text("New Folder", "Folder name:")
        if not name:
            return
        why = check_name(name)
        if why:
            self.dialogs.info("New Folder", why[0].upper() + why[1:] + ".")
            return
        path = self.fs.join(self.active.path, name)
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
        if self.active.is_home:
            self.remove_from_home()                  # only shortcuts can go, and only from the page, never the folder
            return
        sources = self.active.targets()
        if not sources:
            return
        plan = plan_delete(self.fs, sources, to_trash=not permanent)
        if plan.blocking or not plan.ops:
            self._settle(plan)
            return
        names = "\n".join(self.fs.basename(op.src) for op in plan.ops[:6])
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
        """Queue a plan. Plans run one after the other (one disk is never fought over); the progress box of a
        plan appears when it starts, and a queued plan waits until the ones before it are done."""
        self.busy = True
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
            if "box" in shown:
                shown["box"].close()
            if job in self._jobs:
                self._jobs.remove(job)
            self.busy = bool(self._jobs)
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
        """The copy settings: the speed limit and whether a failing file asks what to do."""
        try:
            limit = int(float(self.settings.value("copy/limit_mb", 0) or 0) * 1024 * 1024) or None
        except (TypeError, ValueError):
            limit = None
        options = ExecOptions(limit_bps=limit, on_item=on_item, verify=str(self.settings.value("copy/verify", "false")).lower() == "true")
        if str(self.settings.value("copy/ask_on_error", "false")).lower() == "true":
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

    def _build_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action(f"About {APP_NAME}...", None, self.about))

    def about(self) -> None:
        self.dialogs.info(f"About {APP_NAME}", chr(10).join([
            f"{APP_NAME}, a dual-pane file manager",
            f"Build {APP_VERSION}",
            "",
            APP_REPO_URL,
            "",
            "Free software under the GPL, version 3 or later.",
            "Made with Python and Qt (PyQt6), the QScintilla editor component, and the Tabler and Lucide icon sets.",
            "The full credits are in CREDITS.md."]))

    # the slowness log (opt-in) --------------------------------------------------------------------------
    @property
    def stall_log_path(self) -> str:
        return os.path.join(os.path.dirname(self.settings.fileName()), "slowness.log")

    def _stall_context(self) -> str:
        parts = []
        if getattr(self, "_last_input", None) is not None and self._last_input.text:
            parts.append("last input: " + self._last_input.text)
        waiting = sum(1 for j in self._jobs if j.state is JobState.QUEUED)
        if self._jobs:
            parts.append(f"operations: 1 running{', ' + str(waiting) + ' waiting' if waiting else ''}")
        parts.append(f"marked: {len(self.selection)}")
        return "  |  ".join(parts)

    def set_stall_log(self, on: bool) -> None:
        """Start or stop watching the window for stalls. Off by default; nothing is recorded while it is off."""
        self.settings.setValue("debug/stall_log", "true" if on else "false")
        watch = getattr(self, "_stall_watch", None)
        if watch is not None:
            watch.stop()
            self._stall_watch = None
            self._heartbeat.stop()
            QApplication.instance().removeEventFilter(self._last_input)
        if on:
            self._last_input = _LastInput(self)
            QApplication.instance().installEventFilter(self._last_input)
            self._stall_watch = StallWatch(self.stall_log_path, context=self._stall_context)
            self._heartbeat = QTimer(self)
            self._heartbeat.setInterval(40)
            self._heartbeat.timeout.connect(self._stall_watch.beat)
            self._stall_watch.start()
            self._heartbeat.start()

    def open_stall_log(self) -> None:
        if not os.path.isfile(self.stall_log_path):
            self.dialogs.info("Slowness Log", "Nothing has been recorded yet. Switch on Record Slow Moments, use "
                                              "the program, and the moments it stalls for more than 200 ms are written here.")
            return
        self.edit_file(self.stall_log_path)

    def delete_stall_log(self) -> None:
        if not os.path.isfile(self.stall_log_path):
            self._say("There is no slowness log")
            return
        if self.dialogs.confirm("Delete the Slowness Log", "Delete the record of slow moments?", "Delete"):
            for editor in list(self.editors):
                if os.path.normcase(editor.doc.path) == os.path.normcase(self.stall_log_path):
                    editor.close()
            try:
                os.remove(self.stall_log_path)
                self._say("Slowness log deleted")
            except OSError as e:
                self.dialogs.info("Slowness Log", f"Could not delete it: {e.strerror or e}")

    def closeEvent(self, event) -> None:
        watch = getattr(self, "_stall_watch", None)
        if watch is not None:
            watch.stop()
        for v in list(self.viewers):
            v.close()
        for ed in list(self.editors):
            if not ed.close():                       # the user cancelled a save question: stay open
                event.ignore()
                return
        for job in list(self._jobs):
            job.cancel()
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
