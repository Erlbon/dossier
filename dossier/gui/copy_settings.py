"""Settings > Copy and Move...: every setting that changes how files are copied or moved, in one dialog.

They were three menu entries (speed limit, verify, ask on error) and a few engine options nobody could reach. The values are
kept in the settings file under ``copy/``; ``ExecOptions`` for a run is built from them in ``ops_queue.py``.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
                             QSpinBox, QVBoxLayout)

DEFAULTS = {"limit_mb": 0.0, "verify": False, "ask_on_error": False, "retries": 3, "retry_delay": 0.25, "workers": 0,
            "native": True, "flush": "auto", "ask_on_drop": False}
FLUSH_CHOICES = (("Only for removable and network drives", "auto"), ("Always", "always"), ("Never", "never"))


def _flag(value, default: bool) -> bool:
    return default if value is None else str(value).strip().lower() in ("true", "1", "yes")


def _number(value, default, low, high, kind=float):
    try:
        return max(low, min(high, kind(value)))
    except (TypeError, ValueError):
        return default


def read_settings(settings) -> dict:
    """The copy settings as the user left them (the defaults where nothing is stored)."""
    g = lambda k: settings.value("copy/" + k, None)           # noqa: E731
    flush = str(g("flush") or "auto")
    return {"limit_mb": _number(g("limit_mb"), 0.0, 0.0, 10_000.0),
            "verify": _flag(g("verify"), False), "ask_on_error": _flag(g("ask_on_error"), False),
            "retries": _number(g("retries"), 3, 0, 20, int), "retry_delay": _number(g("retry_delay"), 0.25, 0.0, 30.0),
            "workers": _number(g("workers"), 0, 0, 32, int), "native": _flag(g("native"), True),
            "flush": flush if flush in ("auto", "always", "never") else "auto", "ask_on_drop": _flag(g("ask_on_drop"), False)}


def write_settings(settings, values: dict) -> None:
    for key, value in values.items():
        settings.setValue("copy/" + key, "true" if value is True else "false" if value is False else value)


class CopySettingsDialog(QDialog):
    def __init__(self, parent, values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("Copy and Move")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        speed = QGroupBox("Speed")
        form = QFormLayout(speed)
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 10_000)
        self.limit.setDecimals(1)
        self.limit.setSuffix(" MB/s")
        self.limit.setSpecialValueText("No limit")
        self.limit.setValue(values["limit_mb"])
        self.workers = QSpinBox()
        self.workers.setRange(0, 32)
        self.workers.setSpecialValueText("Choose automatically")
        self.workers.setValue(values["workers"])
        self.native = QCheckBox("Let the system copy large files on the same computer (fastest, keeps everything attached to the file)")
        self.native.setChecked(values["native"])
        form.addRow("Speed limit", self.limit)
        form.addRow("Small files at the same time", self.workers)
        form.addRow("", self.native)
        layout.addWidget(speed)

        safe = QGroupBox("Safety")
        form = QFormLayout(safe)
        self.verify = QCheckBox("Read every copy back and compare it with the original (slower)")
        self.verify.setChecked(values["verify"])
        self.flush = QComboBox()
        for label, key in FLUSH_CHOICES:
            self.flush.addItem(label, key)
        self.flush.setCurrentIndex(max(0, self.flush.findData(values["flush"])))
        form.addRow("", self.verify)
        form.addRow("Push the data to the drive at the end", self.flush)
        layout.addWidget(safe)

        problems = QGroupBox("When a file cannot be copied")
        form = QFormLayout(problems)
        self.retries = QSpinBox()
        self.retries.setRange(0, 20)
        self.retries.setValue(values["retries"])
        self.retry_delay = QDoubleSpinBox()
        self.retry_delay.setRange(0.0, 30.0)
        self.retry_delay.setDecimals(2)
        self.retry_delay.setSuffix(" s")
        self.retry_delay.setValue(values["retry_delay"])
        self.ask = QCheckBox("Ask me what to do (try again, skip, skip all, stop) instead of skipping it")
        self.ask.setChecked(values["ask_on_error"])
        form.addRow("Extra tries for a file another program holds", self.retries)
        form.addRow("Wait before the first retry (doubles each time)", self.retry_delay)
        form.addRow("", self.ask)
        layout.addWidget(problems)

        drop = QGroupBox("Dragging with the mouse")
        form = QFormLayout(drop)
        self.ask_drop = QCheckBox("Show the confirmation box before a drop copies or moves files (conflicts are always asked about)")
        self.ask_drop.setChecked(values["ask_on_drop"])
        form.addRow("", self.ask_drop)
        layout.addWidget(drop)

        note = QLabel("A name that is already taken is asked about in its own dialog, one choice per file.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {"limit_mb": float(self.limit.value()), "verify": self.verify.isChecked(), "ask_on_error": self.ask.isChecked(),
                "retries": int(self.retries.value()), "retry_delay": float(self.retry_delay.value()),
                "workers": int(self.workers.value()), "native": self.native.isChecked(), "flush": self.flush.currentData(),
                "ask_on_drop": self.ask_drop.isChecked()}


class CopySettingsMixin:
    """Part of ``MainWindow``."""

    def copy_settings(self) -> dict:
        return read_settings(self.settings)

    def open_copy_settings(self) -> None:
        dlg = CopySettingsDialog(self, self.copy_settings())
        if not self._run_copy_settings(dlg):
            return
        self.save_copy_settings(dlg.values())

    def _run_copy_settings(self, dlg) -> bool:                # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def save_copy_settings(self, values: dict) -> None:
        write_settings(self.settings, values)
        for action, key in ((self.act_verify, "verify"), (self.act_ask_error, "ask_on_error")):
            action.blockSignals(True)                          # the settings are written above; no second write
            action.setChecked(values[key])
            action.blockSignals(False)
        self._say("Copy and move settings saved")
