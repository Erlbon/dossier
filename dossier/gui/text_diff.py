"""Compare Two Files, for text: the two files side by side, the differing lines tinted (``core/textdiff.py`` makes the rows)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout)

from ..core import textdiff
from .owned_dialog import OwnedDialog

# translucent tints, so they read on the light and the dark scheme alike
TINTS = {textdiff.CHANGED: QColor(230, 180, 40, 70), textdiff.LEFT_ONLY: QColor(220, 60, 60, 60),
         textdiff.RIGHT_ONLY: QColor(60, 170, 80, 60)}


class TextDiffWindow(OwnedDialog):
    def __init__(self, parent, title: str, header: str, rows: list) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)        # shown, not exec'd: it goes when it is closed
        self.setWindowTitle(title)
        self.resize(1100, 700)
        self.rows = rows
        layout = QVBoxLayout(self)
        top = QLabel(header)
        top.setWordWrap(True)
        layout.addWidget(top)
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["", "Left", "", "Right"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        head = self.table.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch)):
            head.setSectionResizeMode(col, mode)
        for r, row in enumerate(rows):
            cells = (str(row.left_no) if row.left_no else "", row.left, str(row.right_no) if row.right_no else "", row.right)
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row.kind in TINTS:
                    item.setBackground(TINTS[row.kind])
                self.table.setItem(r, c, item)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.next_button = QPushButton("Next Difference")
        self.next_button.clicked.connect(self.next_difference)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.next_difference()

    def next_difference(self) -> int:
        """Move to the next differing line after the current one (round to the first). Returns its row, or -1."""
        start = self.table.currentRow() + 1
        order = list(range(start, len(self.rows))) + list(range(0, start))
        for r in order:
            if self.rows[r].kind != textdiff.SAME and (r == 0 or self.rows[r - 1].kind == textdiff.SAME or r == start):
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, 1), QAbstractItemView.ScrollHint.PositionAtCenter)
                return r
        return -1
