"""F1: the list of every keyboard shortcut, read from the menus themselves (so it is never out of date), and F11: full screen."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLineEdit, QMenu, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from ..core import fkey_config
from . import fkeys
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


class LayerWatcher(QObject):
    """Watches the whole application for Shift and Ctrl going down and up, and tells the window which row of function keys to show."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Control):
            if self.window.isActiveWindow():
                mods = event.modifiers()                  # the key that just changed is judged by the event kind, not by what the platform reports
                pressed = kind == QEvent.Type.KeyPress
                shift = pressed if event.key() == Qt.Key.Key_Shift else bool(mods & Qt.KeyboardModifier.ShiftModifier)
                ctrl = pressed if event.key() == Qt.Key.Key_Control else bool(mods & Qt.KeyboardModifier.ControlModifier)
                self.window.show_modifier_row(shift, ctrl)
        elif kind == QEvent.Type.WindowDeactivate and obj is self.window:
            self.window.show_modifier_row(False, False)                       # a key let go in another window is never seen here
        return False


class KeysMixin:
    """Part of ``MainWindow``."""

    def install_layer_watcher(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(LayerWatcher(self))

    def show_modifier_row(self, shift: bool, ctrl: bool) -> None:
        layer = fkey_config.layer_for(self._fkey_table, shift, ctrl)
        if layer != self._fkey_layer:
            self.set_fkey_layer(layer)

    def delete_permanently(self) -> None:
        self.delete(permanent=True)

    def open_admin_terminal(self) -> None:
        self.open_terminal(admin=True)

    def open_function_keys_settings(self) -> None:
        from .fkey_settings import FunctionKeysDialog
        dlg = FunctionKeysDialog(self._fkey_table, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_fkey_table(dlg.table())

    def set_fkey_table(self, table: dict) -> None:
        """Use a new choice of keys: save what differs from the built-in table, rebind the keyboard, redraw the bar."""
        changes = fkey_config.changes_from(table)                          # a key left empty is a change too, not a gap to fill with the default
        self._fkey_table = fkey_config.resolve(changes, known=fkeys.COMMANDS)
        self.settings.setValue("fkeys/config", fkey_config.dump(changes))
        self.apply_fkey_shortcuts()
        self.set_fkey_layer(fkey_config.layer_for(self._fkey_table, False, False))

    def show_keys(self) -> None:
        KeysDialog(shortcut_rows(self.menuBar()), self).exec()

    def toggle_full_screen(self) -> None:
        """F11: the window fills the screen (no title bar, no taskbar); F11 again puts it back as it was, maximized or not."""
        if self.isFullScreen():
            self.showMaximized() if getattr(self, "_maximized_before_full", False) else self.showNormal()
        else:
            self._maximized_before_full = self.isMaximized()
            self.showFullScreen()
