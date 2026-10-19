"""One panel of the commander: an address bar, the folder listing, and the folder note as the last
row of the listing (scroll down past the files to read it, like a README under a file list)."""
from __future__ import annotations

import os
import shutil
from typing import Optional

from PyQt6.QtCore import QModelIndex, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableView,
                             QTextBrowser, QVBoxLayout, QWidget)

from ..core.notes import compose_markdown, find_notes
from ..core.selection import SelectionStore
from ..core.vfs import Entry, FileSystem
from .models import FolderModel, human_size

SAFE_SCHEMES = ("http", "https", "mailto")


class NoteView(QTextBrowser):
    """The rendered note. It never scrolls by itself: it is as tall as its text and the list scrolls."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.anchorClicked.connect(self._open_link)

    @staticmethod
    def _open_link(url: QUrl) -> None:
        if url.scheme() in SAFE_SCHEMES:   # V4: links limited to http, https and mailto
            QDesktopServices.openUrl(url)

    def fit(self, width: int) -> int:
        self.document().setTextWidth(max(width - 24, 80))
        height = int(self.document().size().height()) + 16
        self.setFixedHeight(height)
        return height

    def wheelEvent(self, event) -> None:   # let the list scroll instead
        event.ignore()


class PanelTable(QTableView):
    switch_panel = pyqtSignal()
    mark_toggle = pyqtSignal()
    activate = pyqtSignal()
    go_up = pyqtSignal()
    focused = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.switch_panel.emit()
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Insert):
            self.mark_toggle.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activate.emit()
        elif key == Qt.Key.Key_Backspace:
            self.go_up.emit()
        elif key == Qt.Key.Key_Down and self.currentIndex().row() >= self.model().entry_count() - 1:
            bar = self.verticalScrollBar()          # past the last file: reveal the note
            bar.setValue(min(bar.value() + bar.pageStep() // 2, bar.maximum()))
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit()

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False   # Tab belongs to the commander, not to widget focus


class Panel(QWidget):
    folder_changed = pyqtSignal(object)   # the panel
    activated = pyqtSignal(object)        # the user focused this panel
    message = pyqtSignal(str)

    def __init__(self, fs: FileSystem, selection: SelectionStore, parent=None) -> None:
        super().__init__(parent)
        self.fs = fs
        self.selection = selection
        self.model = FolderModel(fs, selection, self)
        self.setObjectName("panel")

        self.address = QLineEdit()
        self.address.setObjectName("pathbar")
        self.free = QLabel()
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.addWidget(self.address, 1)
        bar.addWidget(self.free)
        self.bar = QWidget()
        self.bar.setObjectName("pathbarbox")
        self.bar.setLayout(bar)

        self.table = PanelTable()
        self.table.setModel(self.model)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)   # every column resizable
        header.setSortIndicatorShown(True)
        self.table.setSortingEnabled(True)                                  # and sortable
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)             # the header defaults to descending
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 130)
        header.setStretchLastSection(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self.note = NoteView(self.table.viewport())
        self.note.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.bar)
        layout.addWidget(self.table, 1)

        self.address.returnPressed.connect(self._address_entered)
        self.table.activate.connect(self.open_current)
        self.table.go_up.connect(self.go_up)
        self.table.doubleClicked.connect(lambda _i: self.open_current())
        self.table.focused.connect(lambda: self.activated.emit(self))
        self.table.verticalScrollBar().valueChanged.connect(lambda _v: self._position_note())
        self.table.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self._position_note())
        self.table.horizontalHeader().sectionResized.connect(lambda *_a: self._position_note())
        self.selection.subscribe(lambda _s: self.model.refresh_marks())
        self.set_active(False)

    # state ---------------------------------------------------------------------------
    @property
    def path(self) -> str:
        return self.model.path

    def set_active(self, active: bool) -> None:
        # Only the address bar shows which panel is active. The list keeps the normal system colours in
        # both panels (the inactive one is never dimmed: that made it unreadable on dark themes).
        self.bar.setStyleSheet("#pathbarbox{background:rgba(217,160,91,90);}" if active else "")

    def current_entry(self) -> Optional[Entry]:
        row = self.table.currentIndex().row()
        if row < 0 or self.model.is_up_row(row):
            return None
        return self.model.entry_at(row)

    def current_name(self) -> str:
        e = self.current_entry()
        return os.path.basename(e.path) if e else ""

    # navigation ----------------------------------------------------------------------
    def set_folder(self, path: str, select: str = "") -> bool:
        """Show ``path``. Returns False (with a message) when it cannot be listed."""
        try:
            self.model.set_folder(path)
        except OSError as e:
            self.message.emit(f"Cannot open {path}: {e.strerror or e}")
            return False
        self.address.setText(path)
        self._update_free(path)
        self._load_note(path)
        row = self.model.row_of(select) if select else -1
        if row < 0 and self.model.entry_count():
            row = 1 if self.model.is_up_row(0) and self.model.entry_count() > 1 else 0
        if row >= 0:
            self.table.setCurrentIndex(self.model.index(row, 0))
        self.table.scrollToTop() if not select else self.table.scrollTo(self.table.currentIndex())
        self.folder_changed.emit(self)
        return True

    def refresh(self) -> None:
        keep = self.current_name()
        self.set_folder(self.path, select=keep)

    def go_up(self) -> None:
        if self.model.is_up_row(0):
            came_from = os.path.basename(self.path.rstrip("\\/"))
            self.set_folder(self.model.entry_at(0).path, select=came_from)

    def open_current(self) -> None:
        row = self.table.currentIndex().row()
        entry = self.model.entry_at(row)
        if entry is None:
            return
        if self.model.is_up_row(row):
            self.go_up()
        elif entry.is_dir:
            self.set_folder(entry.path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(entry.path))

    def _address_entered(self) -> None:
        text = self.address.text().strip()
        if text and not self.set_folder(os.path.normpath(os.path.expanduser(text))):
            self.address.setText(self.path)
        self.table.setFocus()

    def _update_free(self, path: str) -> None:
        try:
            self.free.setText(f"{human_size(shutil.disk_usage(path).free)} free")
        except OSError:
            self.free.setText("")

    # the note -------------------------------------------------------------------------
    def _load_note(self, path: str) -> None:
        text = compose_markdown(find_notes(self.fs, path))
        self.model.set_has_note(bool(text))
        if not text:
            self.note.hide()
            return
        self.note.setMarkdown(text)
        self._place_note()

    def _place_note(self) -> None:
        row = self.model.note_row
        if row < 0:
            return
        self.table.setSpan(row, 0, 1, self.model.columnCount())
        height = self.note.fit(self.table.viewport().width())
        self.table.setRowHeight(row, height)   # the row is empty space; the note is laid over it
        self._position_note()

    def _position_note(self) -> None:
        row = self.model.note_row
        if row < 0:
            self.note.hide()
            return
        rect = self.table.visualRect(self.model.index(row, 0))
        self.note.setGeometry(0, rect.top(), self.table.viewport().width(), self.note.height())
        self.note.show()
        self.note.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.model.note_row >= 0:
            self._place_note()

    # acting on items (S4) ----------------------------------------------------------------
    def targets(self) -> list:
        """The marked items, else the item under the cursor."""
        marked = self.selection.paths()
        if marked:
            return marked
        e = self.current_entry()
        return [e.path] if e else []
