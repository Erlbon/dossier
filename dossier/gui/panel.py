"""One panel of the commander: an address bar, the folder listing, and the folder note as the last
row of the listing (scroll down past the files to read it, like a README under a file list)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QModelIndex, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QTabBar, QToolButton,
                             QTableView, QTextBrowser, QVBoxLayout, QWidget)

from ..core.notes import compose_markdown, find_notes
from ..core.selection import SelectionStore
from ..core.vfs import Entry, FileSystem
from ..core.drives import drive_of, usage_async
from . import icon_set, theme
from .drive_bar import DriveBar
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
    mark_toggle = pyqtSignal()       # Insert
    space = pyqtSignal()             # Space: marks, or types a space into a command being written
    activate = pyqtSignal()
    go_up = pyqtSignal()
    focused = pyqtSignal()
    type_text = pyqtSignal(str)      # a printable key: it starts (or continues) a command
    activate_in_tab = pyqtSignal()   # Ctrl+Enter: open the folder in a new tab
    middle_clicked = pyqtSignal(int)  # middle click on a row: open that folder in a background tab

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middle_clicked.emit(self.indexAt(event.position().toPoint()).row())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        text = event.text()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.switch_panel.emit()
        elif key == Qt.Key.Key_Insert:
            self.mark_toggle.emit()
        elif key == Qt.Key.Key_Space:
            self.space.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.ControlModifier:
            self.activate_in_tab.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activate.emit()
        elif key == Qt.Key.Key_Backspace:
            self.go_up.emit()
        elif key == Qt.Key.Key_Down and self.currentIndex().row() >= self.model().entry_count() - 1:
            bar = self.verticalScrollBar()          # past the last file: reveal the note
            bar.setValue(min(bar.value() + bar.pageStep() // 2, bar.maximum()))
        elif (text and text.isprintable() and not (mods & (Qt.KeyboardModifier.ControlModifier
                                                           | Qt.KeyboardModifier.AltModifier
                                                           | Qt.KeyboardModifier.MetaModifier))):
            self.type_text.emit(text)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit()

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False   # Tab belongs to the commander, not to widget focus


@dataclass
class TabState:
    """What a folder tab remembers while another tab is shown."""
    path: str = ""
    current: str = ""            # the item under the cursor
    sort_col: int = 0
    sort_desc: bool = False
    scroll: int = 0


class PanelTabBar(QTabBar):
    """Folder tabs that draw themselves: rounded top corners, a clear gap between tabs, the current tab filled
    with the gold tint of the cursor row and outlined in gold, the others darker with a thin outline."""

    middle_clicked = pyqtSignal(int)     # a tab was middle-clicked: close it
    new_requested = pyqtSignal()         # double-click on the empty part of the bar
    RADIUS = 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDrawBase(False)
        self.setMouseTracking(True)
        self._hover = -1

    def tabSizeHint(self, index: int) -> QSize:
        hint = super().tabSizeHint(index)
        return QSize(max(96, min(220, hint.width() + 14)), hint.height() + 6)

    def mouseMoveEvent(self, event) -> None:
        hover = self.tabAt(event.position().toPoint())
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def tab_outline(self, index: int) -> QRectF:
        return QRectF(self.tabRect(index).adjusted(2, 4, -2, 0))      # the gap between tabs is the two margins

    def paintEvent(self, event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count()):
            selected = i == self.currentIndex()
            width = 2.0 if selected else 1.0
            r = self.tab_outline(i).adjusted(width / 2, width / 2, -width / 2, 0)   # the line sits on whole pixels
            path = QPainterPath()                        # open at the bottom: the tab grows out of the bar below
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + self.RADIUS)
            path.quadTo(r.left(), r.top(), r.left() + self.RADIUS, r.top())
            path.lineTo(r.right() - self.RADIUS, r.top())
            path.quadTo(r.right(), r.top(), r.right(), r.top() + self.RADIUS)
            path.lineTo(r.right(), r.bottom())
            fill = QPainterPath(path)
            fill.closeSubpath()
            if selected:
                p.fillPath(fill, QColor(t["cursor_bg"]))
            else:
                p.fillPath(fill, QColor(t["line"] if i == self._hover else t["bg"]))
            p.setPen(QPen(QColor(t["accent"] if selected else t["line"]), width))
            p.drawPath(path)
            text_rect = r.adjusted(12, 0, -26, 0)           # room for the close cross on the right
            font = p.font()
            font.setBold(selected)
            p.setFont(font)
            p.setPen(QColor(t["fg"] if selected or i == self._hover else t["dim"]))
            p.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       QFontMetrics(font).elidedText(self.tabText(i), Qt.TextElideMode.ElideRight,
                                                     int(text_rect.width())))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(event.position().toPoint())
            if i >= 0:
                self.middle_clicked.emit(i)
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tabAt(event.position().toPoint()) < 0:
            self.new_requested.emit()
        else:
            super().mouseDoubleClickEvent(event)


class Panel(QFrame):
    folder_changed = pyqtSignal(object)   # the panel
    current_changed = pyqtSignal(object)  # the item under the cursor changed
    activated = pyqtSignal(object)        # the user focused this panel
    message = pyqtSignal(str)

    def __init__(self, fs: FileSystem, selection: SelectionStore, parent=None, dispatch=None) -> None:
        super().__init__(parent)
        self.fs = fs
        self.selection = selection
        self._dispatch = dispatch
        self._last: dict = {}          # drive root -> the folder this panel was in on that drive
        self.notes_enabled = True
        self.model = FolderModel(fs, selection, self)
        self.setObjectName("panel")

        self._tabs: dict = {}          # tab id -> TabState
        self._close_buttons: dict = {}  # tab id -> its small close button
        self._tab_seq = 0
        self._current_tab_id: Optional[int] = None
        self.tabs = PanelTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)         # our own small close buttons, see _attach_close_button
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.new_tab_button = QToolButton()
        self.new_tab_button.setText("+")
        self.new_tab_button.setToolTip("New tab (Ctrl+T)")
        self.new_tab_button.setAutoRaise(True)
        self.new_tab_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)
        tab_row.addWidget(self.tabs)
        tab_row.addWidget(self.new_tab_button)
        tab_row.addStretch(1)
        self.tab_row = QWidget()
        self.tab_row.setObjectName("tabrow")
        self.tab_row.setLayout(tab_row)

        self.drive_bar = DriveBar(dispatch, self)
        self.drive_bar.chosen.connect(self._drive_chosen)
        self.address = QLineEdit()
        self.address.setObjectName("pathbar")
        self.free = QLabel()
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.addWidget(self.drive_bar.chip)
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
        self.table.setIconSize(QSize(16, 16))

        self.note = NoteView(self.table.viewport())
        self.note.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # The gold frame of the active panel wraps everything BELOW the tabs, so the tabs are not drawn inside it
        # (inside, the gold of the selected tab melted into the gold frame and bar).
        self.body = QFrame()
        self.body.setObjectName("panelbody")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.drive_bar.strip)
        body.addWidget(self.bar)
        body.addWidget(self.table, 1)
        layout.addWidget(self.tab_row)
        layout.addSpacing(5)                       # a little distance between the tabs and the box
        layout.addWidget(self.body, 1)

        self.address.returnPressed.connect(self._address_entered)
        self.enter_hook = None         # set by the window: Enter runs a command being written, if there is one
        self.backspace_hook = None     # likewise Backspace edits that command instead of going up
        self.table.activate.connect(self._enter)
        self.table.go_up.connect(self._backspace)
        self.table.doubleClicked.connect(lambda _i: self.open_current())
        self.table.focused.connect(lambda: self.activated.emit(self))
        self.table.verticalScrollBar().valueChanged.connect(lambda _v: self._position_note())
        self.table.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self._position_note())
        self.table.horizontalHeader().sectionResized.connect(lambda *_a: self._position_note())
        self.selection.subscribe(lambda _s: self.model.refresh_marks())
        self.table.selectionModel().currentRowChanged.connect(lambda *_a: self.current_changed.emit(self))
        self.table.activate_in_tab.connect(lambda: self.open_current(new_tab=True))
        self.table.middle_clicked.connect(self._middle_click_row)
        self.tabs.currentChanged.connect(self._tab_switched)
        self.tabs.middle_clicked.connect(self.close_tab)
        self.tabs.new_requested.connect(lambda: self.new_tab())
        self.new_tab_button.clicked.connect(lambda: self.new_tab())
        self._add_tab_entry("")                  # the first tab; set_folder gives it its folder
        self._active = False
        self.restyle()

    # state ---------------------------------------------------------------------------
    @property
    def path(self) -> str:
        return self.model.path

    def set_active(self, active: bool) -> None:
        # The active panel has three signs: a solid accent address bar, an accent frame around the panel, and
        # the full cursor row. The inactive panel is never dimmed (that made it unreadable on dark themes):
        # its text is normal, only its cursor row turns into a quiet grey bar.
        self._active = active
        t = theme.current()
        accent, on_accent = t["accent"], t["accent_fg"]
        self.setStyleSheet(f"#panelbody{{border:2px solid {accent if active else 'transparent'};}}")
        if active:
            self.bar.setStyleSheet(
                f"#pathbarbox{{background:{accent};}}"
                f"#pathbarbox QLineEdit{{background:transparent;color:{on_accent};border:none;font-weight:bold;}}"
                f"#pathbarbox QLabel{{color:{on_accent};}}"
                f"#pathbarbox QToolButton{{color:{on_accent};border:1px solid {on_accent};border-radius:6px;"
                f"padding:1px 6px;background:transparent;font-weight:bold;}}"
                f"#pathbarbox QToolButton::menu-indicator{{image:none;}}")
        else:
            self.bar.setStyleSheet("")
        palette = QPalette(QApplication.palette())
        if not active:
            for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
                palette.setColor(group, QPalette.ColorRole.Highlight, QColor(t["line"]))
                palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(t["fg"]))
        self.table.setPalette(palette)
        self.table.viewport().setPalette(palette)   # the viewport keeps an old copy otherwise (white rows in dark)
        self.drive_bar.set_chip_color(on_accent if active else None)

    def restyle(self) -> None:
        """The colour scheme changed: redraw the active mark, the marked rows and the note."""
        self.set_active(self._active)
        self.drive_bar.restyle()
        t = theme.current()
        # The tabs paint themselves (PanelTabBar.paintEvent). This only styles the row they sit in and the + and
        # close buttons, which are small and quiet until the pointer is on them.
        self.tab_row.setStyleSheet(
            f"#tabrow{{background:{t['card']};}}"
            f"QToolButton{{color:{t['fg']};font-weight:bold;padding:0 8px;border:none;background:transparent;}}"
            f"QTabBar QToolButton{{padding:1px;border-radius:3px;}}"
            f"QTabBar QToolButton:hover{{background:{t['line']};}}")
        self.tabs.update()
        self._style_close_buttons()
        self.model.refresh_marks()
        if self.model.note_row >= 0:
            self._load_note(self.path)

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
        self.drive_bar.set_current_path(path)
        self._update_free(path)
        self._load_note(path)
        row = self.model.row_of(select) if select else -1
        if row < 0 and self.model.entry_count():
            row = 1 if self.model.is_up_row(0) and self.model.entry_count() > 1 else 0
        if row >= 0:
            self.table.setCurrentIndex(self.model.index(row, 0))
        self.table.scrollToTop() if not select else self.table.scrollTo(self.table.currentIndex())
        self._label_current_tab(path)
        self.folder_changed.emit(self)
        return True

    # tabs: each panel has its own, every tab is one folder ----------------------------------------------
    def _add_tab_entry(self, path: str, after: Optional[int] = None) -> int:
        self._tab_seq += 1
        tid = self._tab_seq
        self._tabs[tid] = TabState(path=path)
        index = self.tabs.count() if after is None else after + 1
        # the new tab must not start a switch by itself (a state to load that does not exist yet)
        blocked = self.tabs.blockSignals(True)
        index = self.tabs.insertTab(index, self._tab_label(path))
        self.tabs.setTabData(index, tid)
        self.tabs.setTabToolTip(index, path)
        if self._current_tab_id is None:
            self._current_tab_id = tid
            self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(blocked)
        self._attach_close_button(index, tid)
        return index

    def _attach_close_button(self, index: int, tid: int) -> None:
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setIconSize(QSize(12, 12))
        btn.setToolTip("Close tab (Ctrl+W)")
        btn.clicked.connect(lambda _c=False, t=tid: self.close_tab(self._index_of_tab(t)))
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
        self._close_buttons[tid] = btn
        self._style_close_buttons()

    def _style_close_buttons(self) -> None:
        """A cross drawn in the scheme's colours: dim on the tabs you are not on, full colour on the current one."""
        t = theme.current()
        for tid, btn in list(self._close_buttons.items()):
            try:
                btn.setIcon(icon_set.icon("x", t["fg"] if tid == self._current_tab_id else t["dim"]))
            except RuntimeError:                      # the button went away with its tab
                self._close_buttons.pop(tid, None)

    @staticmethod
    def _tab_label(path: str) -> str:
        return os.path.basename(path.rstrip("\\/")) or path or "..."

    def _index_of_tab(self, tid: Optional[int]) -> int:
        return next((i for i in range(self.tabs.count()) if self.tabs.tabData(i) == tid), -1)

    def _label_current_tab(self, path: str) -> None:
        i = self._index_of_tab(self._current_tab_id)
        if i >= 0:
            self.tabs.setTabText(i, self._tab_label(path))
            self.tabs.setTabToolTip(i, path)
            self._tabs[self._current_tab_id].path = path

    def _save_tab_state(self) -> None:
        st = self._tabs.get(self._current_tab_id)
        if st is None:
            return
        header = self.table.horizontalHeader()
        st.path = self.path or st.path
        st.current = self.current_name()
        st.sort_col = header.sortIndicatorSection()
        st.sort_desc = header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        st.scroll = self.table.verticalScrollBar().value()

    def new_tab(self, path: Optional[str] = None, activate: bool = True) -> None:
        """A new tab, by default a copy of the current folder, next to the current tab."""
        self._save_tab_state()
        where = self.path if path is None else path
        index = self._add_tab_entry(where, after=self.tabs.currentIndex())
        if activate:
            self.tabs.setCurrentIndex(index)         # runs _tab_switched

    def _tab_switched(self, index: int) -> None:
        if index < 0:
            return
        tid = self.tabs.tabData(index)
        if tid == self._current_tab_id:
            return                                   # the same tab, only its number changed
        self._save_tab_state()                       # no-op when the tab we leave was just closed
        self._current_tab_id = tid
        st = self._tabs[tid]
        order = Qt.SortOrder.DescendingOrder if st.sort_desc else Qt.SortOrder.AscendingOrder
        self.table.sortByColumn(st.sort_col, order)
        path = st.path
        while path and not self.set_folder(path, select=st.current):     # a folder that is gone: nearest parent
            parent = os.path.dirname(path.rstrip("\\/"))
            if not parent or parent == path:
                break
            path = parent
        self.table.verticalScrollBar().setValue(st.scroll)
        self._style_close_buttons()

    def close_tab(self, index: int) -> None:
        if self.tabs.count() <= 1 or index < 0 or index >= self.tabs.count():
            return                                   # the last tab stays: a panel always shows a folder
        tid = self.tabs.tabData(index)
        self._tabs.pop(tid, None)
        self._close_buttons.pop(tid, None)
        self.tabs.removeTab(index)                   # when it was the current tab, the neighbour is shown
        self._style_close_buttons()

    def next_tab(self, step: int = 1) -> None:
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def _middle_click_row(self, row: int) -> None:
        entry = self.model.entry_at(row)
        if entry is not None and entry.is_dir and not self.model.is_up_row(row):
            self.new_tab(entry.path, activate=False)

    def tab_paths(self) -> list:
        self._save_tab_state()
        return [self._tabs[self.tabs.tabData(i)].path for i in range(self.tabs.count())]

    def restore_tabs(self, paths: list, active: int = 0) -> None:
        """Replace the tabs by one tab per path (the saved session). Paths that cannot be opened are kept as
        tabs and fall back to their nearest parent when shown."""
        paths = [p for p in paths if p] or [self.path]
        while self.tabs.count() > 1:
            self.close_tab(self.tabs.count() - 1)
        first = self._tabs[self._current_tab_id]
        first.path = paths[0]
        for p in paths[1:]:
            self._add_tab_entry(p)
        self.tabs.setCurrentIndex(0)
        st = first
        while not self.set_folder(st.path):
            parent = os.path.dirname(st.path.rstrip("\\/"))
            if not parent or parent == st.path:
                break
            st.path = parent
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, self._tab_label(self._tabs[self.tabs.tabData(i)].path))
            self.tabs.setTabToolTip(i, self._tabs[self.tabs.tabData(i)].path)
        if 0 < active < self.tabs.count():
            self.tabs.setCurrentIndex(active)

    def _enter(self) -> None:
        if not (self.enter_hook and self.enter_hook()):
            self.open_current()

    def _backspace(self) -> None:
        if not (self.backspace_hook and self.backspace_hook()):
            self.go_up()

    def refresh(self) -> None:
        keep = self.current_name()
        self.set_folder(self.path, select=keep)

    def go_up(self) -> None:
        if self.model.is_up_row(0):
            came_from = os.path.basename(self.path.rstrip("\\/"))
            self.set_folder(self.model.entry_at(0).path, select=came_from)

    def open_current(self, new_tab: bool = False) -> None:
        row = self.table.currentIndex().row()
        entry = self.model.entry_at(row)
        if entry is None:
            return
        if self.model.is_up_row(row):
            self.go_up()
        elif entry.is_dir and new_tab:
            self.new_tab(entry.path)
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
        """Free space comes from a background thread: a dead network share must not freeze the window."""
        self.free.setText("")
        if self._dispatch is None:
            return

        def ready(p: str, usage) -> None:
            def show() -> None:
                if p == self.path:
                    self.free.setText(f"{human_size(usage[1])} free" if usage else "")
            self._dispatch(show)

        usage_async([path], ready)

    def _drive_chosen(self, drive) -> None:
        """Go to a drive: back to where this panel last was on it, else its root."""
        here = drive_of(self.path, self.drive_bar.drives)
        if here is not None and (drive.kind == "home" or here.path != drive.path):
            self._last[here.path] = self.path          # remember where we were when leaving a drive
        target = self._last.get(drive.path, drive.path)
        if drive.kind != "home" and os.path.normcase(target) == os.path.normcase(self.path):
            target = drive.path                          # clicking the drive you are in toggles to its root
        if not self.set_folder(target) and target != drive.path:
            self.set_folder(drive.path)

    def open_drive_menu(self) -> None:
        self.drive_bar.open_menu()

    # the note -------------------------------------------------------------------------
    def set_notes_enabled(self, on: bool) -> None:
        self.notes_enabled = on
        self._load_note(self.path)

    def _load_note(self, path: str) -> None:
        text = compose_markdown(find_notes(self.fs, path)) if self.notes_enabled else ""
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
