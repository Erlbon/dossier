"""Settings > Appearance > Picture Viewer Glass...: the mode and how much of the desktop shows through the picture viewer."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout)

from ..core import glass
from .owned_dialog import OwnedDialog

TITLES = {glass.FROSTED: "Frosted glass (the desktop blurred)", glass.DIM: "Dim glass (the desktop sharp)", glass.SOLID: "Solid (no transparency)"}


class GlassDialog(OwnedDialog):
    def __init__(self, mode: str, level, capabilities: glass.Capabilities, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Picture Viewer Glass")
        self.capabilities = capabilities
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        for m in glass.MODES:
            self.mode.addItem(TITLES[m], m)
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        form.addRow("Look", self.mode)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, glass.MAX_LEVEL)
        self.slider.setValue(glass.level_for(mode if mode != glass.SOLID else glass.FROSTED, level))
        self.value_label = QLabel()
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        form.addRow("Desktop shows through", row)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.slider.valueChanged.connect(self._refresh)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._refresh()

    def _mode_changed(self) -> None:
        mode = self.mode.currentData()
        if mode != glass.SOLID:
            self.slider.setValue(glass.DEFAULT_LEVEL[mode])               # each look starts from its own usual setting
        self._refresh()

    def _refresh(self) -> None:
        mode = self.mode.currentData()
        self.slider.setEnabled(mode != glass.SOLID)
        self.value_label.setText(f"{self.slider.value()} %" if mode != glass.SOLID else "")
        best = glass.resolve(mode, self.capabilities)
        self.note.setText("" if best == mode else f"This computer cannot do that look right now ({TITLES[best].split(' (')[0].lower()} will be used).")

    def values(self) -> tuple:
        """``(mode, level)``; the level is None for solid."""
        mode = self.mode.currentData()
        return mode, (None if mode == glass.SOLID else self.slider.value())
