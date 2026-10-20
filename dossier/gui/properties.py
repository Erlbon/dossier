"""Files > Properties (Alt+Return): the facts of the selected items, and the metadata inside a file.

Step 1 of the metadata work is read only (docs/metadata-plan.md): the tabs show; nothing here can change a file.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.filetags import CannotHoldTags, TagChange, apply_change, clean_tags
from ..core.properties import Gathered, gather
from .background import run_in_background

KIND_TITLES = {"audio": "Audio tags", "comic": "ComicInfo", "video": "Video details"}
LABELS = ("red", "orange", "yellow", "green", "blue", "purple", "grey")
KEEP = "(leave as it is)"


def split_tags(text: str) -> list:
    """The tags typed into a box: separated by commas or semicolons."""
    return clean_tags(text.replace(";", ",").split(","))


class PropertiesDialog(QDialog):
    def __init__(self, parent, data: Gathered, known_tags=()) -> None:
        super().__init__(parent)
        self.setWindowTitle(data.title)
        self.setMinimumWidth(560)
        self.data = data
        self.known_tags = sorted(set(known_tags), key=str.casefold)
        self.change = None                                 # set by Save Tags: what to write
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        general = QWidget()
        form = QFormLayout(general)
        for fact in data.facts:
            value = QLabel(fact.value)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            form.addRow(fact.label, value)
        self.tabs.addTab(general, "General")
        if data.meta is not None:
            self.tabs.addTab(self._metadata_tab(data.meta), KIND_TITLES.get(data.meta_kind, "Metadata"))
        if data.tags or data.tags_reason:
            self.tabs.addTab(self._tags_tab(data), "Tags")
        buttons = QDialogButtonBox()
        self.save_button = QPushButton("Save Tags")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save_tags)
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.save_button.setVisible(bool(data.tags) and data.tags_can_write)       # after addButton: adding re-shows it
        self.copy_button = QPushButton("Copy All")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self.copy_all)
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda b: self.accept() if b not in (self.copy_button, self.save_button) else None)
        layout.addWidget(buttons)

    def _metadata_tab(self, meta) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        if meta.error:
            note = QLabel(meta.error)
            note.setWordWrap(True)
            box.addWidget(note)
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Field", "Value"])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setColumnWidth(0, 190)
        bold = QFont()
        bold.setBold(True)
        for group in meta.groups():
            top = QTreeWidgetItem([group])
            top.setFont(0, bold)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            tree.addTopLevelItem(top)
            for f in meta.fields:
                if f.group == group:
                    child = QTreeWidgetItem([f.label, f.value])
                    child.setToolTip(1, f.value)
                    top.addChild(child)
            top.setExpanded(True)
        box.addWidget(tree)
        hint = QLabel("Read only for now: changing these values comes in a later step.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.tree = tree
        return page

    # the Tags tab ---------------------------------------------------------------------------------------------------
    def _tags_tab(self, data: Gathered) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        if data.tags_reason:
            note = QLabel(data.tags_reason)
            note.setWordWrap(True)
            box.addWidget(note)
        self.many = len(data.paths) > 1
        if not data.tags:
            box.addStretch(1)
            return page
        form = QFormLayout()
        writable = data.tags_can_write
        records = list(data.tags.values())
        self.rating = QComboBox()
        self.label = QComboBox()
        if self.many:
            common = [t for t in records[0].tags if all(r.has(t) for r in records)]
            some = sorted({t for r in records for t in r.tags if not all(x.has(t) for x in records)}, key=str.casefold)
            summary = QLabel("On every item: " + (", ".join(common) or "none") + chr(10) + "On some: " + (", ".join(some) or "none"))
            summary.setWordWrap(True)
            form.addRow("Tags now", summary)
            self.add_edit, self.remove_edit = QLineEdit(), QLineEdit()
            self.add_edit.setPlaceholderText("tags to add to every item, separated by commas")
            self.remove_edit.setPlaceholderText("tags to take off every item")
            form.addRow("Add", self.add_edit)
            form.addRow("Remove", self.remove_edit)
            self.rating.addItem(KEEP, None)
            self.label.addItem(KEEP, None)
        else:
            current = records[0]
            self.tag_edit = QLineEdit(", ".join(current.tags))
            self.tag_edit.setPlaceholderText("holiday, 2019, family")
            form.addRow("Tags", self.tag_edit)
            self.pick = None
            if self.known_tags:
                pick = QComboBox()
                pick.addItem("Add a tag you used before...", "")
                for t in self.known_tags:
                    pick.addItem(t, t)
                pick.activated.connect(lambda i, p=pick: (self._pick(p.itemData(i)), p.setCurrentIndex(0)))
                form.addRow("", pick)
                self.pick = pick
            self.note_edit = QPlainTextEdit(current.note)
            self.note_edit.setFixedHeight(70)
        self.rating.addItem("No rating", 0)
        for n in range(1, 6):
            self.rating.addItem(chr(0x2605) * n, n)
        self.label.addItem("No label", "")
        for name in LABELS:
            self.label.addItem(name.capitalize(), name)
        if not self.many:
            self.rating.setCurrentIndex(max(0, self.rating.findData(current.rating)))
            self.label.setCurrentIndex(max(0, self.label.findData(current.label)))
        form.addRow("Rating", self.rating)
        form.addRow("Label", self.label)
        if not self.many:
            form.addRow("Note", self.note_edit)
        box.addLayout(form)
        widgets = ([self.add_edit, self.remove_edit] if self.many else [self.tag_edit, self.note_edit]) + [self.rating, self.label]
        if not self.many and self.pick is not None:
            widgets.append(self.pick)
        for w in widgets:
            w.setEnabled(writable)
        box.addStretch(1)
        hint = QLabel("Tags are kept on the file itself (no database). They are lost when a file is copied by a program that "
                      "ignores them, or sent by mail or to most cloud services.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        return page

    def _pick(self, tag) -> None:
        if tag:
            self.tag_edit.setText(", ".join(clean_tags(split_tags(self.tag_edit.text()) + [tag])))

    def tag_change(self) -> TagChange:
        """What the Tags tab asks for (empty when nothing was changed)."""
        data = self.data
        if not data.tags or not data.tags_can_write:
            return TagChange()
        if self.many:
            return TagChange(add=split_tags(self.add_edit.text()), remove=split_tags(self.remove_edit.text()),
                             rating=self.rating.currentData(), label=self.label.currentData())
        current = next(iter(data.tags.values()))
        change = TagChange()
        typed = split_tags(self.tag_edit.text())
        if [t.casefold() for t in typed] != [t.casefold() for t in current.tags]:
            change.replace = typed
        if self.rating.currentData() != current.rating:
            change.rating = self.rating.currentData()
        if self.label.currentData() != current.label:
            change.label = self.label.currentData()
        if self.note_edit.toPlainText() != current.note:
            change.note = self.note_edit.toPlainText()
        return change

    def _save_tags(self) -> None:
        self.change = self.tag_change()
        self.accept()

    def text(self) -> str:
        lines = [self.data.title, ""]
        lines += [f"{f.label}: {f.value}" for f in self.data.facts]
        if self.data.meta is not None:
            lines.append("")
            for g in self.data.meta.groups():
                lines.append(g)
                lines += [f"  {f.label}: {f.value}" for f in self.data.meta.fields if f.group == g]
        return chr(10).join(lines)

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.text())


class PropertiesMixin:
    """Part of ``MainWindow``."""

    @property
    def _known_tags(self) -> set:
        """Every tag seen or saved in this session (the "used before" list). Nothing is stored."""
        return self.__dict__.setdefault("_known_tag_set", set())

    def show_properties(self) -> None:
        panel = self.active
        if panel.is_home:
            self._say("The Home page lists shortcuts: open a folder to see the properties of its items")
            return
        paths = [p for p in panel.targets() if self.fs.basename(p) != ".."]
        if not paths:
            self._say("Nothing to show: mark items or put the cursor on one")
            return

        def work(progress, cancel):
            progress(0, 0)
            return gather(self.fs, paths, cancel)

        def finished(data) -> None:
            for t in data.tags.values():
                self._known_tags.update(t.tags)
            dlg = PropertiesDialog(self, data, self._known_tags)
            self._show_properties_dialog(dlg)
            if dlg.change is not None and not dlg.change.is_empty():
                self._write_tags(list(data.paths), dlg.change)

        run_in_background(self, self.cmd_runner, "Reading properties", work, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Properties")

    def _show_properties_dialog(self, dlg) -> None:       # a seam for tests
        dlg.exec()

    def _write_tags(self, paths: list, change) -> None:
        """Save the change on every item, on a thread; say what could not be done."""
        failed: list = []

        def work(progress, cancel):
            saved = 0
            for i, p in enumerate(paths):
                progress(i, len(paths))
                try:
                    t = apply_change(p, change)
                    self._known_tags.update(t.tags)
                    saved += 1
                except CannotHoldTags:
                    failed.append((p, "this drive cannot store tags"))
                except OSError as e:
                    failed.append((p, e.strerror or str(e)))
            return saved

        def finished(saved: int) -> None:
            text = f"Tags saved on {saved} item{'s' if saved != 1 else ''}"
            if failed:
                text += f"; {len(failed)} could not be changed"
                self.dialogs.info("Tags", chr(10).join(f"{self.fs.basename(p)}: {why}" for p, why in failed[:10]))
            self._say(text)
            for panel in (self.left, self.right):
                panel.refresh_tags()                     # the Tags and Rating columns show what was just saved

        run_in_background(self, self.cmd_runner, "Saving tags", work, on_result=finished, tracked=self._size_jobs,
                          failed_title="Tags")
