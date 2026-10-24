"""The Search dialog: where to look, what the name is like, size, dates and text inside the files.

It only gathers the answers into a ``Criteria``; the search itself is ``core/search.py`` and runs on a thread.
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Optional

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QVBoxLayout, QWidget)

from ..core.search import BadCriteria, Criteria
from .owned_dialog import OwnedDialog

UNITS = (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3), ("bytes", 1))
KINDS = (("Files", "files"), ("Folders", "folders"), ("Files and folders", "both"))


class _SizeBox(QWidget):
    """A number and a unit; empty means no limit."""

    def __init__(self, unit: str = "MB") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.number = QLineEdit()
        self.number.setPlaceholderText("no limit")
        self.number.setMaximumWidth(110)
        self.unit = QComboBox()
        for label, size in UNITS:
            self.unit.addItem(label, size)
        self.unit.setCurrentIndex(max(0, self.unit.findText(unit)))
        row.addWidget(self.number)
        row.addWidget(self.unit)
        row.addStretch(1)

    def value(self) -> Optional[int]:
        text = self.number.text().strip().replace(",", ".")
        if not text:
            return None
        try:
            n = float(text)
        except ValueError:
            raise BadCriteria(f'"{self.number.text().strip()}" is not a size')
        if n < 0:
            raise BadCriteria("a size cannot be negative")
        return int(n * self.unit.currentData())


class _DateBox(QWidget):
    """A date that only counts when its box is ticked."""

    def __init__(self, label: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.on = QCheckBox(label)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setEnabled(False)
        self.on.toggled.connect(self.date.setEnabled)
        row.addWidget(self.on)
        row.addWidget(self.date)
        row.addStretch(1)

    def value(self, end_of_day: bool) -> Optional[float]:
        if not self.on.isChecked():
            return None
        d = self.date.date()
        day = datetime(d.year(), d.month(), d.day())
        return datetime.combine(day.date(), dtime.max if end_of_day else dtime.min).timestamp()


class SearchDialog(OwnedDialog):
    def __init__(self, parent, root: str, last: Optional[Criteria] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.root = QLineEdit(root)
        self.name = QLineEdit()
        self.name.setPlaceholderText("*.jpg;*.png   or a part of the name   (! in front leaves a match out)")
        self.case = QCheckBox("Match case")
        self.kinds = QComboBox()
        for label, key in KINDS:
            self.kinds.addItem(label, key)
        self.subfolders = QCheckBox("Include subfolders")
        self.subfolders.setChecked(True)
        form.addRow("Look in", self.root)
        form.addRow("Name", self.name)
        form.addRow("", self.case)
        form.addRow("Look for", self.kinds)
        form.addRow("", self.subfolders)
        layout.addLayout(form)

        by = QGroupBox("Size and date")
        sub = QFormLayout(by)
        self.min_size, self.max_size = _SizeBox(), _SizeBox()
        self.after, self.before = _DateBox("Changed on or after"), _DateBox("Changed on or before")
        sub.addRow("At least", self.min_size)
        sub.addRow("At most", self.max_size)
        sub.addRow("", self.after)
        sub.addRow("", self.before)
        layout.addWidget(by)

        inside = QGroupBox("Text inside the files")
        t = QFormLayout(inside)
        self.text = QLineEdit()
        self.text.setPlaceholderText("leave empty to search by name only")
        self.regex = QCheckBox("The text is a regular expression")
        self.text_case = QCheckBox("Match case")
        t.addRow("Contains", self.text)
        t.addRow("", self.regex)
        t.addRow("", self.text_case)
        layout.addWidget(inside)

        tagged = QGroupBox("Tags")
        tf = QFormLayout(tagged)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("holiday, 2019   (the file needs all of them)")
        self.min_rating = QComboBox()
        self.min_rating.addItem("Any rating", 0)
        for n in range(1, 6):
            self.min_rating.addItem(chr(0x2605) * n + " or more", n)
        self.label = QComboBox()
        self.label.addItem("Any label", "")
        for name in ("red", "orange", "yellow", "green", "blue", "purple", "grey"):
            self.label.addItem(name.capitalize(), name)
        tf.addRow("Tagged with", self.tags)
        tf.addRow("Rating", self.min_rating)
        tf.addRow("Label", self.label)
        layout.addWidget(tagged)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Search", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if last is not None:
            self._fill(last)
        self.name.setFocus()

    def _fill(self, c: Criteria) -> None:
        self.name.setText(c.name)
        self.case.setChecked(c.case_sensitive)
        self.kinds.setCurrentIndex(max(0, self.kinds.findData(c.kinds)))
        self.subfolders.setChecked(c.subfolders)
        self.text.setText(c.text)
        self.regex.setChecked(c.text_regex)
        self.text_case.setChecked(c.text_case)
        self.tags.setText(", ".join(c.tags))
        self.min_rating.setCurrentIndex(max(0, self.min_rating.findData(c.min_rating)))
        self.label.setCurrentIndex(max(0, self.label.findData(c.label)))

    def criteria(self) -> Criteria:
        """The answers as Criteria; raises BadCriteria when something cannot be used."""
        from ..core.search import validate
        c = Criteria(root=self.root.text().strip(), name=self.name.text().strip(), case_sensitive=self.case.isChecked(),
                     kinds=self.kinds.currentData(), subfolders=self.subfolders.isChecked(),
                     min_size=self.min_size.value(), max_size=self.max_size.value(),
                     newer_than=self.after.value(False), older_than=self.before.value(True),
                     text=self.text.text(), text_regex=self.regex.isChecked(), text_case=self.text_case.isChecked(),
                     tags=[t for t in (p.strip() for p in self.tags.text().replace(";", ",").split(",")) if t],
                     min_rating=self.min_rating.currentData(), label=self.label.currentData())
        if not c.root:
            raise BadCriteria("say where to look")
        validate(c)
        return c

    def _accept(self) -> None:
        try:
            self.criteria()
        except BadCriteria as e:
            self.problem.setText(f"Cannot search: {e}.")
            return
        self.accept()
