"""Files > Properties (Alt+Return): the facts of the selected items, and the metadata inside a file.

Step 1 of the metadata work is read only (docs/metadata-plan.md): the tabs show; nothing here can change a file.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, QTabWidget,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.properties import Gathered, gather
from .background import run_in_background

KIND_TITLES = {"audio": "Tags", "comic": "ComicInfo", "video": "Video details"}


class PropertiesDialog(QDialog):
    def __init__(self, parent, data: Gathered) -> None:
        super().__init__(parent)
        self.setWindowTitle(data.title)
        self.setMinimumWidth(560)
        self.data = data
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
        buttons = QDialogButtonBox()
        self.copy_button = QPushButton("Copy All")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self.copy_all)
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda b: self.accept() if b is not self.copy_button else None)
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
            self._show_properties_dialog(PropertiesDialog(self, data))

        run_in_background(self, self.cmd_runner, "Reading properties", work, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Properties")

    def _show_properties_dialog(self, dlg) -> None:       # a seam for tests
        dlg.exec()
