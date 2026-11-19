"""Earlier Versions (card 67B): the snapshots a NAS, ZFS or btrfs keeps as plain folders, listed for the item under the cursor.

The engine is ``core/snapshots.py``. Here: the search on a thread (a network share is slow), a picker with the moments, and opening the
chosen one in the OTHER panel. Snapshot folders are read-only for the whole program (``LocalFileSystem.is_writable`` says no for a path
inside one), so the other panel cannot be changed, and copying out of it with the normal commands brings an earlier version back.
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ..core import snapshots
from ..core.platform import has_scheme
from .background import run_in_background
from .owned_dialog import OwnedDialog


class EarlierVersionsDialog(OwnedDialog):
    """The moments that hold the item, newest first. ``chosen()`` is the picked ``Moment`` (or None)."""

    def __init__(self, parent, name: str, moments: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Earlier Versions")
        self.resize(640, 380)
        self.moments = list(moments)
        layout = QVBoxLayout(self)
        intro = QLabel(f"{len(moments):,} earlier version{'s' if len(moments) != 1 else ''} of {name}. The chosen one opens in the other "
                       "panel, where nothing can be changed. Copy from there to bring a version back.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["When", "Snapshot", "Kept by"])
        for m in self.moments:
            item = QTreeWidgetItem([datetime.fromtimestamp(m.when).strftime("%Y-%m-%d %H:%M") if m.when else "", m.name, m.kind])
            item.setData(0, Qt.ItemDataRole.UserRole, m)
            item.setToolTip(1, m.path)
            self.tree.addTopLevelItem(item)
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 300)
        if self.moments:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.itemDoubleClicked.connect(lambda *_a: self.accept())
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.open_button = buttons.addButton("Open in the Other Panel", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None


class EarlierVersionsMixin:
    """Part of ``MainWindow``."""

    def _ask_earlier_version(self, dlg):                      # seam for tests: the picked Moment, or None
        return dlg.chosen() if dlg.exec() == QDialog.DialogCode.Accepted else None

    def earlier_versions(self) -> None:
        """Tools > Compare > Earlier Versions, and right-click: list the snapshots that hold the item under the cursor."""
        panel = self.active
        paths = panel.targets()
        if panel.is_home or len(paths) != 1:
            self._say("Put the cursor on one file or folder to look for its earlier versions")
            return
        path = paths[0]
        if has_scheme(path):
            self._say("Earlier versions are looked for on disks and shares, not inside archives or on servers")
            return
        name = os.path.basename(path.rstrip("/" + chr(92))) or path

        def work(progress, cancel):
            return snapshots.find_earlier_versions(path, cancel=(lambda: cancel.cancelled) if cancel is not None else None)

        run_in_background(self, self.cmd_runner, "Looking for earlier versions", work,
                          on_result=lambda found: self._earlier_versions_found(path, name, found),
                          tracked=self._size_jobs, indeterminate=True, failed_title="Earlier Versions")

    def _earlier_versions_found(self, path: str, name: str, found) -> None:
        if not found.moments:
            self.dialogs.info("Earlier Versions", snapshots.nothing_found_text(found, name))
            return
        moment = self._ask_earlier_version(EarlierVersionsDialog(self, name, found.moments))
        if moment is None:
            return
        self.open_earlier_version(moment)

    def open_earlier_version(self, moment) -> None:
        """Show the snapshot's copy in the other panel: its folder, with the cursor on the item."""
        other = self.other if self.other is not self.active else self.left
        folder, item = os.path.split(moment.path.rstrip("/" + chr(92)))
        other.set_folder(folder, select=item)
        self._say(f"The other panel shows {item} as it was in {moment.name} (read-only)")
