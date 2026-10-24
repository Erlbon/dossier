"""The question "these items already exist": one row per file, each with its own answer.

A table with the name, what is being copied, what is already there, and a choice per row. Buttons set many rows at once
(all overwrite, all skip, newer only, skip identical). The table has a height limit: past ``MAX_ROWS_SHOWN`` rows it
scrolls, so a thousand conflicts never make a box taller than the screen.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.ops import ConflictRow, Resolution
from ..core.sizefmt import human_size
from .owned_dialog import OwnedDialog

MAX_ROWS_SHOWN = 10                     # the table is this tall at most; more rows scroll
MIN_ROWS_SHOWN = 3

CHOICES = (("Overwrite", Resolution.OVERWRITE), ("Skip", Resolution.SKIP), ("Keep both", Resolution.KEEP_BOTH))
_WHEN = "%Y-%m-%d %H:%M"


def default_choice(row: ConflictRow) -> Resolution:
    """What a row starts as: identical files are skipped, a newer copy replaces, anything else keeps both."""
    if row.identical:
        return Resolution.SKIP
    if row.can_overwrite and row.newer:
        return Resolution.OVERWRITE
    return Resolution.KEEP_BOTH


def _when(mtime: float) -> str:
    try:
        return datetime.fromtimestamp(mtime).strftime(_WHEN)
    except (OverflowError, OSError, ValueError):
        return ""


class ConflictDialog(OwnedDialog):
    def __init__(self, parent: Optional[QWidget], rows: list, where: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Items already exist")
        self.setMinimumWidth(860)
        self.rows = list(rows)
        self._combos: list = []
        layout = QVBoxLayout(self)
        head = QLabel(f"{len(rows)} item{'s' if len(rows) != 1 else ''} already exist"
                      + (f" in {where}" if where else "") + ". Choose what to do with each one.")
        head.setWordWrap(True)
        layout.addWidget(head)

        self.table = QTableWidget(len(rows), 4, self)
        self.table.setHorizontalHeaderLabels(["Name", "Copying", "Already there", "Do this"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 200), (2, 180), (3, 120)):          # fixed widths: the Name column takes the rest
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for r, row in enumerate(rows):
            name = QTableWidgetItem(row.name)
            name.setToolTip(row.path)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(self._side(row.size, row.src_mtime,
                                                                 "newer" if row.newer else "older" if row.older else "same time")))
            self.table.setItem(r, 2, QTableWidgetItem(self._side(row.dst_size, row.dst_mtime, "")))
            combo = QComboBox()
            for label, res in CHOICES:
                if res is Resolution.OVERWRITE and not row.can_overwrite:
                    continue                                      # a folder, or the item itself, cannot be overwritten
                combo.addItem(label, res)
            self._set(combo, default_choice(row))
            self.table.setCellWidget(r, 3, combo)
            self._combos.append(combo)
        shown = max(MIN_ROWS_SHOWN, min(len(rows), MAX_ROWS_SHOWN))
        row_h = self.table.verticalHeader().defaultSectionSize()
        self.table.setFixedHeight(self.table.horizontalHeader().height() + row_h * shown + 4)   # the height limit
        layout.addWidget(self.table)

        bulk = QHBoxLayout()
        for text, handler in (("All: overwrite", lambda: self._all(Resolution.OVERWRITE)),
                              ("All: skip", lambda: self._all(Resolution.SKIP)),
                              ("All: keep both", lambda: self._all(Resolution.KEEP_BOTH)),
                              ("Newer only", self._newer_only), ("Skip identical", self._skip_identical)):
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(handler)
            bulk.addWidget(button)
        bulk.addStretch(1)
        layout.addLayout(bulk)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ok.setDefault(True)

    @staticmethod
    def _side(size: int, mtime: float, note: str) -> str:
        text = f"{human_size(size)}, {_when(mtime)}"
        return f"{text}  ({note})" if note else text

    @staticmethod
    def _set(combo: QComboBox, res: Resolution) -> None:
        i = combo.findData(res)
        combo.setCurrentIndex(i if i >= 0 else combo.findData(Resolution.SKIP))

    def _all(self, res: Resolution) -> None:
        for combo in self._combos:
            self._set(combo, res)

    def _newer_only(self) -> None:
        for row, combo in zip(self.rows, self._combos):
            self._set(combo, Resolution.OVERWRITE if row.can_overwrite and row.newer else Resolution.SKIP)

    def _skip_identical(self) -> None:
        for row, combo in zip(self.rows, self._combos):
            if row.identical:
                self._set(combo, Resolution.SKIP)

    def answers(self) -> dict:
        """Plan step number -> the Resolution chosen for it."""
        return {row.index: combo.currentData() for row, combo in zip(self.rows, self._combos)}
