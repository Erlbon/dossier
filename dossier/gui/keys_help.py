"""F1: the list of every keyboard shortcut, read from the menus themselves (so it is never out of date), and F11: full screen."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLineEdit, QMenu, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from .owned_dialog import OwnedDialog


def shortcut_rows(menu_bar) -> list:
    """``(keys, command, menu)`` for every menu action that has a shortcut, in menu order. A submenu is named with its parent."""
    rows = []

    def walk(menu: QMenu, path: str) -> None:
        for action in menu.actions():
            sub = action.menu()
            if sub is not None:
                walk(sub, f"{path} > {sub.title().replace('&', '')}")
            elif action.shortcuts() and not action.isSeparator():
                keys = ", ".join(s.toString(s.SequenceFormat.NativeText) for s in action.shortcuts())
                rows.append((keys, action.text().replace("&", "").rstrip(". ").rstrip("…"), path))

    for top in menu_bar.actions():
        if top.menu() is not None:
            walk(top.menu(), top.text().replace("&", ""))
    return rows


class KeysDialog(OwnedDialog):
    def __init__(self, rows: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(560, 560)
        layout = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by key or command")
        self.filter.setClearButtonEnabled(True)
        layout.addWidget(self.filter)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["Keys", "Command", "Menu"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(text))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)      # every column can be dragged wider
        header.setStretchLastSection(True)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)                                   # and every header sorts
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.filter.textChanged.connect(self._apply_filter)
        self.filter.setFocus()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for r in range(self.table.rowCount()):
            hit = not needle or any(needle in self.table.item(r, c).text().lower() for c in range(3))
            self.table.setRowHidden(r, not hit)


class KeysMixin:
    """Part of ``MainWindow``."""

    def show_keys(self) -> None:
        KeysDialog(shortcut_rows(self.menuBar()), self).exec()

    def toggle_full_screen(self) -> None:
        """F11: the window fills the screen (no title bar, no taskbar); F11 again puts it back as it was, maximized or not."""
        if self.isFullScreen():
            self.showMaximized() if getattr(self, "_maximized_before_full", False) else self.showNormal()
        else:
            self._maximized_before_full = self.isMaximized()
            self.showFullScreen()
