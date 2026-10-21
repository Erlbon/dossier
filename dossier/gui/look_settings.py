"""Settings > Fonts and Bold...: the font of the program and where bold is used."""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFontComboBox, QFormLayout, QGroupBox,
                             QLabel, QPushButton, QVBoxLayout)

from . import look

DEFAULTS = {"font_family": "", "font_size": 0.0, "bold_lists": True, "bold_bars": True}


def _flag(value, default: bool) -> bool:
    return default if value is None else str(value).strip().lower() in ("true", "1", "yes")


def read_look(settings) -> dict:
    g = lambda k: settings.value("view/" + k, None)           # noqa: E731
    try:
        size = max(0.0, min(40.0, float(g("font_size") or 0)))
    except (TypeError, ValueError):
        size = 0.0
    return {"font_family": str(g("font_family") or ""), "font_size": size, "bold_lists": _flag(g("bold_lists"), True),
            "bold_bars": _flag(g("bold_bars"), True)}


def write_look(settings, values: dict) -> None:
    for key, value in values.items():
        settings.setValue("view/" + key, "true" if value is True else "false" if value is False else value)


class LookDialog(QDialog):
    def __init__(self, parent, values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fonts and Bold")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        font_box = QGroupBox("Font")
        form = QFormLayout(font_box)
        self.use_system = QCheckBox("Use the system's font")
        self.use_system.setChecked(not values["font_family"] and not values["font_size"])
        self.family = QFontComboBox()
        self.family.setCurrentFont(QFont(values["font_family"] or look.system_font().family()))
        self.size = QDoubleSpinBox()
        self.size.setRange(6.0, 40.0)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.size.setValue(values["font_size"] or look.system_font().pointSizeF())
        form.addRow(self.use_system)
        form.addRow("Font", self.family)
        form.addRow("Size", self.size)
        layout.addWidget(font_box)
        bold_box = QGroupBox("Bold")
        bf = QFormLayout(bold_box)
        self.bold_lists = QCheckBox("Folders, marked items and the names on the Home page")
        self.bold_lists.setChecked(values["bold_lists"])
        self.bold_bars = QCheckBox("The address bar, the tabs and the buttons")
        self.bold_bars.setChecked(values["bold_bars"])
        bf.addRow(self.bold_lists)
        bf.addRow(self.bold_bars)
        layout.addWidget(bold_box)
        self.sample = QLabel("Sample: Documents   report.docx   2.9 K   2026-10-20")
        layout.addWidget(self.sample)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.defaults = QPushButton("Back to the defaults")
        self.defaults.setAutoDefault(False)
        buttons.addButton(self.defaults, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.defaults.clicked.connect(self._reset)
        layout.addWidget(buttons)
        for w in (self.family, self.size):
            (w.currentFontChanged if w is self.family else w.valueChanged).connect(self._changed)
        self.use_system.toggled.connect(self._changed)
        self._changed()

    def _reset(self) -> None:
        self.use_system.setChecked(True)
        self.bold_lists.setChecked(True)
        self.bold_bars.setChecked(True)

    def _changed(self, *_args) -> None:
        manual = not self.use_system.isChecked()
        self.family.setEnabled(manual)
        self.size.setEnabled(manual)
        self.sample.setFont(QFont(self.family.currentFont().family(), int(self.size.value())) if manual else look.system_font())

    def values(self) -> dict:
        if self.use_system.isChecked():
            family, size = "", 0.0
        else:
            family, size = self.family.currentFont().family(), float(self.size.value())
        return {"font_family": family, "font_size": size, "bold_lists": self.bold_lists.isChecked(),
                "bold_bars": self.bold_bars.isChecked()}


class LookMixin:
    """Part of ``MainWindow``."""

    def apply_look(self) -> None:
        """Put the stored font and bold choices to work: the program's font, the lists, the bars."""
        v = read_look(self.settings)
        look.set_bold(v["bold_lists"], v["bold_bars"])
        look.apply_font(v["font_family"], v["font_size"])
        for panel in (self.left, self.right):
            panel.restyle()
            panel.model.refresh_all()
            panel.tabs.update()
            panel.table.verticalHeader().setDefaultSectionSize(panel.fontMetrics().height() + 6)

    def open_look_settings(self) -> None:
        dlg = LookDialog(self, read_look(self.settings))
        if not self._run_look_dialog(dlg):
            return
        write_look(self.settings, dlg.values())
        self.apply_look()
        self._say("Fonts and bold saved")

    def _run_look_dialog(self, dlg) -> bool:                  # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted
