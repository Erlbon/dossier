"""A text field keeps the second keys of card 51A for itself while it has the focus.

Cmd+Backspace deletes text in the command line, and Cmd+Down there lists the history; a window shortcut would take both first and delete
the marked files. Qt asks the focused widget before it runs a shortcut (a ``ShortcutOverride`` event); this filter answers yes for the
second keys when the widget is a text field of the window, so the key reaches the field as an ordinary key press.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

TEXT_FIELDS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


class SecondKeyGuard(QObject):
    """Installed on the application; goes away with its window (its parent)."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.ShortcutOverride or not isinstance(obj, TEXT_FIELDS):
            return False
        if obj.window() is not self.window:
            return False
        keys = self.window.guarded_keys()
        if keys and QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText) in keys:
            event.accept()                                   # the field uses the key; the shortcut does not run
        return False
