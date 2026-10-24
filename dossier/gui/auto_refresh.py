"""Auto refresh: a panel shows a change made by another program (a file saved, a download finished, a folder made) without a manual refresh.

Settings > Auto Refresh has two switches, one for folders on this computer's own drives (on by default) and one for network drives and shares
(off by default: watching a share can be slow, and a share that sleeps or drops makes the watching unreliable). Only the folder each panel
shows is watched, so it costs two watches at most. A change is not acted on at once: a burst (a download growing, a big copy by another
program) is waited out, a panel is refreshed at most every 1.5 seconds, and nothing is refreshed while the panel is loading, an operation
is running, a name is being edited or the quick filter is open. The refresh is the ordinary one, so the cursor, the marks and the scroll
position stay where they were.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QFileSystemWatcher, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractItemView

from ..core.drives import is_network_path
from ..core.platform import path_key

KEY_LOCAL, KEY_NETWORK = "refresh/auto_local", "refresh/auto_network"
DEFAULT_LOCAL, DEFAULT_NETWORK = True, False
DEBOUNCE_MS = 600                        # wait this long after the last change before looking
RETRY_MS = 1500                          # and this long again when a panel is busy
MIN_GAP = 1.5                            # seconds between two automatic refreshes of one panel
NOT_FOLDERS = ("zip:", "flat:", "found:")


class AutoRefreshMixin:
    """Part of ``MainWindow``."""

    def build_auto_refresh(self) -> None:
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._directory_changed)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_refresh_due)
        self._auto_dirty: set = set()
        self._auto_last: dict = {}
        for panel in (self.left, self.right):
            panel.folder_changed.connect(lambda _p: self.sync_watches())
        self.sync_watches()

    # the two switches -----------------------------------------------------------------------------------------------------------------
    def auto_refresh_on(self, network: bool) -> bool:
        key, default = (KEY_NETWORK, DEFAULT_NETWORK) if network else (KEY_LOCAL, DEFAULT_LOCAL)
        value = self.settings.value(key, None)
        return default if value is None else str(value).strip().lower() in ("true", "1", "yes")

    def set_auto_refresh(self, network: bool, on: bool) -> None:
        self.settings.setValue(KEY_NETWORK if network else KEY_LOCAL, "true" if on else "false")
        self.sync_watches()
        self._say(f"Auto refresh for {'network drives' if network else 'drives of this computer'} is {'on' if on else 'off'}")

    def add_auto_refresh_actions(self, menu) -> None:
        menu = menu.addMenu("Auto Refresh")
        self.act_auto_local = QAction("Drives of This Computer", self)
        self.act_auto_network = QAction("Network Drives (can be slow)", self)
        for act, network in ((self.act_auto_local, False), (self.act_auto_network, True)):
            act.setCheckable(True)
            act.setChecked(self.auto_refresh_on(network))
            act.toggled.connect(lambda on, n=network: self.set_auto_refresh(n, on))
            menu.addAction(act)

    # what is watched ------------------------------------------------------------------------------------------------------------------
    def _watched_folder(self, panel) -> str:
        """The folder ``panel`` shows when it may be watched under the switches, else an empty string."""
        path = panel.path
        if panel.is_home or not path or "://" in path or path.startswith(NOT_FOLDERS):
            return ""
        return path if self.auto_refresh_on(is_network_path(path)) else ""

    def watched(self) -> list:
        return list(self._watcher.directories())

    def sync_watches(self) -> None:
        """Watch exactly the folders the panels show now (those the switches allow); stop watching the rest."""
        wanted = {self._watched_folder(p) for p in (self.left, self.right)} - {""}
        have = set(self._watcher.directories())
        stale = [d for d in have if path_key(d) not in {path_key(w) for w in wanted}]
        if stale:
            self._watcher.removePaths(stale)
        fresh = [w for w in wanted if path_key(w) not in {path_key(h) for h in have}]
        if fresh:
            self._watcher.addPaths(fresh)                      # a folder that is not there (any more) is simply not watched

    # reacting -------------------------------------------------------------------------------------------------------------------------
    def _directory_changed(self, path: str) -> None:
        self._auto_dirty.add(path_key(path))
        self._auto_timer.start(DEBOUNCE_MS)

    def _panel_busy(self, panel) -> bool:
        """Whether refreshing ``panel`` now would get in somebody's way."""
        editing = panel.table.state() == QAbstractItemView.State.EditingState
        return bool(panel.loading or self.busy or editing or panel.filter_edit.isVisibleTo(panel) or panel.address_bar.editing)

    def _auto_refresh_due(self) -> None:
        now = time.monotonic()
        later = False
        for panel in (self.left, self.right):
            key = path_key(panel.path)
            if key not in self._auto_dirty:
                continue
            if not self._watched_folder(panel):
                self._auto_dirty.discard(key)                    # switched off, or no longer a folder that is watched
            elif self._panel_busy(panel) or now - self._auto_last.get(id(panel), 0.0) < MIN_GAP:
                later = True                                     # try again a little later; the change is not forgotten
            else:
                self._auto_dirty.discard(key)
                self._auto_last[id(panel)] = now
                panel.refresh()
        self._auto_dirty &= {path_key(p.path) for p in (self.left, self.right)}      # a change in a folder no panel shows is of no interest
        self.sync_watches()                                      # a watched folder that was renamed or removed is dropped by the system
        if later and self._auto_dirty:
            self._auto_timer.start(RETRY_MS)
