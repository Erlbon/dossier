"""The table model behind one panel: the entries of a folder plus, when the folder has a note,
one last row that the panel fills with the rendered note (it scrolls with the list, like a README
under a repository's file list)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor, QFont

from ..core.filetypes import icon_name
from ..core.selection import SelectionStore
from ..core.vfs import Entry, FileSystem, natural_key
from . import icon_set, theme

COLUMNS = ("Name", "Size", "Date")
ENTRY_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(n)


def marked_color() -> QColor:
    """The gold of the current colour scheme (see theme.py), readable on its page and cursor row."""
    return QColor(theme.current()["marked"])


class FolderModel(QAbstractTableModel):
    def __init__(self, fs: FileSystem, selection: SelectionStore, parent=None) -> None:
        super().__init__(parent)
        self.fs = fs
        self.selection = selection
        self.path = ""
        self._up: Optional[Entry] = None
        self._rows: list = []
        self._has_note = False
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder

    # content -----------------------------------------------------------------------
    def set_folder(self, path: str) -> None:
        """List ``path``. Raises OSError (the old listing stays) when it cannot be read."""
        entries = self.fs.list(path)
        parent = self.fs.parent(path)
        up = Entry("..", parent, True) if parent else None
        self.beginResetModel()
        self.path = path
        self._up = up
        self._rows = entries
        self._resort()
        self.endResetModel()

    def set_has_note(self, has: bool) -> None:
        if has != self._has_note:
            self.beginResetModel()
            self._has_note = has
            self.endResetModel()

    @property
    def note_row(self) -> int:
        return self.entry_count() if self._has_note else -1

    def entry_count(self) -> int:
        return len(self._rows) + (1 if self._up else 0)

    def entry_at(self, row: int) -> Optional[Entry]:
        if row < 0 or row >= self.entry_count():
            return None
        if self._up:
            return self._up if row == 0 else self._rows[row - 1]
        return self._rows[row]

    def is_up_row(self, row: int) -> bool:
        return self._up is not None and row == 0

    def row_of(self, name: str) -> int:
        for r in range(self.entry_count()):
            e = self.entry_at(r)
            if e and self.fs.basename(e.path) == name and not self.is_up_row(r):
                return r
        return -1

    # sorting -----------------------------------------------------------------------
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_col, self._sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        before = {(idx.row(), idx.column()): idx for idx in self.persistentIndexList()}
        old_paths = {r: (self.entry_at(r).path if self.entry_at(r) else None) for r, _c in before}
        self._resort()
        new_row = {self.entry_at(r).path: r for r in range(self.entry_count())}
        for (r, c), idx in before.items():
            path = old_paths.get(r)
            if path in new_row:                       # the cursor stays on the same item, not the same row
                self.changePersistentIndex(idx, self.index(new_row[path], c))
        self.layoutChanged.emit()

    def _resort(self) -> None:
        keys = {0: lambda e: natural_key(e.name), 1: lambda e: (e.size, natural_key(e.name)),
                2: lambda e: (e.mtime, natural_key(e.name))}
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        folders = sorted((e for e in self._rows if e.is_dir), key=keys[self._sort_col], reverse=reverse)
        files = sorted((e for e in self._rows if not e.is_dir), key=keys[self._sort_col], reverse=reverse)
        self._rows = folders + files   # folders stay first whatever the order

    # Qt model interface ----------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self.entry_count() + (1 if self._has_note else 0)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        if self._has_note and index.row() == self.note_row:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def is_marked(self, entry: Entry) -> bool:
        return entry.name != ".." and entry.path in self.selection

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or (self._has_note and index.row() == self.note_row):
            return None
        entry = self.entry_at(index.row())
        if entry is None:
            return None
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return entry.name
            if self.is_up_row(index.row()):
                return "UP" if col == 1 else ""
            if col == 1:
                return "DIR" if entry.is_dir else human_size(entry.size)
            return datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M") if entry.mtime else ""
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._icon(entry, self.is_up_row(index.row()))
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and self.is_marked(entry):
            return QBrush(marked_color())
        if role == Qt.ItemDataRole.FontRole and (self.is_marked(entry) or entry.is_dir):
            font = QFont()
            font.setBold(True)
            return font
        if role == ENTRY_ROLE:
            return entry
        return None

    def _icon(self, entry: Entry, is_up: bool):
        """Gold for marked items and folders, the quiet text colour for the rest."""
        t = theme.current()
        name = icon_name(entry.name, is_dir=entry.is_dir, is_link=entry.is_link, is_up=is_up)
        color = t["marked"] if self.is_marked(entry) else (t["accent"] if entry.is_dir and not is_up else t["dim"])
        return icon_set.icon(name, color)

    def refresh_marks(self) -> None:
        if self.entry_count():
            self.dataChanged.emit(self.index(0, 0), self.index(self.entry_count() - 1, len(COLUMNS) - 1))
