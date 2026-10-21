"""Enter or a double-click on a file: the built-in viewer, or the program Windows has for it (Settings > Opening Files).

The rule itself is ``core.viewmodes.opens_in_viewer``; this is the window's side: the setting, its menu, and the hook a panel calls.
Ctrl+Enter always does the opposite of the setting. Marking is untouched (Ctrl+click and Ctrl+Space still mark).
"""
from __future__ import annotations

from PyQt6.QtGui import QAction, QActionGroup

from ..core import viewmodes
from ..core.platform import has_scheme


class OpenFilesMixin:
    """Part of ``MainWindow``."""

    def build_open_menu(self, parent_menu) -> None:
        menu = parent_menu.addMenu("Opening Files (Enter and Double-Click)")
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
        menu.addAction("Ctrl+Enter always does the other thing").setEnabled(False)

    def open_choice(self) -> str:
        value = str(self.settings.value("open/files", "viewer"))
        return value if value in dict(viewmodes.OPEN_CHOICES) else "viewer"

    def set_open_choice(self, key: str) -> None:
        self.settings.setValue("open/files", key)
        if key in self.open_actions:
            self.open_actions[key].setChecked(True)

    def _open_file(self, path: str, alternate: bool = False) -> bool:
        """The panel's hook: show ``path`` in the viewer and return True, or return False so the panel hands it to the Windows program."""
        if self._home_blocked("View"):
            return True
        if not viewmodes.opens_in_viewer(path, self.open_choice(), alternate, local=not has_scheme(path)):
            return False
        self.view_file([path])
        return True
