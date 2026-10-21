"""The main button of a dialog (Save, Find, Add, Run...) is the gold one, and the one Enter presses.

Every dialog builds its buttons with a ``QDialogButtonBox``; the button with the accept role is the main one. Instead of styling that
button in twenty places, one filter on the application does it whenever a dialog is shown, so a dialog added later gets it too.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QPushButton

from . import theme


def primary_style(t: dict) -> str:
    edge = QColor(t["accent"]).darker(130).name()
    hover = theme.mix(t["accent"], t["bg"], 0.88)
    return (f"QPushButton{{background:{t['accent']};color:{t['accent_fg']};border:1px solid {edge};border-radius:4px;"
            f"padding:4px 16px;min-width:64px;}}"
            f"QPushButton:hover{{background:{hover};}}"
            f"QPushButton:disabled{{background:{t['line']};color:{t['dim']};border-color:{t['line']};}}")


def style_dialog(dialog: QDialog) -> None:
    for box in dialog.findChildren(QDialogButtonBox):
        for button in box.buttons():
            if box.buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole and isinstance(button, QPushButton):
                button.setStyleSheet(primary_style(theme.current()))
                button.setDefault(True)


class PrimaryButtons(QObject):
    """Installed on the application: styles the accept button of every dialog as it is shown."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
            style_dialog(obj)
        return False
