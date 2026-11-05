"""Mark > Mark by Pattern... (Ctrl+F) and Unmark by Pattern...: a name pattern, and optionally size, date and attributes.

The size, date and attribute boxes are the Search dialog's; the test is ``core.search.fits``, the same one Search uses. Everything is
judged from the listing the panel already holds, so marking never touches the disk.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout

from ..core.search import BadCriteria, Criteria, validate
from .owned_dialog import OwnedDialog
from .search_dialog import _AttributeBox, _DateBox, _SizeBox

PATTERN_HINT = "*.jpg;*.png   or  *.log !debug*   or  backup*/ for folders   (empty: every name)"


class MarkDialog(OwnedDialog):
    def __init__(self, parent, title: str, pattern: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.pattern = QLineEdit(pattern)
        self.pattern.setPlaceholderText(PATTERN_HINT)
        self.pattern.selectAll()
        form.addRow("Name", self.pattern)
        layout.addLayout(form)
        more = QGroupBox("Only if (leave empty for any)")
        sub = QFormLayout(more)
        self.min_size, self.max_size = _SizeBox(), _SizeBox()
        self.after, self.before = _DateBox("Changed on or after"), _DateBox("Changed on or before")
        self.attributes = _AttributeBox()
        sub.addRow("At least", self.min_size)
        sub.addRow("At most", self.max_size)
        sub.addRow("", self.after)
        sub.addRow("", self.before)
        sub.addRow("Must be", self.attributes)
        layout.addWidget(more)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.pattern.setFocus()

    def answer(self) -> tuple:
        """``(pattern, criteria)``; raises BadCriteria when a box cannot be used."""
        c = Criteria(root="", min_size=self.min_size.value(), max_size=self.max_size.value(), newer_than=self.after.value(False),
                     older_than=self.before.value(True), attributes=self.attributes.value(), kinds="both")
        validate(c)
        return self.pattern.text().strip(), c

    def _accept(self) -> None:
        try:
            self.answer()
        except BadCriteria as e:
            self.problem.setText(f"Cannot mark: {e}.")
            return
        self.accept()


def ask_mark(parent, title: str, pattern: str) -> Optional[tuple]:
    dlg = MarkDialog(parent, title, pattern)
    return dlg.answer() if dlg.exec() == MarkDialog.DialogCode.Accepted else None
