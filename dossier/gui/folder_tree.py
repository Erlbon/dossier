"""Go > Folder Tree... (Alt+F10): the folders of the drive as a tree in a popup; Enter (or a double-click) goes there and the popup closes
(functionality review 2026-11-05, card 26, the popup only: no tree beside the panel).

Folders are read by Qt's own file-system model, on its own thread, so a slow or sleeping drive never holds the window. It starts at the
drive (or network share) of the active panel, opened down to the folder the panel shows. A server or an archive says it has no tree.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QDir, QModelIndex, QPoint, Qt
from PyQt6.QtGui import QFileSystemModel, QKeyEvent
from PyQt6.QtWidgets import QAbstractItemView, QDialog, QTreeView, QVBoxLayout

from ..core.platform import has_scheme
from .owned_dialog import OwnedDialog


class FolderTreePopup(OwnedDialog):
    def __init__(self, parent, start: str) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.chosen = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        root = (os.path.splitdrive(start)[0] + os.sep) if os.name == "nt" else "/"     # a drive, or a share's root
        self.model.setRootPath(root)
        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)                          # the name only: size, type and date say nothing of a folder here
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setRootIndex(self.model.index(root))
        self.tree.activated.connect(self._go)
        layout.addWidget(self.tree)
        self.resize(420, 520)
        self._show(start)

    def _show(self, path: str) -> None:
        index = self.model.index(path)
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.tree.expand(index)

    def _go(self, index: QModelIndex) -> None:
        if index.isValid():
            self.chosen = os.path.normpath(self.model.filePath(index))
            self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._go(self.tree.currentIndex())
            return
        super().keyPressEvent(event)


class FolderTreeMixin:
    """Part of ``MainWindow``."""

    def show_folder_tree(self) -> None:
        panel = self.active
        start = panel.real_folder() if not panel.is_home else ""
        if not start or has_scheme(start):
            self._say("The folder tree shows the drives of this computer: open a folder on one first")
            return
        popup = FolderTreePopup(self, start)
        bar = panel.address_bar
        popup.move(bar.mapToGlobal(QPoint(0, bar.height())))
        if self._ask_folder_tree(popup) and popup.chosen:
            panel.set_folder(popup.chosen)
        panel.view.setFocus()

    def _ask_folder_tree(self, popup) -> bool:                    # a seam for tests
        popup.tree.setFocus()
        return popup.exec() == QDialog.DialogCode.Accepted
