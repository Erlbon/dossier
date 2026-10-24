"""Settings > Mouse Wheel...: what the wheel does in the picture viewer, for the wheel alone, with Ctrl and with Shift."""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QVBoxLayout

from ..core import wheel
from .owned_dialog import OwnedDialog


def read_wheel(settings) -> dict:
    return wheel.clean({key: settings.value("wheel/" + key, None) for key, _label in wheel.KEYS})


def write_wheel(settings, values: dict) -> None:
    for key, value in wheel.clean(values).items():
        settings.setValue("wheel/" + key, value)


class WheelDialog(OwnedDialog):
    def __init__(self, parent, values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mouse Wheel")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("What the mouse wheel does when you look at a picture (F3). In the file lists it always scrolls."))
        form = QFormLayout()
        self.boxes = {}
        for key, label in wheel.KEYS:
            box = QComboBox()
            for action, text in wheel.ACTIONS:
                box.addItem(text, action)
            box.setCurrentIndex(max(0, box.findData(values[key])))
            form.addRow(label, box)
            self.boxes[key] = box
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.defaults = QPushButton("Back to the defaults")
        self.defaults.setAutoDefault(False)
        buttons.addButton(self.defaults, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.defaults.clicked.connect(self._reset)
        layout.addWidget(buttons)

    def _reset(self) -> None:
        for key, box in self.boxes.items():
            box.setCurrentIndex(max(0, box.findData(wheel.DEFAULTS[key])))

    def values(self) -> dict:
        return {key: box.currentData() for key, box in self.boxes.items()}


class WheelMixin:
    """Part of ``MainWindow``."""

    def wheel_map(self) -> dict:
        return read_wheel(self.settings)

    def open_wheel_settings(self) -> None:
        dlg = WheelDialog(self, self.wheel_map())
        if not self._run_wheel_dialog(dlg):
            return
        write_wheel(self.settings, dlg.values())
        for viewer in self.viewers:                          # a picture viewer that is open follows at once
            viewer.set_wheel_map(self.wheel_map())
        self._say("Mouse wheel saved")

    def _run_wheel_dialog(self, dlg) -> bool:                # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted
