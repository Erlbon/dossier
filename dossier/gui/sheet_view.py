"""The Spreadsheet page of the F3 viewer: a workbook's values in a grid, read only, like a look into Excel.

Column letters and row numbers as Excel shows them, one tab per sheet under the grid (a hidden sheet says so), select cells and copy
them as tab-separated text (they paste into Excel as cells), and find a text cell by cell. Nothing here edits; the values come from
``core/officesheet.py``.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeySequence
from PyQt6.QtWidgets import QAbstractItemView, QTableView, QTabBar, QVBoxLayout, QWidget

from . import theme


def column_name(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    n += 1
    while n:
        n, rest = divmod(n - 1, 26)
        name = chr(65 + rest) + name
    return name


class SheetModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list = []
        self.width = 0

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self.rows = rows
        self.width = max((len(r) for r in rows), default=0)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self.width

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            row = self.rows[index.row()]
            text = row[index.column()] if index.column() < len(row) else ""
            return text if role == Qt.ItemDataRole.DisplayRole or len(text) > 40 else None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            row = self.rows[index.row()]
            text = row[index.column()] if index.column() < len(row) else ""
            if _numeric(text):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return column_name(section) if orientation == Qt.Orientation.Horizontal else str(section + 1)


def _numeric(text: str) -> bool:
    """Numbers, dates and percentages line up on the right, as in Excel."""
    if not text or not (text[0].isdigit() or text[0] in "-+."):
        return False
    return all(ch.isdigit() or ch in "-+.:%e " for ch in text)


class SheetPage(QWidget):
    changed = pyqtSignal()                          # the current cell or sheet moved: the window updates its place label
    copied = pyqtSignal(int)                        # Ctrl+C copied this many cells

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.sheets: list = []
        self.model = SheetModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setDefaultSectionSize(110)
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().height() + 8)
        self.table.verticalHeader().setMinimumWidth(44)
        self.table.selectionModel().currentChanged.connect(lambda *_: self.changed.emit())
        self.table.installEventFilter(self)
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._show_sheet)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.tabs)
        self.setFocusProxy(self.table)
        self.restyle()

    def restyle(self) -> None:
        t = theme.current()
        self.table.setStyleSheet(
            f"QTableView{{background:{t['bg']};color:{t['fg']};gridline-color:{t['line']};border:none;"
            f"selection-background-color:{t['cursor_bg']};selection-color:{t['cursor_fg']};}}"
            f"QHeaderView::section{{background:{t['card']};color:{t['dim']};border:none;"
            f"border-right:1px solid {t['line']};border-bottom:1px solid {t['line']};padding:0 6px;}}"
            f"QTableCornerButton::section{{background:{t['card']};border:none;}}")
        self.tabs.setStyleSheet(
            f"QTabBar{{background:{t['card']};}}"
            f"QTabBar::tab{{background:{t['card']};color:{t['dim']};padding:4px 14px;border:none;border-top:2px solid transparent;}}"
            f"QTabBar::tab:selected{{background:{t['bg']};color:{t['fg']};border-top:2px solid {t['accent']};}}")

    def set_workbook(self, sheets: list) -> None:
        self.sheets = list(sheets)
        blocked = self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for s in self.sheets:
            self.tabs.addTab(s.name + (" (hidden)" if s.hidden else ""))
        self.tabs.blockSignals(blocked)
        self.tabs.setVisible(len(self.sheets) > 1)
        first = next((i for i, s in enumerate(self.sheets) if not s.hidden and s.rows), 0)
        self.tabs.setCurrentIndex(first)
        self._show_sheet(first)

    def clear(self) -> None:
        self.set_workbook([])

    def sheet(self):
        i = self.tabs.currentIndex()
        return self.sheets[i] if 0 <= i < len(self.sheets) else None

    def _show_sheet(self, i: int) -> None:
        sheet = self.sheets[i] if 0 <= i < len(self.sheets) else None
        self.model.set_rows(sheet.rows if sheet else [])
        self._fit_columns()
        if sheet and sheet.rows:
            self.table.setCurrentIndex(self.model.index(0, 0))
        self.changed.emit()

    def _fit_columns(self) -> None:
        """Each column as wide as its text in the first rows (a path, a URL), within limits; measuring every row would take long."""
        fm = self.table.fontMetrics()
        rows = self.model.rows[:200]
        for c in range(self.model.width):
            widest = max((fm.horizontalAdvance(r[c]) for r in rows if c < len(r) and r[c]), default=0)
            self.table.setColumnWidth(c, max(60, min(widest + 18, 480)))

    def place(self) -> str:
        """``C2`` and the sheet's size, for the window's place label."""
        sheet = self.sheet()
        if sheet is None:
            return ""
        size = f"{len(sheet.rows):,} rows x {self.model.width} columns" + (" (cut)" if sheet.cut else "")
        cur = self.table.currentIndex()
        return f"{column_name(cur.column())}{cur.row() + 1}   {size}" if cur.isValid() else size

    def selected_text(self) -> str:
        """The selected cells as tab-separated lines, the block from the top-left to the bottom-right of the selection."""
        indexes = self.table.selectionModel().selectedIndexes()
        if not indexes:
            return ""
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        chosen = {(i.row(), i.column()) for i in indexes}
        lines = []
        for r in range(rows[0], rows[-1] + 1):
            row = self.model.rows[r]
            lines.append("\t".join(row[c] if (r, c) in chosen and c < len(row) else "" for c in range(cols[0], cols[-1] + 1)))
        return "\n".join(lines)

    def copy(self) -> int:
        """Copy the selected cells; returns how many were copied."""
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
        return len(self.table.selectionModel().selectedIndexes()) if text else 0

    def eventFilter(self, obj, event) -> bool:
        """Ctrl+C on the grid copies the whole selection (Qt's own copies only the current cell)."""
        if obj is self.table and event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Copy):
            self.copied.emit(self.copy())
            return True
        return super().eventFilter(obj, event)

    def find(self, needle: str, forward: bool = True, case: bool = False) -> Optional[str]:
        """Select the next cell (by rows, then columns) holding ``needle``, wrapping around once. Returns ``found``, ``wrapped`` or
        None when no cell has it."""
        rows = self.model.rows
        if not needle or not rows:
            return None
        width = self.model.width
        total = len(rows) * width
        cur = self.table.currentIndex()
        start = cur.row() * width + cur.column() if cur.isValid() else -1
        want = needle if case else needle.lower()
        step = 1 if forward else -1
        for k in range(1, total + 1):
            n = (start + step * k) % total
            r, c = divmod(n, width)
            text = rows[r][c] if c < len(rows[r]) else ""
            if want in (text if case else text.lower()):
                self.table.setCurrentIndex(self.model.index(r, c))
                self.table.scrollTo(self.model.index(r, c))
                wrapped = (n <= start) if forward else (n >= start)
                return "wrapped" if wrapped else "found"
        return None
