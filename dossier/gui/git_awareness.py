"""Git awareness in the window (plan 2026-11-07, card 4): git is read on the drives of this computer, and on network drives only when the
owner switches it on (Settings > Git Status on Network Drives), as with thumbnails and auto refresh: ``git status`` of a big repository
over a share can take seconds. Servers and archives are never asked. The reading itself is the panel's (``Panel.refresh_git``).
"""
from __future__ import annotations

from PyQt6.QtGui import QAction

from ..core.drives import is_network_path

KEY_NETWORK = "git/network"


class GitAwarenessMixin:
    """Part of ``MainWindow``."""

    def build_git_awareness(self) -> None:
        for panel in (self.left, self.right):
            panel.git_allowed = self.git_allowed
            if self.git_on_network():                # the first listing was made before the switch was known
                panel.refresh_git()

    def git_on_network(self) -> bool:
        return str(self.settings.value(KEY_NETWORK, "false")).strip().lower() in ("true", "1", "yes")

    def git_allowed(self, path: str) -> bool:
        return self.git_on_network() or not is_network_path(path)

    def set_git_on_network(self, on: bool) -> None:
        self.settings.setValue(KEY_NETWORK, "true" if on else "false")
        for panel in (self.left, self.right):
            panel.refresh_git()
        self._say(f"Git status on network drives is {'on' if on else 'off'}")

    def add_git_actions(self, menu) -> None:
        self.act_git_network = QAction("Git Status on Network Drives (can be slow)", self)
        self.act_git_network.setToolTip("Show the branch and the Git column for repositories on network drives and shares too")
        self.act_git_network.setCheckable(True)
        self.act_git_network.setChecked(self.git_on_network())
        self.act_git_network.toggled.connect(self.set_git_on_network)
        menu.addAction(self.act_git_network)
