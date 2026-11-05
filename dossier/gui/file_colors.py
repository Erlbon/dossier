"""Settings > Appearance > File Colours...: switch the colours of names by type on or off, and change a group's extensions and colours
(``core/filecolors.py`` holds the rules)."""
from __future__ import annotations

from dataclasses import asdict

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from ..core import filecolors
from .owned_dialog import OwnedDialog

SETTING = "view/file_colors"


class FileColorsDialog(OwnedDialog):
    def __init__(self, parent, current: filecolors.FileColors) -> None:
        super().__init__(parent)
        self.setWindowTitle("File Colours")
        self.setMinimumWidth(720)
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Colour file names by their type (hidden and system files are dimmed, marked files stay gold)")
        self.enabled.setChecked(current.enabled)
        layout.addWidget(self.enabled)
        grid = QGridLayout()
        for col, text in enumerate(("", "Extensions", "Light scheme", "Dark scheme")):
            grid.addWidget(QLabel(f"<b>{text}</b>"), 0, col)
        self.rows = []
        for r, g in enumerate(current.groups, start=1):
            exts = QLineEdit(g.extensions)
            light, dark = self._swatch(g.light), self._swatch(g.dark)
            grid.addWidget(QLabel(g.name), r, 0)
            grid.addWidget(exts, r, 1)
            grid.addWidget(light, r, 2)
            grid.addWidget(dark, r, 3)
            self.rows.append((g, exts, light, dark))
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        reset = buttons.addButton("Back to the Defaults", QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self.reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _swatch(self, colour: str) -> QPushButton:
        button = QPushButton(colour)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self._choose(button))
        self._paint(button, colour)
        return button

    @staticmethod
    def _paint(button: QPushButton, colour: str) -> None:
        button.setText(colour)
        button.setStyleSheet(f"color: {colour}; font-weight: bold;")

    def _choose(self, button: QPushButton) -> None:
        chosen = self._ask_colour(QColor(button.text()))
        if chosen is not None:
            self._paint(button, chosen)

    def _ask_colour(self, start: QColor):                      # a seam for tests
        c = QColorDialog.getColor(start, self, "Colour")
        return c.name() if c.isValid() else None

    def reset(self) -> None:
        defaults = {g.key: g for g in filecolors.DEFAULT_GROUPS}
        for g, exts, light, dark in self.rows:
            d = defaults[g.key]
            exts.setText(d.extensions)
            self._paint(light, d.light)
            self._paint(dark, d.dark)
        self.enabled.setChecked(True)

    def value(self) -> filecolors.FileColors:
        groups = [filecolors.ColorGroup(**{**asdict(g), "extensions": exts.text().strip(), "light": light.text(), "dark": dark.text()})
                  for g, exts, light, dark in self.rows]
        return filecolors.loads(filecolors.dumps(filecolors.FileColors(self.enabled.isChecked(), groups)))     # cleaned as when read back


class FileColorsMixin:
    """Part of ``MainWindow``."""

    def file_colors(self) -> filecolors.FileColors:
        return filecolors.loads(str(self.settings.value(SETTING, "") or ""))

    def apply_file_colors(self, colors=None) -> None:
        colors = colors or self.file_colors()
        for panel in (self.left, self.right):
            panel.model.file_colors = colors
            panel.table.viewport().update()
            panel.view.viewport().update()

    def open_file_colors(self) -> None:
        dlg = FileColorsDialog(self, self.file_colors())
        if not self._ask_file_colors(dlg):
            return
        colors = dlg.value()
        self.settings.setValue(SETTING, filecolors.dumps(colors))
        self.apply_file_colors(colors)

    def _ask_file_colors(self, dlg) -> bool:                   # a seam for tests
        return dlg.exec() == FileColorsDialog.DialogCode.Accepted
