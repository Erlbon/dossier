"""Tools > Rules > Folder Rules...: this folder's rules, with Add, Edit and Remove (card 68A). Nothing here changes a file; the rules only
ever propose a plan (``gui/folder_rules.py``)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QPushButton, QSpinBox, QVBoxLayout)

from ..core.folder_rules import ACTIONS, FolderRule, describe, problem
from .owned_dialog import OwnedDialog

ACTION_TEXTS = {"move": "Move to", "copy": "Copy to", "delete": "Delete to the recycle bin"}
MB = 1 << 20


class RuleForm(OwnedDialog):
    """One rule: which items, and what to do with them."""

    def __init__(self, parent, rule: Optional[FolderRule] = None, folder: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Folder Rule" if rule is None else "Edit Folder Rule")
        self.folder = folder
        self.rule_id = rule.id if rule is not None else ""
        form = QFormLayout()
        self.patterns = QLineEdit(rule.patterns if rule else "")
        self.patterns.setPlaceholderText("for example: *.pdf;*.docx")
        self.patterns.setToolTip("Name patterns as in Mark > Mark by Pattern: *.pdf;*.docx, with !keep* to leave some out, "
                                 "and a name ending in / for folders.")
        form.addRow("Items named", self.patterns)
        self.older = QSpinBox()
        self.older.setRange(0, 36500)
        self.older.setSuffix(" days")
        self.older.setSpecialValueText("any age")
        self.older.setValue(rule.older_days if rule else 0)
        self.older.setToolTip("Only items last changed more than this long ago.")
        form.addRow("Older than", self.older)
        self.larger = QSpinBox()
        self.larger.setRange(0, 10_000_000)
        self.larger.setSuffix(" MB")
        self.larger.setSpecialValueText("any size")
        big = rule.larger_than if rule else 0
        self.larger.setValue(0 if not big else max(1, round(big / MB)))
        self.larger.setToolTip("Only files bigger than this. Folders are never matched by size.")
        form.addRow("Larger than", self.larger)
        self.action = QComboBox()
        for key in ACTIONS:
            self.action.addItem(ACTION_TEXTS[key], key)
        self.action.setCurrentIndex(max(0, ACTIONS.index(rule.action)) if rule and rule.action in ACTIONS else 0)
        self.action.currentIndexChanged.connect(self._sync)
        form.addRow("Then", self.action)
        where = QHBoxLayout()
        self.dest = QLineEdit(rule.dest if rule else "")
        self.dest.setPlaceholderText("for example: Archive/<year>")
        self.dest.setToolTip("A folder. <year> and <month> are the year and month the item was last changed. A path that is not "
                             "complete is below this folder.")
        self.browse = QPushButton("Browse...")
        self.browse.setAutoDefault(False)
        self.browse.clicked.connect(self._browse)
        where.addWidget(self.dest, 1)
        where.addWidget(self.browse)
        self.dest_row = where
        form.addRow("Folder", where)
        self._form = form
        self.error = QLabel()
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(self.error)
        box.addWidget(buttons)
        self._sync()

    def _sync(self) -> None:
        on = self.action.currentData() != "delete"
        self.dest.setEnabled(on)
        self.browse.setEnabled(on)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose the folder", self.folder)
        if chosen:
            self.dest.setText(chosen)

    def rule(self) -> FolderRule:
        extra = {"id": self.rule_id} if self.rule_id else {}
        return FolderRule(self.patterns.text().strip(), str(self.action.currentData()), self.dest.text().strip(),
                          self.older.value(), self.larger.value() * MB, **extra)

    def _accept(self) -> None:
        why = problem(self.rule())
        if why:
            self.error.setText(why)
            return
        self.accept()


class FolderRulesDialog(OwnedDialog):
    """The list of this folder's rules. ``rules`` holds the answer after OK."""

    def __init__(self, parent, folder: str, rules: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Folder Rules")
        self.resize(640, 360)
        self.folder = folder
        self.rules = list(rules)
        box = QVBoxLayout(self)
        intro = QLabel(f"Rules for {folder}. They never act alone: when you open this folder, or choose Tools > Rules > Run Rules, "
                       "they make a plan, and nothing changes until you press Run. The first rule that matches an item decides.")
        intro.setWordWrap(True)
        box.addWidget(intro)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        for b, slot in ((self.add_button, self.add), (self.edit_button, self.edit), (self.remove_button, self.remove),
                        (self.up_button, lambda: self.move(-1)), (self.down_button, lambda: self.move(1))):
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            side.addWidget(b)
        side.addStretch(1)
        row.addLayout(side)
        box.addLayout(row, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self._fill()

    def _fill(self, keep: int = 0) -> None:
        self.list.clear()
        for r in self.rules:
            self.list.addItem(describe(r))
        if self.rules:
            self.list.setCurrentRow(min(max(keep, 0), len(self.rules) - 1))
        has = bool(self.rules)
        for b in (self.edit_button, self.remove_button, self.up_button, self.down_button):
            b.setEnabled(has)

    def _ask(self, rule: Optional[FolderRule]) -> Optional[FolderRule]:        # a seam for tests
        form = RuleForm(self, rule, self.folder)
        return form.rule() if form.exec() == QDialog.DialogCode.Accepted else None

    def add(self) -> None:
        rule = self._ask(None)
        if rule is not None:
            self.rules.append(rule)
            self._fill(len(self.rules) - 1)

    def edit(self) -> None:
        i = self.list.currentRow()
        if not 0 <= i < len(self.rules):
            return
        rule = self._ask(self.rules[i])
        if rule is not None:
            self.rules[i] = rule
            self._fill(i)

    def remove(self) -> None:
        i = self.list.currentRow()
        if 0 <= i < len(self.rules):
            del self.rules[i]
            self._fill(i)

    def move(self, delta: int) -> None:
        i = self.list.currentRow()
        j = i + delta
        if 0 <= i < len(self.rules) and 0 <= j < len(self.rules):
            self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
            self._fill(j)
