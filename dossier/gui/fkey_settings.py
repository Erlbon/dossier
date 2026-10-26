"""Settings > Function Keys...: choose the command of every key of the plain, Shift and Ctrl rows."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QAbstractItemView)

from ..core import fkey_config
from ..core.fkey_config import LAYERS, NUMBERS, TITLES
from . import fkeys
from .owned_dialog import OwnedDialog

NONE = ""


class FunctionKeysDialog(OwnedDialog):
    """Three tabs of twelve rows. ``table()`` is the choice made: ``{layer: {number: command}}`` (a key left empty is not in it)."""

    def __init__(self, table: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Function Keys")
        self.resize(520, 520)
        layout = QVBoxLayout(self)
        intro = QLabel("Choose what each function key does. Hold Shift or Ctrl to see the other rows on the bar. "
                       "A row with no keys is never shown.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        self.combos: dict = {}
        self._ordered = sorted(fkeys.COMMANDS, key=lambda c: fkeys.COMMANDS[c].label.lower())
        for layer in LAYERS:
            self.tabs.addTab(self._build_tab(layer, table.get(layer, {})), TITLES[layer])
        layout.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        this_tab = QPushButton("Restore This Tab")
        this_tab.clicked.connect(lambda: self._restore([LAYERS[self.tabs.currentIndex()]]))
        everything = QPushButton("Restore All")
        everything.clicked.connect(lambda: self._restore(list(LAYERS)))
        row.addWidget(this_tab)
        row.addWidget(everything)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_tab(self, layer: str, row: dict) -> QTableWidget:
        grid = QTableWidget(len(NUMBERS), 2)
        grid.setHorizontalHeaderLabels(["Key", "Command"])
        grid.verticalHeader().hide()
        grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        grid.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        grid.horizontalHeader().setStretchLastSection(True)
        for r, number in enumerate(NUMBERS):
            item = QTableWidgetItem(fkey_config.key_text(layer, number))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            grid.setItem(r, 0, item)
            combo = QComboBox()
            combo.addItem("(none)", NONE)
            for command in self._ordered:
                combo.addItem(fkeys.COMMANDS[command].label, command)
            combo.setCurrentIndex(max(0, combo.findData(row.get(number, NONE))))
            grid.setCellWidget(r, 1, combo)
            self.combos[(layer, number)] = combo
        grid.setColumnWidth(0, 110)
        return grid

    def _restore(self, layers: list) -> None:
        for layer in layers:
            for number in NUMBERS:
                combo = self.combos[(layer, number)]
                combo.setCurrentIndex(max(0, combo.findData(fkey_config.DEFAULTS[layer].get(number, NONE))))

    def table(self) -> dict:
        return {layer: {n: self.combos[(layer, n)].currentData() for n in NUMBERS if self.combos[(layer, n)].currentData()}
                for layer in LAYERS}
