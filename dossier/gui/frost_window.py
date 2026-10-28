"""Settings > Appearance > Frosted Background...: the file manager's frame (title row, menu bar, tools bar, command line, function keys,
status line) shows a blurred picture of the screen, while the file lists stay solid so names are always easy to read.

The picture is taken when Dossier opens (or when the setting is turned on: the window hides for a moment so it is not in it) and is not
live: it is the screen as it was, which moves with the window like glass over a still desktop. A remote desktop session gets no frost.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout)

from ..core import glass
from . import frost, theme
from .owned_dialog import OwnedDialog


class FrostDialog(OwnedDialog):
    applied = pyqtSignal(bool, int)             # Apply: show the effect now, with the dialog still open

    def __init__(self, on: bool, level: int, available: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Frosted Background")
        layout = QVBoxLayout(self)
        self.on = QCheckBox("Frost the background of the window")
        self.on.setChecked(on and available)
        self.on.setEnabled(available)
        layout.addWidget(self.on)
        form = QFormLayout()
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, frost.MAX_LEVEL)
        self.slider.setValue(max(1, min(frost.MAX_LEVEL, level)))
        self.value_label = QLabel()
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        form.addRow("Screen shows through", row)
        layout.addLayout(form)
        note = QLabel("The title row, menus, bars and the status line show a blurred picture of your screen; the file lists stay solid. "
                      "The picture is taken when Dossier opens, so it does not follow what happens behind the window afterwards."
                      + ("" if available else " This is not available in a remote desktop session."))
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.Apply)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(lambda: self.applied.emit(*self.values()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.slider.valueChanged.connect(self._refresh)
        self.on.toggled.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.slider.setEnabled(self.on.isChecked())
        self.value_label.setText(f"{self.slider.value()} %")

    def values(self) -> tuple:
        return self.on.isChecked(), self.slider.value()


class FrostMixin:
    """Part of ``MainWindow``: the frosted frame."""

    def init_frost(self) -> None:
        """Called before any bar is built, so they know whether to paint their own background."""
        self._frost_shots: dict = {}
        self._frost_level = self._saved_frost_level()
        frost.set_active(False)
        if str(self.settings.value("frost/on", "false")).lower() == "true" and glass.detect().transparent:
            self._frost_shots = frost.grab_screens()                    # the window is not on the screen yet: it is not in the picture
            frost.set_active(bool(self._frost_shots))

    def _saved_frost_level(self) -> int:
        text = str(self.settings.value("frost/level", ""))
        return max(1, min(frost.MAX_LEVEL, int(text))) if text.isdigit() else frost.DEFAULT_LEVEL

    def set_frost(self, on: bool, level: Optional[int] = None, grabber=None, wait_ms: int = 250) -> bool:
        """Turn the frosted frame on or off (and its strength). Returns whether it is on afterwards."""
        if level is not None:
            self._frost_level = max(1, min(frost.MAX_LEVEL, int(level)))
        self.settings.setValue("frost/on", "true" if on else "false")
        self.settings.setValue("frost/level", self._frost_level)
        if on and not glass.detect().transparent:
            self._say("The frosted background is not available in a remote desktop session")
            on = False
        if on and (not frost.active() or grabber is not None):
            shown = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
            for w in shown:
                w.hide()                                                # so no Dossier window (this dialog included) is in the picture
            if shown:
                QApplication.processEvents()
                if wait_ms:
                    loop = QEventLoop()
                    QTimer.singleShot(wait_ms, loop.quit)
                    loop.exec()
            self._frost_shots = (grabber or frost.grab_screens)()
            for w in shown:
                w.show()
            on = bool(self._frost_shots)
        frost.set_active(on)
        self.tools_bar.restyle()
        self.menuBar().update()
        self.update()
        return on

    def open_frost_settings(self) -> None:
        before = (frost.active(), self._frost_level)
        dlg = FrostDialog(*before, glass.detect().transparent, self)
        dlg.applied.connect(lambda on, level: self.set_frost(on, level))
        if dlg.exec() != FrostDialog.DialogCode.Accepted:
            if (frost.active(), self._frost_level) != before:
                self.set_frost(*before)                                 # Cancel after Apply: back to how it was
            return
        on, level = dlg.values()
        if on != frost.active() or level != self._frost_level:
            self.set_frost(on, level)

    # painting --------------------------------------------------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        screen = self.screen()
        shot = self._frost_shots.get(screen.name()) if (frost.active() and screen is not None) else None
        if shot is None:
            return
        geometry, picture = shot
        origin = self.mapToGlobal(QPoint(0, 0)) - geometry.topLeft()
        painter = QPainter(self)
        painter.drawPixmap(QRect(-origin.x(), -origin.y(), geometry.width(), geometry.height()), picture)
        tint = QColor(theme.current()["card"])
        tint.setAlpha(frost.tint_alpha(self._frost_level))
        painter.fillRect(self.rect(), tint)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if frost.active():
            self.update()                                              # the glass moves over the still picture
