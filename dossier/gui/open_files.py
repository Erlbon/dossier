"""Enter or a double-click on a file: the built-in viewer, or the program Windows has for it (Settings > Opening Files).

The rule itself is ``core.viewmodes.opens_in_viewer``; this is the window's side: the setting, its menu, and the hook a panel calls.
Ctrl+Enter always does the opposite of the setting. Marking is untouched (Ctrl+click and Ctrl+Space still mark).
A script (``core/scripts.py``) runs on Enter unless Settings > Opening Files > Run Scripts on Enter is switched off; Ctrl+Enter then shows it.
"""
from __future__ import annotations

import os

from PyQt6.QtGui import QAction, QActionGroup

from ..core import scripts, viewmodes
from ..core.platform import has_scheme


class OpenFilesMixin:
    """Part of ``MainWindow``."""

    def build_open_menu(self, parent_menu) -> None:
        menu = parent_menu.addMenu("Opening Files")
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
        menu.addAction("What Enter and double-click do. Ctrl+Enter does the other thing.").setEnabled(False)

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
        if not viewmodes.opens_in_viewer(path, self.open_choice(), alternate, local=not has_scheme(path)):
            return False
        self.view_file([path])
        return True
