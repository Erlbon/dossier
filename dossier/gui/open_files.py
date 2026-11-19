"""Enter or a double-click on a file: the built-in viewer, or the program Windows has for it (Settings > Opening Files).

The rule itself is ``core.viewmodes.opens_in_viewer``; this is the window's side: the setting, its menu, and the hook a panel calls.
Ctrl+Enter always does the opposite of the setting. Marking is untouched (Ctrl+click and Ctrl+Space still mark).
A script (``core/scripts.py``) runs on Enter unless Settings > Opening Files > Run Scripts on Enter is switched off; Ctrl+Enter then shows it.
The same menu chooses the editor for F4: Dossier's notepad, or a program of the user's (started with the file, as a tools-bar tool).
"""
from __future__ import annotations

import hashlib
import json
import os

from PyQt6.QtGui import QAction, QActionGroup

from ..core import bundles, scripts, terminals, tools, viewmodes
from ..core.platform import has_scheme
from .background import run_in_background


class OpenFilesMixin:
    """Part of ``MainWindow``."""

    def build_open_menu(self, parent_menu) -> None:
        menu = parent_menu.addMenu("Opening Files")
        menu.menuAction().setToolTip("What Enter and double-click do. Ctrl+Enter does the other thing.")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.open_actions = {}
        for key, label in viewmodes.OPEN_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.open_choice() == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_open_choice(k))
            group.addAction(act)
            menu.addAction(act)
            self.open_actions[key] = act
        menu.addSeparator()
        self.act_run_scripts = QAction("Run Scripts on Enter (" + ", ".join(scripts.extensions()) + ")", self)
        self.act_run_scripts.setCheckable(True)
        self.act_run_scripts.setChecked(self.run_scripts())
        self.act_run_scripts.setToolTip("Off: Enter shows a script in the viewer, as any text file, and Ctrl+Enter runs it")
        self.act_run_scripts.toggled.connect(self.set_run_scripts)
        menu.addAction(self.act_run_scripts)
        menu.addSeparator()
        editors = QActionGroup(self)
        editors.setExclusive(True)
        self.act_editor_notepad = QAction("Edit (F4) in Dossier's Notepad", self)
        self.act_editor_program = QAction("", self)
        for act in (self.act_editor_notepad, self.act_editor_program):
            act.setCheckable(True)
            editors.addAction(act)
            menu.addAction(act)
        self.act_editor_notepad.triggered.connect(lambda: self.set_editor_program(""))
        self.act_editor_program.triggered.connect(self.choose_editor_program)
        self._show_editor_choice()
        menu.addSeparator()
        self.act_text_header = QAction("Rules at the Top of a Name List (Batch Rename)", self)
        self.act_text_header.setCheckable(True)
        self.act_text_header.setChecked(self.text_rename_header())
        self.act_text_header.setToolTip("Tools > Batch Rename > Edit the Names as Text writes a few lines of rules above the names. "
                                        "Off: only the names.")
        self.act_text_header.toggled.connect(self.set_text_rename_header)
        menu.addAction(self.act_text_header)
        self.build_associations_menu(menu)         # Windows only: Dossier in Open With (card 69C)

    # the editor for F4 ------------------------------------------------------------------------------------------------------------
    def editor_program(self) -> str:
        """The program F4 opens files in, or "" for Dossier's own notepad."""
        return str(self.settings.value("editor/program", "") or "")

    def set_editor_program(self, program: str) -> None:
        self.settings.setValue("editor/program", program)
        self._show_editor_choice()
        self._say(f"F4 opens files in {os.path.basename(program)}" if program else "F4 opens files in Dossier's notepad")

    def choose_editor_program(self) -> None:
        program = self.dialogs.ask_program("Editor for F4", self.editor_program())
        if program:
            self.set_editor_program(program)
        else:
            self._show_editor_choice()                     # cancelled: the tick goes back to what is set

    def _show_editor_choice(self) -> None:
        program = self.editor_program()
        self.act_editor_program.setText(f"Edit (F4) in {os.path.basename(program)} (Change...)" if program
                                        else "Edit (F4) in Another Program...")
        (self.act_editor_program if program else self.act_editor_notepad).setChecked(True)

    def edit_in_program(self, path: str) -> bool:
        """Open ``path`` in the chosen editor program; False when none is chosen. The file must be on this computer."""
        program = self.editor_program()
        if not program:
            return False
        tool = tools.Tool(os.path.basename(program), program, "{file}")
        try:
            tools.launch(tool, [path], os.path.dirname(path), "", starter=self.tool_starter)
        except OSError as e:
            self.dialogs.info("Edit", f"Could not start {program}: {e.strerror or e}")
        else:
            self._say(f"Opened {os.path.basename(path)} in {tool.name}")
        return True

    def open_choice(self) -> str:
        value = str(self.settings.value("open/files", "viewer"))
        return value if value in dict(viewmodes.OPEN_CHOICES) else "viewer"

    def set_open_choice(self, key: str) -> None:
        self.settings.setValue("open/files", key)
        if key in self.open_actions:
            self.open_actions[key].setChecked(True)

    def run_scripts(self) -> bool:
        return str(self.settings.value("open/run_scripts", "true")).lower() != "false"

    def set_run_scripts(self, on: bool) -> None:
        self.settings.setValue("open/run_scripts", "true" if on else "false")
        self._say("Enter runs scripts" if on else "Enter shows scripts in the viewer; Ctrl+Enter runs them")

    def run_script(self, path: str) -> None:
        """Start the script in its own console window, in its own folder."""
        launch = scripts.launch_for(path)
        if launch is None:
            return
        try:
            self.launch_terminal(launch)
        except OSError as e:
            self.dialogs.info("Run Script", f"{os.path.basename(path)} could not be started: {e.strerror or e}")
            return
        self._say(f"Started {os.path.basename(path)}")

    def _open_file(self, path: str, alternate: bool = False) -> bool:
        """The panel's hook: show ``path`` in the viewer and return True, or return False so the panel hands it to the Windows program.
        A script runs (or, with Ctrl+Enter, is shown) when scripts run on Enter."""
        if self._home_blocked("View"):
            return True
        if not has_scheme(path) and scripts.is_script(path) and self.run_scripts() and self.open_choice() != "all":
            if alternate:
                self.view_file([path])
            else:
                self.run_script(path)
            return True
        if not alternate and not has_scheme(path):
            name = os.path.basename(path)
            if bundles.is_launcher(name, False):
                self._open_launcher(path)
                return True
            if not bundles.WINDOWS and bundles.name_could_run(name):
                # the run bit decides (Linux and Mac): looked at on a thread, then the usual way when it is no program
                run_in_background(self, self.cmd_runner, "Opening", lambda progress, cancel: self._run_mode(path),
                                  on_result=lambda mode: self._runnable_or_plain(path, mode), tracked=self._size_jobs,
                                  indeterminate=True, failed_title="Open")
                return True
        return self._open_file_plain(path, alternate)

    def _run_mode(self, path: str) -> int:
        """The file's mode (0 when it cannot be read). Called on a thread."""
        try:
            return os.stat(path).st_mode
        except OSError:
            return 0

    def _runnable_or_plain(self, path: str, mode: int) -> None:
        if not bundles.is_runnable(os.path.basename(path), False, mode):
            if not self._open_file_plain(path, False):
                self._open_with_system(path)
            return
        name = os.path.basename(path)
        answer = self.dialogs.ask_choice(
            "Run", f"{name} is a program of no known type. What now?",
            [("run", "Run"), ("terminal", "Run in a Terminal"), ("view", "View")])
        folder = os.path.dirname(path)
        if answer == "view":
            self.view_file([path])
        elif answer == "run":
            self._start_program(name, path, folder)
        elif answer == "terminal":
            try:
                self.launch_terminal(terminals.Launch([path], folder))
            except OSError as e:
                self.dialogs.info("Run", f"{name} could not be started: {e.strerror or e}")
            else:
                self._say(f"Started {name} in a terminal")

    def _start_program(self, name: str, path: str, folder: str) -> None:
        try:
            tools.launch(tools.Tool(name, path, ""), [], folder, "", starter=self.tool_starter)
        except (OSError, tools.BadTool) as e:
            self.dialogs.info("Start", f"{name} could not be started: {getattr(e, 'strerror', None) or e}")
        else:
            self._say(f"Started {name}")

    # launchers (Linux .desktop files): asked once each, as Files' "Trust and Launch" --------------------------------------------
    def trusted_launchers(self) -> dict:
        """Launchers said yes to: path -> the SHA-256 of the file as it was then (question 73A). The older list of bare paths (card 50)
        reads as paths with no checksum, so those are asked about once more."""
        try:
            value = json.loads(str(self.settings.value("open/trusted_launchers", "") or "{}"))
        except ValueError:
            return {}
        if isinstance(value, list):
            return {v: "" for v in value if isinstance(v, str)}
        return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(value, dict) else {}

    def _open_launcher(self, path: str) -> None:
        from ..core import desktop_entries

        def read(progress, cancel):                             # the launcher and its checksum: on a thread
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            return desktop_entries.read_entry(path), digest

        run_in_background(self, self.cmd_runner, "Opening", read, on_result=lambda found: self._launcher_read(path, *found),
                          tracked=self._size_jobs, indeterminate=True, failed_title="Open")

    def _launcher_read(self, path: str, app, digest: str = "") -> None:
        if app is None or not app.exec:
            self.view_file([path])                              # not a launcher after all: it is a text file
            return
        trusted = self.trusted_launchers()
        if trusted.get(path) != digest or not digest:
            changed = bool(trusted.get(path))                   # trusted before, but the file is not the one said yes to
            first = (f"{app.name or os.path.basename(path)} has changed since you trusted it." + chr(10) + chr(10) + "It now runs: "
                     if changed else f"Start {app.name or os.path.basename(path)}?" + chr(10) + chr(10) + "It runs: ")
            answer = self.dialogs.ask_choice(
                "Start Launcher", first + app.exec + chr(10) + chr(10)
                + "Only start launchers you trust. Dossier asks again only if this file changes.",
                [("start", "Start"), ("view", "View as Text")])
            if answer == "view":
                self.view_file([path])
                return
            if answer != "start":
                return
            trusted[path] = digest
            self.settings.setValue("open/trusted_launchers", json.dumps(trusted))
        self._start_program(app.name or os.path.basename(path), path, os.path.dirname(path))

    def _open_file_plain(self, path: str, alternate: bool = False) -> bool:
        choice = self.open_choice()
        if choice == "viewer" and not has_scheme(path):
            # the file's first bytes decide (a binary one goes to the system program): read on a thread, then opened from here
            def decide(progress, cancel):
                return viewmodes.opens_in_viewer(path, choice, alternate, local=True)
            run_in_background(self, self.cmd_runner, "Opening", decide,
                              on_result=lambda in_viewer: self.view_file([path]) if in_viewer else self._open_with_system(path),
                              tracked=self._size_jobs, indeterminate=True, failed_title="Open")
            return True
        if not viewmodes.opens_in_viewer(path, choice, alternate, local=not has_scheme(path)):
            return False
        self.view_file([path])
        return True
