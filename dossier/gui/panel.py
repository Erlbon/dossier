"""One panel of the commander: an address bar, the folder listing, and the folder note as the last
row of the listing (scroll down past the files to read it, like a README under a file list)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QModelIndex, QPoint, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QContextMenuEvent, QDesktopServices, QDrag, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QPixmap, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QListView, QStackedWidget, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QTabBar, QToolButton,
                             QTableView, QTextBrowser, QVBoxLayout, QWidget)

from ..core import archives, pathparts, zipfs
from ..core.notes import compose_markdown, find_notes
from ..core.selection import SelectionStore
from ..core.vfs import Entry, FileSystem
from ..core.columns import DEFAULT_HIDDEN, DEFAULT_ORDER, DEFAULT_WIDTHS, KEYS as COLUMN_KEYS, META_KEYS, PROTECTED as PROTECTED_COLUMNS
from ..core import metacolumns
from ..core.columns import index_of as column_index
from redactor_common.core.table_settings import is_column_visible
from redactor_common.gui.column_order import apply_column_order, visual_column_keys
from ..core.drives import drive_of, probe_async, usage_async
from ..core.lights import FAILED, OK, describe
from ..core.home import HOME_URL, is_home
from ..core.platform import has_scheme, path_key
from ..core.sftpfs import NotConnected
from . import icon_set, look, theme
from .address_bar import AddressBar
from .drive_bar import DriveBar
from .models import FolderModel, human_size

SAFE_SCHEMES = ("http", "https", "mailto")


class NoteView(QTextBrowser):
    """The rendered note. It never scrolls by itself: it is as tall as its text and the list scrolls."""

    edit_requested = pyqtSignal()                 # a double click on the note: edit it

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

    HEADING_SCALE = {1: 1.35, 2: 1.2, 3: 1.08}        # the Markdown default (about twice the text) outweighs the file list

    def setMarkdown(self, text: str) -> None:
        super().setMarkdown(text)
        base = self.font().pointSizeF()
        if base <= 0:
            return
        cursor = QTextCursor(self.document())
        block = self.document().begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level > 0:
                scale = self.HEADING_SCALE.get(level, 1.0)
                cursor.setPosition(block.position())
                cursor.setPosition(block.position() + max(block.length() - 1, 0), QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setFontPointSize(base * scale)
                cursor.mergeCharFormat(fmt)
            block = block.next()

    def fit(self, width: int) -> int:
        self.document().setTextWidth(max(width - 24, 80))
        height = int(self.document().size().height()) + 16
        self.setFixedHeight(height)
        return height

    def wheelEvent(self, event) -> None:   # let the list scroll instead
        event.ignore()

    def mouseDoubleClickEvent(self, event) -> None:
        self.edit_requested.emit()


class _FilterEdit(QLineEdit):
    """The quick filter's field: Esc clears the filter, Enter or Down goes back to the list."""
    escaped = pyqtSignal()
    leave = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
            self.leave.emit()
        else:
            super().keyPressEvent(event)


class _FileView:
    """What a list of files does, for the details table and the icon view alike: marking, dragging, dropping, keys, the right-click
    menu. A mixin before the Qt view class, so ``super()`` reaches the Qt view."""

    # Marking several items. The marks are the shared selection; the cursor is the current row.
    #   Space / Insert       mark the item and move down          Ctrl+Space   mark it, stay
    #   Shift+arrows, Page, Home, End   mark everything from where the Shift began to the cursor
    #   Ctrl+arrows          move the cursor only                 Ctrl+click   mark or unmark that item
    #   Shift+click          mark from the cursor to the click    Ctrl+click and drag   mark every item the mouse passes
    #   drag (plain)         carry the item (or all marked items) away
    selection = None            # the SelectionStore, set by the panel
    drag_paths = None           # set by the panel: row -> the paths a drag from that row carries
    drag_source = ""            # set by the panel: its name in a drag, so a drop knows where it came from
    drop_check = None           # set by the panel: (paths, source, row) -> whether a drop here would do something
    content_check = None        # set by the panel: row -> whether a picture or text dropped here could become a new file
    _press = None               # where and on which row the left button went down

    def contextMenuEvent(self, event) -> None:
        """Right-click, or the Menu key / Shift+F10 (then the menu opens at the cursor row)."""
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            row = self.currentIndex().row()
            spot = self.viewport().mapToGlobal(self.visualRect(self.model().index(max(row, 0), 0)).center()) if row >= 0 \
                else self.viewport().mapToGlobal(QPoint(20, 20))
        else:
            row = self.indexAt(event.pos()).row()
            spot = event.globalPos()
            if row >= 0:
                self.setCurrentIndex(self.model().index(row, 0))        # the item under the pointer; the marks stay as they are
        self.context_requested.emit(spot, row)
        event.accept()

    def _set_drop_row(self, row: int) -> None:
        model = self.model()
        if getattr(model, "drop_row", -1) != row:
            model.drop_row = row
            self.viewport().update()

    def _path_of(self, row: int):
        model = self.model()
        entry = model.entry_at(row)
        if entry is None or model.is_up_row(row) or entry.kind in ("header", "action") or model.is_home:
            return None
        return entry.path

    def _begin_range(self, anchor_row: int) -> None:
        if self.selection is not None and getattr(self, "_anchor", None) is None:
            self._anchor = anchor_row
            self._base = set(self.selection.paths())

    def _mark_range(self, row: int) -> None:
        """Marks = what was marked when the range began, plus every item from the anchor to ``row``."""
        if self.selection is None or getattr(self, "_anchor", None) is None:
            return
        lo, hi = sorted((self._anchor, row))
        wanted = set(self._base) | {p for p in (self._path_of(r) for r in range(lo, hi + 1)) if p}
        now = set(self.selection.paths())
        self.selection.remove(now - wanted)
        self.selection.add(wanted - now)

    def _end_range(self) -> None:
        self._anchor = None
        self._base = set()

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Shift:
            self._end_range()
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.BackButton:
            self.history_step.emit(-1)
            return
        if event.button() == Qt.MouseButton.ForwardButton:
            self.history_step.emit(1)
            return
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or not index.isValid():
            super().mousePressEvent(event)
            return
        mods = event.modifiers()
        row = index.row()
        if mods & Qt.KeyboardModifier.ControlModifier:
            path = self._path_of(row)
            self._ctrl_drag = None
            if path and self.selection is not None:
                base = set(self.selection.paths())
                self.selection.toggle(path)
                # Ctrl+click toggles the item; keep the button down and drag to mark (or, when the click took a mark off, to unmark)
                # every item from here to the pointer
                self._ctrl_drag = (row, base, path not in base)
            self.setCurrentIndex(self.model().index(row, 0))
            self._press = None
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            self._end_range()
            self._begin_range(max(0, self.currentIndex().row()))
            self.setCurrentIndex(self.model().index(row, 0))
            self._mark_range(row)
            self._end_range()
            self._press = None
            return
        super().mousePressEvent(event)
        self._press = (event.position().toPoint(), row)       # a drag from here carries the item (or the marked ones) away

    def _ctrl_drag_to(self, row: int) -> None:
        """Ctrl+click and drag: marks (or unmarks) the range from the clicked item to ``row`` on top of what was marked before."""
        start, base, marking = self._ctrl_drag
        lo, hi = sorted((start, row))
        span = {p for p in (self._path_of(r) for r in range(lo, hi + 1)) if p}
        wanted = (base | span) if marking else (base - span)
        now = set(self.selection.paths())
        self.selection.remove(now - wanted)
        self.selection.add(wanted - now)
        self.setCurrentIndex(self.model().index(row, 0))

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_ctrl_drag", None) is not None and event.buttons() & Qt.MouseButton.LeftButton:
            row = self.indexAt(event.position().toPoint()).row()
            if row >= 0:
                self._ctrl_drag_to(row)
            return
        press = self._press
        if press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - press[0]).manhattanLength() >= QApplication.startDragDistance():
                self._press = None
                self._start_drag(press[1])
                return
        super().mouseMoveEvent(event)

    def _start_drag(self, row: int) -> None:
        """Carry the item under the press away, or all marked items when that one is marked."""
        paths = self.drag_paths(row) if self.drag_paths is not None else []
        if not paths:
            return
        from .dragdrop import label, make_mime
        drag = QDrag(self)
        drag.setMimeData(make_mime(paths, self.drag_source, self._stage_function(paths)))
        text = label(paths)
        metrics = QFontMetrics(self.font())
        pixmap = QPixmap(metrics.horizontalAdvance(text) + 24, metrics.height() + 10)
        pixmap.fill(QColor(0, 0, 0, 200))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(12, 5 + metrics.ascent(), text)
        painter.end()
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
        self._set_drop_row(-1)
        self.drag_ended.emit()

    stage_for = None            # set by the panel: paths -> a function that copies them out of an archive or off a server, or None

    def _stage_function(self, paths: list):
        return self.stage_for(paths) if self.stage_for is not None else None

    # taking drops ----------------------------------------------------------------------------------------------
    def _drop_info(self, event):
        from .dragdrop import read_paths
        paths, source = read_paths(event.mimeData())
        return paths, source, self.indexAt(event.position().toPoint()).row()

    def _content_row(self, event) -> Optional[int]:
        """The row under a drop of a picture or text (no files in it) when it could become a new file here, else None."""
        from .dragdrop import content_of
        if self.content_check is None or content_of(event.mimeData()) is None:
            return None
        row = self.indexAt(event.position().toPoint()).row()
        return row if self.content_check(row) else None

    def dragEnterEvent(self, event) -> None:
        paths, source, row = self._drop_info(event)
        if paths and self.drop_check is not None and self.drop_check(paths, source, row) is not None:
            event.acceptProposedAction()
        elif not paths and self._content_row(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        paths, source, row = self._drop_info(event)
        if not paths:
            content_row = self._content_row(event)
            if content_row is None:
                self._set_drop_row(-1)
                event.ignore()
                return
            self._set_drop_row(content_row if content_row >= 0 and self.content_check(content_row) == "folder" else -1)
            event.acceptProposedAction()
            return
        target = self.drop_check(paths, source, row) if paths and self.drop_check is not None else None
        if target is None:
            self._set_drop_row(-1)
            event.ignore()
            return
        self._set_drop_row(row if target != "here" else -1)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_row(-1)
        event.accept()

    def dropEvent(self, event) -> None:
        paths, source, row = self._drop_info(event)
        self._set_drop_row(-1)
        if not paths:
            content_row = self._content_row(event)
            if content_row is None:
                event.ignore()
                return
            from .dragdrop import content_of
            kind, payload = content_of(event.mimeData())
            event.acceptProposedAction()
            self.content_dropped.emit(kind, payload, content_row)
            return
        if self.drop_check is None or self.drop_check(paths, source, row) is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.dropped.emit(paths, row, int(event.modifiers().value), source)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middle_clicked.emit(self.indexAt(event.position().toPoint()).row())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._ctrl_drag = None
            self._press = None
            self._end_range()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        text = event.text()
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):      # first and last item, not the first and last column
            model = self.model()
            row = max(0, model.first_selectable_row()) if key == Qt.Key.Key_Home else model.entry_count() - 1
            shifted = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            if shifted:
                self._begin_range(max(0, self.currentIndex().row()))
            if row >= 0:
                self.setCurrentIndex(model.index(row, 0))
                self.scrollTo(model.index(row, 0))
            if shifted:
                self._mark_range(row)
            return
        shift_nav = (mods & Qt.KeyboardModifier.ShiftModifier and key in (
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown))
        if shift_nav:
            self._begin_range(max(0, self.currentIndex().row()))
            super().keyPressEvent(event)                 # moves the cursor
            self._mark_range(self.currentIndex().row())
            return
        if key == Qt.Key.Key_Space and mods & Qt.KeyboardModifier.ControlModifier:
            path = self._path_of(self.currentIndex().row())
            if path and self.selection is not None:
                self.selection.toggle(path)              # Ctrl+Space marks without moving
            return
        if key == Qt.Key.Key_Escape:
            self.escape.emit()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
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


    zooms = False                # only the icon view zooms with Ctrl+wheel

    def wheelEvent(self, event) -> None:
        if self.zooms and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class PanelTable(_FileView, QTableView):
    switch_panel = pyqtSignal()
    mark_toggle = pyqtSignal()       # Insert
    space = pyqtSignal()             # Space: marks, or types a space into a command being written
    activate = pyqtSignal()
    go_up = pyqtSignal()
    focused = pyqtSignal()
    type_text = pyqtSignal(str)      # a printable key: it starts (or continues) a command
    activate_in_tab = pyqtSignal()   # Ctrl+Enter: open the folder in a new tab
    escape = pyqtSignal()            # Esc: stop waiting for a slow folder
    middle_clicked = pyqtSignal(int)  # middle click on a row: open that folder in a background tab
    history_step = pyqtSignal(int)    # the mouse's back (-1) or forward (+1) button
    dropped = pyqtSignal(list, int, int, object)   # (paths, row under the pointer or -1, keyboard modifiers, source panel)
    content_dropped = pyqtSignal(str, object, int)  # (kind, a QImage or a str, row under the pointer or -1): a picture or text, not files
    drag_ended = pyqtSignal()                      # a drag that started here is over (the lists may have changed)
    context_requested = pyqtSignal(object, int)    # a right-click, or the Menu key: (global position, row under it or -1)
    zoom = pyqtSignal(int)                         # Ctrl+wheel in the icon view: +1 bigger, -1 smaller


class PanelIcons(_FileView, QListView):
    """The thumbnail view: the same list as the table, as a grid of pictures with the names under them."""
    switch_panel = pyqtSignal()
    mark_toggle = pyqtSignal()       # Insert
    space = pyqtSignal()             # Space: marks, or types a space into a command being written
    activate = pyqtSignal()
    go_up = pyqtSignal()
    focused = pyqtSignal()
    type_text = pyqtSignal(str)      # a printable key: it starts (or continues) a command
    activate_in_tab = pyqtSignal()   # Ctrl+Enter: open the folder in a new tab
    escape = pyqtSignal()            # Esc: stop waiting for a slow folder
    middle_clicked = pyqtSignal(int)  # middle click on a row: open that folder in a background tab
    history_step = pyqtSignal(int)    # the mouse's back (-1) or forward (+1) button
    dropped = pyqtSignal(list, int, int, object)   # (paths, row under the pointer or -1, keyboard modifiers, source panel)
    content_dropped = pyqtSignal(str, object, int)  # (kind, a QImage or a str, row under the pointer or -1): a picture or text, not files
    drag_ended = pyqtSignal()                      # a drag that started here is over (the lists may have changed)
    context_requested = pyqtSignal(object, int)    # a right-click, or the Menu key: (global position, row under it or -1)
    zoom = pyqtSignal(int)                         # Ctrl+wheel in the icon view: +1 bigger, -1 smaller

    zooms = True

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSpacing(4)

    def set_size(self, px: int) -> None:
        self.setIconSize(QSize(px, px))
        line = self.fontMetrics().height()
        self.setGridSize(QSize(px + 24, px + line * 2 + 16))



NAV_BUDGET = 0.15      # seconds a folder gets to answer before the window stops waiting for it


class _Listing:
    """A folder being listed on its own thread, so a slow file system can never freeze the window."""

    def __init__(self, fs: FileSystem, path: str, with_notes: bool = False) -> None:
        self.entries: Optional[list] = None
        self.notes: list = []                # the folder's notes, read on this thread too: the window never reads a file
        self.error: Optional[BaseException] = None
        self.cancelled = False
        self.done = threading.Event()
        threading.Thread(target=self._run, args=(fs, path, with_notes), daemon=True, name="dossier-listing").start()

    def _run(self, fs: FileSystem, path: str, with_notes: bool) -> None:
        try:
            self.entries = fs.list(path)
            if with_notes:
                self.notes = find_notes(fs, path, self.entries)
        except BaseException as e:           # reported to the panel, never raised in the thread
            self.error = e
        finally:
            self.done.set()


@dataclass
class TabState:
    """What a folder tab remembers while another tab is shown."""
    path: str = ""
    current: str = ""            # the item under the cursor
    sort_col: int = 0
    sort_desc: bool = False
    scroll: int = 0
    history: list = field(default_factory=list)     # the folders this tab has shown, oldest first
    hpos: int = -1                                  # where in the history the tab stands (back and forward move it)


HISTORY_MAX = 100                           # folders a tab remembers
FRAME = 2                                   # width of the active panel's gold frame, in logical pixels


class PanelTabBar(QTabBar):
    """Folder tabs that draw themselves: rounded top corners, a clear gap between tabs, the current tab filled
    with the gold tint of the cursor row and outlined in gold, the others darker with a thin outline."""

    middle_clicked = pyqtSignal(int)     # a tab was middle-clicked: close it
    new_requested = pyqtSignal()         # double-click on the empty part of the bar
    layout_changed = pyqtSignal()        # the tabs moved or changed size: the outline around the current one must follow
    RADIUS = 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDrawBase(False)
        self.setMouseTracking(True)
        self._hover = -1
        self.panel_active = False        # set by the panel: the current tab then continues the gold frame below it
        self.first_inset = 0             # set by the panel: how far the first tab's left edge is moved in, to line up with the box below

    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        self.layout_changed.emit()

    def tabSizeHint(self, index: int) -> QSize:
        hint = super().tabSizeHint(index)
        # the height follows the text: 4 px gap above the tab, then 5 px above and 5 below the letters (Fusion's own hint added far more)
        return QSize(max(96, min(220, hint.width() + 14)), self.fontMetrics().height() + 14)

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
        # The gap between two tabs is the right margin of one plus the left margin of the next. The first tab has no
        # left margin: its edge lines up with the left edge of the box below it.
        return QRectF(self.tabRect(index).adjusted(self.first_inset if index == 0 else 2, 4, -2, 0))

    def paintEvent(self, event) -> None:
        c = theme.tab_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count()):
            selected = i == self.currentIndex()
            # a thin outline on every tab that is not the current one; the current tab has none of its own: ``PanelOutline`` draws one
            # line around it and the box below together, so tab and box read as a single shape
            width = 1.0
            r = self.tab_outline(i).adjusted(width / 2, width / 2, -width / 2, 0)   # the line sits on whole pixels
            # open at the bottom: the tab grows out of the bar below. It runs past the widget's edge so the clip,
            # not the shape, ends it: at a fractional display scale the last device row is only partly inside
            # the widget and a shape ending there would blend with the background and show as a faint line
            bottom = r.bottom() + 2
            path = QPainterPath()
            path.moveTo(r.left(), bottom)
            path.lineTo(r.left(), r.top() + self.RADIUS)
            path.quadTo(r.left(), r.top(), r.left() + self.RADIUS, r.top())
            path.lineTo(r.right() - self.RADIUS, r.top())
            path.quadTo(r.right(), r.top(), r.right(), r.top() + self.RADIUS)
            path.lineTo(r.right(), bottom)
            fill = QPainterPath(path)
            fill.closeSubpath()
            if selected:
                top = c["active_fill"] if self.panel_active else c["dim_fill"]
                p.fillPath(fill, QColor(top))
                line = None
                text = c["active_text"] if self.panel_active else c["dim_text"]
            else:
                p.fillPath(fill, QColor(c["blue_hover"] if i == self._hover else c["blue_fill"]))
                line, text = c["blue_line"], c["blue_text"]
            if line is not None:
                p.setPen(QPen(QColor(line), width))
                p.drawPath(path)
            text_rect = r.adjusted(12, 0, -26, 0)           # room for the close cross on the right
            font = p.font()
            font.setBold(selected and look.bold_bars)
            p.setFont(font)
            p.setPen(QColor(text))
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


class PanelOutline(QWidget):
    """One 1 px line around the current tab and the box below it together (tab sides and top, the box's top edge beside the tab, its
    sides and bottom), like the thin line around the other tabs. It lies over the panel and lets every click through. The line is a
    darker gold in the active panel and a lighter dim gold in the other; the box of the active panel reaches the panel's edge (its
    frame is the gold fill), the box of the other starts FRAME in."""

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self.panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def path(self) -> Optional[QPainterPath]:
        panel = self.panel
        tabs = panel.tabs
        current = tabs.currentIndex()
        if current < 0 or panel.body.height() <= 0:
            return None
        inset = 0 if panel._active else FRAME
        origin = tabs.mapTo(panel, QPoint(0, 0))
        r = tabs.tab_outline(current).translated(origin.x(), origin.y()).adjusted(0.5, 0.5, -0.5, 0)   # the line sits on whole pixels
        left, right, bottom = inset + 0.5, panel.width() - inset - 0.5, panel.height() - inset - 0.5
        edge = panel.body.y() + 0.5                                  # the top edge of the box, where the tabs rest
        radius = tabs.RADIUS
        path = QPainterPath()
        path.moveTo(left, bottom)
        path.lineTo(left, edge)
        if r.left() > left + 0.01:
            path.lineTo(r.left(), edge)
        path.lineTo(r.left(), r.top() + radius)
        path.quadTo(r.left(), r.top(), r.left() + radius, r.top())
        path.lineTo(r.right() - radius, r.top())
        path.quadTo(r.right(), r.top(), r.right(), r.top() + radius)
        path.lineTo(r.right(), edge)
        if r.right() < right - 0.01:
            path.lineTo(right, edge)
        path.lineTo(right, bottom)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        path = self.path()
        if path is None:
            return
        c = theme.tab_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(c["frame_line"] if self.panel._active else c["inactive_frame_line"]), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class Panel(QFrame):
    folder_changed = pyqtSignal(object)   # the panel
    current_changed = pyqtSignal(object)  # the item under the cursor changed
    activated = pyqtSignal(object)        # the user focused this panel
    message = pyqtSignal(str)
    context_requested = pyqtSignal(object, int)           # a right-click on this panel's list: (global position, row or -1)
    mode_changed = pyqtSignal(object)                    # the view mode or the thumbnail size of this panel changed
    sort_changed = pyqtSignal(object)                    # the owner (not the program) changed the sort order of this panel
    files_dropped = pyqtSignal(list, str, int, object)    # (paths, folder they were dropped on, key modifiers, source panel)
    content_dropped = pyqtSignal(str, object, str)        # (kind, a QImage or a str, folder it was dropped on): a picture or text to make a file of
    column_menu_requested = pyqtSignal(object)    # a right-click on the header (its position)
    columns_reordered = pyqtSignal()              # the user dragged a column
    note_edit_requested = pyqtSignal()    # the note was double-clicked
    open_archived = pyqtSignal(str)       # Enter on a file inside an archive: unpack it, then open it
    sizes_requested = pyqtSignal()        # the button for folder sizes was pressed
    flatten_requested = pyqtSignal()      # the button for "all files below this folder" was pressed
    home_action = pyqtSignal(str)         # an action entry of the Home page was opened (its path says which)
    server_requested = pyqtSignal(str, bool)   # a server of the Home page was opened: (its address, in a new tab)
    connect_needed = pyqtSignal(str)      # a folder of a server that is not connected was asked for (its address)

    def __init__(self, fs: FileSystem, selection: SelectionStore, parent=None, dispatch=None) -> None:
        super().__init__(parent)
        self._active = False                          # set before the first tab is built: its close button reads it
        self._skip_history_for = None                 # a folder shown by back/forward or a tab switch is not new history
        self.fs = fs
        self.selection = selection
        self._dispatch = dispatch
        self._last: dict = {}          # drive root -> the folder this panel was in on that drive
        self.notes_enabled = True
        self.note_paths: list = []                # the files those notes were read from
        self._note_text = ""                      # the Markdown of the folder's notes, as read with its listing
        self.model = FolderModel(fs, selection, self)
        self.setObjectName("panel")

        self._pending = None            # (listing, path, select) of a slow folder being opened
        self._poll = QTimer(self)
        self._poll.setInterval(40)
        self._poll.timeout.connect(self._poll_pending)
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
        # Aligned to the bottom: if the + button (or the font) makes the row taller than the tabs, the extra
        # height goes above the tabs, never as a strip between the tabs and the box below.
        tab_row.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        tab_row.addWidget(self.new_tab_button, 0, Qt.AlignmentFlag.AlignBottom)
        tab_row.addStretch(1)
        self.tab_row = QWidget()
        self.tab_row.setObjectName("tabrow")
        self.tab_row.setLayout(tab_row)

        self.drive_bar = DriveBar(dispatch, self)
        self.drive_bar.chosen.connect(self._drive_chosen)
        self.address_bar = AddressBar(fs)
        self.address = self.address_bar.line             # the text field behind the clickable parts
        self.free = QLabel()
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        self.home_button = QToolButton()
        self.home_button.setObjectName("homebtn")
        self.home_button.setAutoRaise(True)
        self.home_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.home_button.setIconSize(QSize(16, 16))
        self.home_button.setToolTip("The Home page: drives, places, network (Alt+Home)")
        self.home_button.clicked.connect(self.go_home)
        bar.addWidget(self.home_button)
        bar.addWidget(self.drive_bar.chip)
        bar.addWidget(self.address_bar, 1)
        self.sizes_button = QToolButton()
        self.sizes_button.setObjectName("sizesbtn")
        self.sizes_button.setText(chr(0x03A3))                                  # a capital sigma: sum
        self.sizes_button.setAutoRaise(True)
        self.sizes_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sizes_button.setToolTip("Folder sizes: add up the folders in this list, or the marked ones (Alt+Shift+Enter)")
        self.sizes_button.clicked.connect(self.sizes_requested.emit)
        self.flatten_button = QToolButton()
        self.flatten_button.setObjectName("flatbtn")
        self.flatten_button.setText(chr(0x2261))                                # three bars: every file in one list
        self.flatten_button.setAutoRaise(True)
        self.flatten_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.flatten_button.setToolTip("Flatten: every file below this folder as one list in a new tab (Ctrl+Shift+B)")
        self.flatten_button.clicked.connect(self.flatten_requested.emit)
        self.refresh_button = QToolButton()
        self.refresh_button.setObjectName("refreshbtn")
        self.refresh_button.setText(chr(0x21BB))                                # a circular arrow: read this folder again
        self.refresh_button.setAutoRaise(True)
        self.refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh_button.setToolTip("Refresh: read this folder again (Ctrl+R refreshes both panels)")
        self.refresh_button.clicked.connect(self.refresh)
        bar.addWidget(self.free)
        bar.addWidget(self.sizes_button)
        bar.addWidget(self.flatten_button)
        bar.addWidget(self.refresh_button)
        self.bar = QWidget()
        self.bar.setObjectName("pathbarbox")
        self.bar.setLayout(bar)

        self.filter_edit = _FilterEdit()
        self.filter_edit.setPlaceholderText("Filter: part of a name, or a pattern with * and ?   (Esc clears)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.hide()
        self.table = PanelTable()
        self.table.selection = selection
        self.table.drag_paths = self._paths_to_drag
        self.table.drag_source = str(id(self))
        self.table.drop_check = self._drop_target
        self.table.content_check = self._content_target
        self.table.stage_for = self._stage_for_paths
        self.table.content_dropped.connect(self._content_dropped)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.table.dropped.connect(self._table_dropped)
        self.table.context_requested.connect(self.context_requested.emit)
        self.table.drag_ended.connect(self.refresh)
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
        self.layout_rule_path = ""        # the folder whose layout rule is applied to this panel now ("" for none)
        self._applying_layout = False     # the program is setting columns, mode or sort: not a choice of the owner
        self.sort_before_rule = None      # the sort the panel had before a folder rule took over: (key, descending)
        header.sortIndicatorChanged.connect(self._sort_indicator_changed)
        for key, width in DEFAULT_WIDTHS.items():
            self.table.setColumnWidth(column_index(key), width)
        header.setStretchLastSection(True)
        header.setSectionsMovable(True)                                      # drag a column header to move the column
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # right-click: show or hide columns
        header.customContextMenuRequested.connect(self.column_menu_requested.emit)
        header.sectionMoved.connect(self._column_moved)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setIconSize(QSize(16, 16))

        self.icons = PanelIcons()                          # the thumbnail view: the same list, the same cursor and marks
        self._setup_view(self.icons)
        self.icons.setModel(self.model)
        self.icons.setSelectionModel(self.table.selectionModel())
        self.icons.setModelColumn(0)
        self.icon_px = 128
        self.view_mode = "details"
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.icons)

        self._note_row_set = -1                    # the row whose span and height were set for a note
        self.note = NoteView(self.table.viewport())
        self.note.edit_requested.connect(self.note_edit_requested.emit)
        self.note.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # The gold frame of the active panel wraps everything below the tabs and has no top edge: the tabs rest
        # directly on the address bar, and the current tab (the same gold) flows into it.
        self.body = QFrame()
        self.body.setObjectName("panelbody")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(FRAME, 0, FRAME, FRAME)       # the frame is the fill behind these margins, not a border
        body.setSpacing(0)
        body.addWidget(self.drive_bar.strip)
        body.addWidget(self.bar)
        body.addWidget(self.stack, 1)
        body.addWidget(self.filter_edit)
        layout.addWidget(self.tab_row)
        layout.addWidget(self.body, 1)
        self.outline = PanelOutline(self)             # one line around the current tab and the box below; over everything, clicks pass through
        self.outline.raise_()
        self.tabs.layout_changed.connect(self.outline.update)

        self.address.returnPressed.connect(self._address_entered)
        self.filter_edit.textChanged.connect(self._filter_changed)
        self.filter_edit.escaped.connect(self.clear_filter)
        self.filter_edit.leave.connect(lambda: self.view.setFocus())
        self.table.history_step.connect(lambda step: self.history_back() if step < 0 else self.history_forward())
        self.address_bar.navigate.connect(self._crumb_clicked)
        self.address_bar.navigate_new_tab.connect(lambda target: self.new_tab(target, activate=False))
        self.address_bar.escaped.connect(lambda: self.view.setFocus())
        self.enter_hook = None         # set by the window: Enter runs a command being written, if there is one
        self.file_hook = None          # set by the window: Enter on a file (Ctrl+Enter: the other way) goes through the open setting
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
        self.table.escape.connect(self._escape)
        self.table.activate_in_tab.connect(lambda: self.open_current(new_tab=True))
        self.table.middle_clicked.connect(self._middle_click_row)
        self.tabs.currentChanged.connect(self._tab_switched)
        self.tabs.currentChanged.connect(lambda _i: self.outline.update())
        self.tabs.middle_clicked.connect(self.close_tab)
        self.tabs.new_requested.connect(lambda: self.new_tab())
        self.new_tab_button.clicked.connect(lambda: self.new_tab())
        self._add_tab_entry("")                  # the first tab; set_folder gives it its folder
        self._active = False
        self.restyle()

    # the two views ------------------------------------------------------------------
    @property
    def view(self):
        """The view that is showing: the details table or the thumbnails."""
        return self.stack.currentWidget()

    def _setup_view(self, view) -> None:
        """Give a view the same wiring as the table has."""
        view.selection = self.selection
        view.drag_paths = self._paths_to_drag
        view.drag_source = str(id(self))
        view.drop_check = self._drop_target
        view.content_check = self._content_target
        view.stage_for = self._stage_for_paths
        view.content_dropped.connect(self._content_dropped)
        view.setAcceptDrops(True)
        view.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        view.dropped.connect(self._table_dropped)
        view.context_requested.connect(self.context_requested.emit)
        view.drag_ended.connect(self.refresh)
        view.history_step.connect(lambda step: self.history_back() if step < 0 else self.history_forward())
        view.activate.connect(self._enter)
        view.go_up.connect(self._backspace)
        view.doubleClicked.connect(lambda _i: self.open_current())
        view.focused.connect(lambda: self.activated.emit(self))
        view.escape.connect(self._escape)
        view.activate_in_tab.connect(lambda: self.open_current(new_tab=True))
        view.middle_clicked.connect(self._middle_click_row)
        view.zoom.connect(lambda step: self.zoom_icons(step))

    def set_view_mode(self, mode: str, px: int = 0) -> None:
        """``details`` or ``icons`` (the thumbnails) with a picture size. The Home page always shows details."""
        from .thumbnails import nearest_step
        self.view_mode = mode if mode in ("details", "icons") else "details"
        if px:
            self.icon_px = nearest_step(px)
        self._apply_mode()
        self.mode_changed.emit(self)

    def current_sort(self) -> tuple:
        """``(column name, descending)`` of the list as it is sorted now."""
        header = self.table.horizontalHeader()
        column = header.sortIndicatorSection()
        key = COLUMN_KEYS[column] if 0 <= column < len(COLUMN_KEYS) else "name"
        return key, header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    def set_sort(self, key: str, descending: bool) -> None:
        """Sort by a column on the program's own account (a layout), not as a choice of the owner."""
        was, self._applying_layout = self._applying_layout, True
        try:
            self.table.sortByColumn(column_index(key) if key in COLUMN_KEYS else 0,
                                    Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        finally:
            self._applying_layout = was

    def _sort_indicator_changed(self, *_args) -> None:
        if not self._applying_layout and not self.is_home:
            self.sort_changed.emit(self)

    def zoom_icons(self, step: int) -> None:
        from .thumbnails import step_by
        self.set_view_mode("icons", step_by(self.icon_px, step))

    def _apply_mode(self) -> None:
        show_icons = self.view_mode == "icons" and not self.is_home and self.model.path != ""
        had_focus = self.table.hasFocus() or self.icons.hasFocus()
        self.model.icon_px = self.icon_px if show_icons else 0
        self.icons.set_size(self.icon_px)
        self.stack.setCurrentWidget(self.icons if show_icons else self.table)
        self.model.refresh_all()
        self._show_note(self._note_text)
        if had_focus:
            self.view.setFocus()

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
        # no top edge: the tabs sit directly on the box, so tabs, bar and frame read as one structure
        # a flat fill behind the margins, not a border: a border leaves a hairline seam at fractional display scaling
        self.setStyleSheet(f"#panelbody{{background:{accent if active else 'transparent'};border:none;}}")
        colors = theme.tab_colors(t)
        # the address field belongs to the tabs above it: solid gold with the current tab in the active panel,
        # a dark gold with the current tab in the other one
        fill, text = (accent, on_accent) if active else (colors["dim_fill"], colors["dim_text"])
        self.bar.setStyleSheet(
            f"#pathbarbox{{background:{fill};}}"
            f"#pathbarbox QLineEdit{{background:transparent;color:{text};border:none;font-weight:{look.weight()};}}"
            f"#pathbarbox QLabel{{color:{text};}}"
            f"#pathbarbox QToolButton{{color:{text};border:1px solid {text};border-radius:6px;"
            f"padding:1px 6px;background:transparent;font-weight:{look.weight()};}}"
            f"#pathbarbox QToolButton::menu-indicator{{image:none;}}"
            f"#pathbarbox QToolButton#homebtn{{border:none;padding:1px 3px;}}"
            f"#pathbarbox QToolButton#crumb{{border:none;border-radius:4px;padding:1px 4px;}}"
            f"#pathbarbox QToolButton#crumb:hover{{background:rgba(0,0,0,60);}}"
            f"#pathbarbox QToolButton#crumb::menu-indicator{{image:none;}}"
            f"#pathbarbox QLabel#crumbsep{{color:{text};}}"
            f"#pathbarbox QToolButton#sizesbtn, #pathbarbox QToolButton#flatbtn, #pathbarbox QToolButton#refreshbtn"
            f"{{border:none;border-radius:4px;padding:1px 6px;font-weight:{look.weight()};}}"
            f"#pathbarbox QToolButton#sizesbtn:hover, #pathbarbox QToolButton#flatbtn:hover, #pathbarbox QToolButton#refreshbtn:hover{{background:rgba(0,0,0,60);}}")
        palette = QPalette(QApplication.palette())
        if not active:
            for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
                palette.setColor(group, QPalette.ColorRole.Highlight, QColor(t["line"]))
                palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(t["fg"]))
        for view in (self.table, self.icons):
            view.setPalette(palette)
            view.viewport().setPalette(palette)     # the viewport keeps an old copy otherwise (white rows in dark)
        self.drive_bar.set_chip_color(text)
        self.home_button.setIcon(icon_set.icon("home", text))
        self._style_close_buttons()
        self.tabs.panel_active = active
        # The active panel's gold frame is the fill behind the body's side margins, so the box below the tabs reaches the panel's edge and
        # the first tab lines up with it there. An inactive panel has no frame: its box starts FRAME in, so the first tab starts there too.
        self.tabs.first_inset = 0 if active else FRAME
        self.tabs.update()
        self.outline.update()

    def restyle(self) -> None:
        """The colour scheme changed: redraw the active mark, the marked rows and the note."""
        self.set_active(self._active)
        self.drive_bar.restyle()
        t = theme.current()
        # The tabs paint themselves (PanelTabBar.paintEvent). This only styles the row they sit in and the + and
        # close buttons, which are small and quiet until the pointer is on them.
        self.tab_row.setStyleSheet(
            f"#tabrow{{background:{t['card']};}}"
            f"QToolButton{{color:{t['fg']};font-weight:{look.weight()};padding:0 8px;border:none;background:transparent;}}"
            f"QTabBar QToolButton{{padding:1px;border-radius:3px;}}"
            f"QTabBar QToolButton:hover{{background:{t['line']};}}")
        self.tabs.update()
        self._style_close_buttons()
        self.model.refresh_marks()
        if self.model.note_row >= 0:
            self._show_note(self._note_text)

    def current_entry(self) -> Optional[Entry]:
        row = self.table.currentIndex().row()
        if row < 0 or self.model.is_up_row(row):
            return None
        return self.model.entry_at(row)

    def current_name(self) -> str:
        e = self.current_entry()
        return self.fs.basename(e.path) if e else ""

    # navigation ----------------------------------------------------------------------
    def set_folder(self, path: str, select: str = "") -> bool:
        """Show ``path``. The listing is made on a worker thread; a folder that answers within a moment (every
        local one) is shown at once. A slow one (a dead network share, a server) leaves the window alive: the
        old folder stays, a message says what is being opened, Esc cancels, and the new folder appears when the
        answer arrives. Returns False (with a message) when it cannot be listed, True when shown or still
        pending."""
        self._cancel_navigation()
        listing = _Listing(self.fs, path, self.notes_enabled and not is_home(path))
        if listing.done.wait(NAV_BUDGET):
            return self._finish_listing(listing, path, select)
        self._pending = (listing, path, select)
        self.table.viewport().setCursor(Qt.CursorShape.BusyCursor)
        self.message.emit(f"Opening {path}... (Esc cancels)")
        self._poll.start()
        return True

    @property
    def loading(self) -> bool:
        return self._pending is not None

    @property
    def pending_path(self) -> str:
        return self._pending[1] if self._pending else ""

    # folder history: back, forward and a list, for each tab --------------------------------------------------------
    def _record_history(self, path: str) -> None:
        st = self._tabs.get(self._current_tab_id)
        if st is None:
            return
        if self._skip_history_for is not None and self._skip_history_for == path:
            self._skip_history_for = None            # we got here by going back or forward, or by switching tab
            if not st.history:
                st.history, st.hpos = [path], 0
            return
        if 0 <= st.hpos < len(st.history) and st.history[st.hpos] == path:
            return                                   # a refresh of the same folder
        del st.history[st.hpos + 1:]                 # a new place cuts off what was "forward"
        st.history.append(path)
        if len(st.history) > HISTORY_MAX:
            del st.history[0]
        st.hpos = len(st.history) - 1

    def history_go(self, index: int) -> bool:
        st = self._tabs.get(self._current_tab_id)
        if st is None or not 0 <= index < len(st.history) or index == st.hpos:
            return False
        before, st.hpos = st.hpos, index
        target = st.history[index]
        self._skip_history_for = target
        if self.set_folder(target):
            return True
        st.hpos = before                             # that folder cannot be opened: stay where we were
        self._skip_history_for = None
        return False

    def history_back(self) -> bool:
        st = self._tabs.get(self._current_tab_id)
        return bool(st) and self.history_go(st.hpos - 1)

    def history_forward(self) -> bool:
        st = self._tabs.get(self._current_tab_id)
        return bool(st) and self.history_go(st.hpos + 1)

    def history_entries(self) -> list:
        """``[(index, path), ...]`` newest first, for a list the user picks from."""
        st = self._tabs.get(self._current_tab_id)
        if st is None:
            return []
        return [(i, p) for i, p in reversed(list(enumerate(st.history)))]

    @property
    def history_position(self) -> int:
        st = self._tabs.get(self._current_tab_id)
        return st.hpos if st else -1

    # the quick filter ------------------------------------------------------------------------------------------
    @property
    def filter_active(self) -> bool:
        return bool(self.model.filter_text.strip())

    def start_filter(self) -> None:
        if self.is_home:
            self.message.emit("The Home page has no list to filter")
            return
        self.filter_edit.show()
        self.filter_edit.setFocus()
        self.filter_edit.selectAll()

    def _filter_changed(self, text: str) -> None:
        self.model.set_filter(text)
        shown, total = self.model.counts()
        if text.strip():
            self.message.emit(f"Filter: {shown} of {total} shown")
        if self.model.entry_count():
            first = 1 if self.model.is_up_row(0) and self.model.entry_count() > 1 else 0
            self.table.setCurrentIndex(self.model.index(first, 0))

    def _hide_filter(self) -> None:
        blocked = self.filter_edit.blockSignals(True)
        self.filter_edit.clear()
        self.filter_edit.blockSignals(blocked)
        self.filter_edit.hide()

    def clear_filter(self) -> None:
        self._hide_filter()
        self.model.set_filter("")
        self.view.setFocus()
        if self.model.entry_count():
            first = 1 if self.model.is_up_row(0) and self.model.entry_count() > 1 else 0
            self.table.setCurrentIndex(self.model.index(first, 0))

    def _escape(self) -> None:
        """Esc stops a slow folder; when nothing is pending it clears the marks."""
        if self.cancel_navigation():
            return
        if self.filter_active or self.filter_edit.isVisible():
            self.clear_filter()
            return
        self.selection.clear()

    def cancel_navigation(self) -> bool:
        """Stop waiting for a slow folder. Returns True when there was one."""
        was = self._pending is not None
        self._cancel_navigation()
        if was:
            self.message.emit("Cancelled")
        return was

    def _cancel_navigation(self) -> None:
        if self._pending is not None:
            self._pending[0].cancelled = True            # the thread cannot be stopped; its answer is ignored
            self._pending = None
        self._poll.stop()
        self.table.viewport().unsetCursor()

    def _poll_pending(self) -> None:
        if self._pending is None:
            self._poll.stop()
            return
        listing, path, select = self._pending
        if listing.done.is_set():
            self._pending = None
            self._poll.stop()
            self.table.viewport().unsetCursor()
            self._finish_listing(listing, path, select)

    def _apply_columns(self) -> None:
        """The Home page has its own three columns (name, type, details); folders have the chosen columns."""
        home = self.is_home
        if home == getattr(self, "_columns_for_home", None):
            return
        self._columns_for_home = home
        if home:
            for i, w in enumerate((300, 130, 260)):
                self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSortIndicatorShown(not home)
        self.apply_column_layout()

    # which columns are shown, and in which order (the window keeps the choice and hands it to both panels) -----
    def set_column_layout(self, hidden: set, order: list) -> None:
        self._col_hidden, self._col_order = set(hidden), list(order)
        self.apply_column_layout()

    def apply_column_layout(self) -> None:
        header = self.table.horizontalHeader()
        hidden = getattr(self, "_col_hidden", set(DEFAULT_HIDDEN))
        order = getattr(self, "_col_order", list(DEFAULT_ORDER))
        self._laying_out = True
        try:
            logical_of = {k: column_index(k) for k in COLUMN_KEYS}
            apply_column_order(header, list(COLUMN_KEYS[:3]) if self.is_home else order, logical_of)
            for key, idx in logical_of.items():
                off = (idx > 2) if self.is_home else not is_column_visible(key, hidden, PROTECTED_COLUMNS)
                header.setSectionHidden(idx, off)
        finally:
            self._laying_out = False
        self.refresh_tags()                                   # a tags column may just have been switched on
        self.refresh_meta()                                   # and so may a metadata column

    def column_keys_in_order(self) -> list:
        return visual_column_keys(self.table.horizontalHeader(), list(COLUMN_KEYS))

    def _column_moved(self, *_args) -> None:
        if not getattr(self, "_laying_out", False) and not self.is_home:
            self.columns_reordered.emit()

    # dragging and dropping --------------------------------------------------------------------------------------------
    def _paths_to_drag(self, row: int) -> list:
        """What a drag from ``row`` carries: all the marked items when that row is marked, otherwise just that row."""
        entry = self.model.entry_at(row)
        if entry is None or self.model.is_up_row(row) or entry.kind in ("header", "action") or self.is_home:
            return []
        marked = self.marked_here()
        return marked if entry.path in marked else [entry.path]

    def _drop_target(self, paths: list, source, row: int):
        """Where a drop on ``row`` would land: the folder (a path), ``"here"`` for this panel's own folder, or None when a drop
        makes no sense there (the Home page, a read-only place, onto itself, into its own subfolder, nothing to move)."""
        from .dragdrop import all_in_folder, can_drop
        if self.is_home or not paths:
            return None
        entry = self.model.entry_at(row) if row >= 0 else None
        if entry is not None and entry.is_dir and entry.kind not in ("header", "action"):
            dest, on_row = entry.path, True
        else:
            dest, on_row = self.path, False
        if not on_row and source == str(id(self)):
            return None                                   # dropped on its own list: nothing to move
        if not (self.fs.is_writable(dest) or dest.startswith("zip://")):
            return None
        if not can_drop(paths, dest, self.fs.sep):
            return None
        if source == str(id(self)) and all_in_folder(paths, dest, self.fs.dirname):
            return None
        return dest if on_row else "here"

    def _stage_for_paths(self, paths: list):
        """For a drag of items that are not on a drive (inside an archive, on a server): a function that copies them out when another
        program asks for files. None when they are all on a drive (nothing to do) or are more than the limit (said in the status line)."""
        if all(not has_scheme(p) for p in paths):
            return None
        from ..core import stage
        wanted = set(paths)
        known = [e for e in (self.model.entry_at(r) for r in range(self.model.entry_count())) if e is not None and e.path in wanted]
        if stage.known_size(known) > stage.LIMIT:
            self.message.emit(f"Too big to hand to another program (over {stage.LIMIT // (1024 * 1024)} MB): copy it to the other panel instead")
            return None
        fs = self.fs
        return lambda: stage.stage(fs, paths)

    def _content_target(self, row: int):
        """Where a picture or text dropped on ``row`` would be made into a file: ``"folder"`` for a folder row, ``"here"`` for this panel's
        folder, None where nothing can be made (the Home page, a read-only place, an archive)."""
        if self.is_home:
            return None
        entry = self.model.entry_at(row) if row >= 0 else None
        if entry is not None and entry.is_dir and entry.kind not in ("header", "action") and not self.model.is_up_row(row):
            return "folder" if self.fs.is_writable(entry.path) and not entry.path.startswith("zip://") else None
        return "here" if self.fs.is_writable(self.path) and not self.path.startswith("zip://") else None

    def _content_dropped(self, kind: str, payload, row: int) -> None:
        target = self._content_target(row)
        if target is None:
            return
        entry = self.model.entry_at(row) if target == "folder" else None
        self.content_dropped.emit(kind, payload, entry.path if entry is not None else self.path)

    def _table_dropped(self, paths: list, row: int, modifiers: int, source) -> None:
        target = self._drop_target(paths, source, row)
        if target is None:
            return
        self.files_dropped.emit(paths, self.path if target == "here" else target, modifiers, source)

    # the Tags and Rating columns --------------------------------------------------------------------------------------
    def tag_columns_visible(self) -> bool:
        header = self.table.horizontalHeader()
        return not self.is_home and any(not header.isSectionHidden(column_index(k)) for k in ("tags", "rating", "label"))

    def refresh_tags(self) -> None:
        """Read the tags of the listed items on a thread and show them. Only when a tags column is on, and only for items on
        a drive of this computer; a newer call makes an older one stop."""
        if not self.tag_columns_visible() or self._dispatch is None:
            return
        from ..core.filetags import read_tags
        entries = [e for e in (self.model.entry_at(r) for r in range(self.model.entry_count()))
                   if e is not None and e.name != ".." and not e.kind and not has_scheme(e.path)][:5000]
        self._tag_gen = getattr(self, "_tag_gen", 0) + 1
        gen, shown = self._tag_gen, self.model.path

        def work() -> None:
            info = {}
            for e in entries:
                if gen != self._tag_gen:
                    return
                t = read_tags(e.path)
                if not t.is_empty():
                    info[e.path] = (", ".join(t.tags), t.rating, t.label)

            def show() -> None:
                if gen == self._tag_gen and self.model.path == shown:
                    self.model.set_tag_info(info)
            self._dispatch(show)

        threading.Thread(target=work, daemon=True, name="dossier-tags").start()

    # the metadata columns (Artist, Album, Series, Resolution...) --------------------------------------------------------------
    meta_reader = staticmethod(metacolumns.read_values)       # a seam for tests: the function that reads one file

    def meta_columns_visible(self) -> list:
        header = self.table.horizontalHeader()
        return [] if self.is_home else [k for k in META_KEYS if not header.isSectionHidden(column_index(k))]

    def refresh_meta(self) -> None:
        """Read the files of the listing that the visible metadata columns are about, on a thread, a few at a time: the cells fill in
        while the rest is read. Nothing is opened when no metadata column is on. A newer call makes an older one stop."""
        self._meta_gen = getattr(self, "_meta_gen", 0) + 1
        visible = self.meta_columns_visible()
        if not visible or self._dispatch is None:
            return
        kinds = metacolumns.kinds_needed(visible)
        entries = [e for e in (self.model.entry_at(r) for r in range(self.model.entry_count()))
                   if e is not None and e.name != ".." and not e.is_dir and not e.kind and not has_scheme(e.path)][:5000]
        gen, shown, reader = self._meta_gen, self.model.path, self.meta_reader

        def work() -> None:
            def batch(info: dict) -> None:
                def show() -> None:
                    if gen == self._meta_gen and self.model.path == shown:
                        self.model.set_meta_info(info)
                self._dispatch(show)
            metacolumns.read_many(entries, kinds, metacolumns.SHARED_CACHE, batch, reader=reader,
                                  cancelled=lambda: gen != self._meta_gen)

        threading.Thread(target=work, daemon=True, name="dossier-meta").start()

    def _fill_home_usage(self, entries: list) -> None:
        """Free space of the drives, asked on background threads: a dead network drive only delays its own row."""
        if self._dispatch is None:
            return
        paths = [e.path for e in entries if e.kind in ("fixed", "removable", "optical", "other", "network")]
        provider = getattr(getattr(self.fs, "home", None), "provider", None)

        def ready(p: str, usage, identity: str = "") -> None:
            def show() -> None:
                if not self.is_home:
                    return
                if not usage:                                    # the drive did not answer: not ready, or gone
                    if provider is not None:
                        provider.board.record(p, FAILED)
                    self.model.update_detail(p, "Not available", FAILED, describe(FAILED))
                    return
                status, note = provider.memory.judge(p, identity) if provider is not None else (OK, "")
                if provider is not None:
                    provider.board.record(p, status, note)
                self.model.update_detail(p, f"{human_size(usage[1])} free of {human_size(usage[0])}", status,
                                         describe(status, note))
            self._dispatch(show)

        probe_async(paths, ready)

    def _finish_listing(self, listing: "_Listing", path: str, select: str) -> bool:
        provider = getattr(getattr(self.fs, "home", None), "provider", None)
        if listing.error is not None:
            e = listing.error
            if isinstance(e, NotConnected):                  # the window offers to connect, and comes back here
                self.connect_needed.emit(path)
                return False
            if provider is not None and not is_home(path):
                provider.board.record(path, FAILED, str(getattr(e, "strerror", None) or e))
            self.message.emit(f"Cannot open {path}: {getattr(e, 'strerror', None) or e}")
            return False
        if provider is not None and not is_home(path):
            provider.board.record(path, OK)
        moved_on = path != self.model.path
        self.model.set_entries(path, listing.entries)
        if moved_on and (self.filter_edit.isVisible() or self.filter_edit.text()):
            self._hide_filter()                    # a filter belongs to one folder
        self._record_history(path)
        self._apply_columns()
        self._apply_mode()
        self.address.setText(path)
        self.address_bar.set_path(path)
        self.drive_bar.set_current_path(path)
        self._update_free(path)
        self._note_text = compose_markdown(listing.notes) if self.notes_enabled and not is_home(path) else ""
        self.note_paths = [n.path for n in listing.notes] if self.notes_enabled and not is_home(path) else []
        self._show_note(self._note_text)
        row = self.model.row_of(select) if select else -1
        if row < 0 and self.is_home and select:                # coming up from a drive or a folder: land on it
            row = next((r for r in range(self.model.entry_count())
                        if self.model.entry_at(r).path.rstrip("\\/") == select.rstrip("\\/")), -1)
        if row < 0 and self.model.entry_count():
            row = (self.model.first_selectable_row() if self.is_home
                   else 1 if self.model.is_up_row(0) and self.model.entry_count() > 1 else 0)
        if self.is_home:
            self._fill_home_usage(listing.entries)
        else:
            self.refresh_tags()
            self.refresh_meta()
        if row >= 0:
            self.table.setCurrentIndex(self.model.index(row, 0))
        self.view.scrollToTop() if not select else self.view.scrollTo(self.table.currentIndex())
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
        """A cross in the text colour of its tab (dark on the gold tab, light on the dark gold ones)."""
        c = theme.tab_colors()
        for tid, btn in list(self._close_buttons.items()):
            try:
                current = tid == self._current_tab_id
                colour = (c["active_text"] if self._active else c["dim_text"]) if current else c["blue_text"]
                btn.setIcon(icon_set.icon("x", colour))
            except RuntimeError:                      # the button went away with its tab
                self._close_buttons.pop(tid, None)

    def _tab_label(self, path: str) -> str:
        if is_home(path):
            return "Home"
        return self.fs.basename(path.rstrip("\\/")) or path or "..."

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

    def append_tab(self, path: str) -> int:
        """A tab at the end of the row, in the background (several appended one after the other keep their order)."""
        self._save_tab_state()
        return self._add_tab_entry(path)

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
        was, self._applying_layout = self._applying_layout, True       # a tab brings its own sort: nobody's choice here
        try:
            self.table.sortByColumn(st.sort_col, order)
        finally:
            self._applying_layout = was
        path = st.path
        self._skip_history_for = path
        while path and not self.set_folder(path, select=st.current):     # a folder that is gone: nearest parent
            parent = self.fs.parent(path)
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
        """The folders of the tabs, for the next session. A search result is not kept: its tab comes back as the folder
        the search started in."""
        self._save_tab_state()
        paths = [self._tabs[self.tabs.tabData(i)].path for i in range(self.tabs.count())]
        return [(self.fs.parent(p) or p) if p.startswith("found:") else p for p in paths]

    def real_folder(self) -> str:
        """The folder on a disk this panel stands in: its own path, or for an archive, a list of all files or a search
        result the folder it was made from. A terminal or a command runs there."""
        path = self.path
        for _ in range(16):
            if not path.startswith(("zip:", "flat:", "found:")):
                break
            above = self.fs.parent(path)
            if not above or above == path:
                break
            path = above
        return path

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
        self._skip_history_for = st.path
        while not self.set_folder(st.path):
            parent = self.fs.parent(st.path)
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

    def go_home(self) -> None:
        if not self.is_home:
            self.set_folder(HOME_URL, select=self.path)

    @property
    def is_home(self) -> bool:
        return self.model.is_home

    def go_up(self) -> None:
        if self.model.is_up_row(0):
            came_from = self.fs.basename(self.path.rstrip("\\/"))
            self.set_folder(self.model.entry_at(0).path, select=came_from)
        elif not self.is_home and self.path:
            self.set_folder(HOME_URL, select=self.path)      # above a drive root is the Home page

    def open_current(self, new_tab: bool = False) -> None:
        row = self.table.currentIndex().row()
        entry = self.model.entry_at(row)
        if entry is None:
            return
        if self.model.is_up_row(row):
            self.go_up()
        elif entry.kind == "header":
            return
        elif entry.kind in ("action", "tailnet"):
            self.home_action.emit(entry.path)
        elif entry.kind == "server":
            self.server_requested.emit(entry.path, new_tab)
        elif entry.is_dir and new_tab:
            self.new_tab(entry.path)
        elif entry.is_dir:
            self.set_folder(entry.path)
        elif not has_scheme(entry.path) and archives.opens_by_name(entry.path):
            self.set_folder(zipfs.archive_root(entry.path))          # an archive opens like a folder
        elif not has_scheme(entry.path) and archives.missing_reader_by_name(entry.path):
            self.message.emit(archives.missing_reader_by_name(entry.path))   # say what would open it, then let the system try
            QDesktopServices.openUrl(QUrl.fromLocalFile(entry.path))
        elif self.file_hook and self.file_hook(entry.path, new_tab):
            return                                            # the window opened it (in the viewer, or in the Windows program)
        elif has_scheme(entry.path):
            self.open_archived.emit(entry.path)               # the window unpacks it on a thread, then opens it
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(entry.path))

    def open_as_archive(self) -> None:
        """Ctrl+PageDown: open the file under the cursor as a folder whatever it is called, when its content is an
        archive (a Word document, an epub, a jar...)."""
        entry = self.current_entry()
        if entry is None or entry.is_dir or has_scheme(entry.path):
            self.message.emit("Put the cursor on a file to open it as an archive")
        elif zipfs.is_archive(entry.path):
            self.set_folder(zipfs.archive_root(entry.path))
        else:
            self.message.emit(archives.missing_reader(entry.path) or f"{entry.name} is not an archive Dossier can read")

    def _address_entered(self) -> None:
        text = self.address.text().strip()
        if text.lower() in ("home", "home:", "home:/", "home://"):
            text = HOME_URL
        typed = text if has_scheme(text) else os.path.normpath(os.path.expanduser(text))
        if text and not self.set_folder(typed):
            self.address.setText(self.path)
        self.address_bar.finish_edit()
        self.view.setFocus()

    def _crumb_clicked(self, target: str) -> None:
        """A part of the address was clicked: go there, and stand on the folder we came out of."""
        here = [p for _label, p in self.address_bar.parts()]
        came_from = ""
        if target in here and here.index(target) + 1 < len(here):
            came_from = self.fs.basename(here[here.index(target) + 1].rstrip(pathparts.SEPARATORS))
        self.set_folder(target, select=came_from)
        self.view.setFocus()

    def _update_free(self, path: str) -> None:
        """Free space comes from a background thread: a dead network share must not freeze the window."""
        self.free.setText("")
        if self._dispatch is None or is_home(path):
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
        if drive.kind != "home" and path_key(target) == path_key(self.path):
            target = drive.path                          # clicking the drive you are in toggles to its root
        if not self.set_folder(target) and target != drive.path:
            self.set_folder(drive.path)

    def open_drive_menu(self) -> None:
        self.drive_bar.open_menu()

    # the note -------------------------------------------------------------------------
    def set_notes_enabled(self, on: bool) -> None:
        if on == self.notes_enabled:
            return
        self.notes_enabled = on
        if on:
            self.refresh()                       # the notes are read with the listing, on its thread
        else:
            self._note_text = ""
            self._show_note("")

    def _show_note(self, text: str) -> None:
        if self._note_row_set >= 0:                # the row that held the last folder's note keeps its span and height by number:
            self.table.clearSpans()                # give them back, or the next listing shows a tall row there (Home had two)
            self.table.setRowHeight(self._note_row_set, self.table.verticalHeader().defaultSectionSize())
            self._note_row_set = -1
        self.model.set_has_note(bool(text) and not self.model.icon_px)      # the thumbnail view has no note row
        if not text or self.model.icon_px:
            self.note.hide()
            return
        self.note.setMarkdown(text)
        self._place_note()

    def _place_note(self) -> None:
        row = self.model.note_row
        if row < 0:
            return
        self.table.setSpan(row, 0, 1, self.model.columnCount())
        self._note_row_set = row
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
        self.outline.setGeometry(self.rect())
        self.outline.raise_()
        if self.model.note_row >= 0:
            self._place_note()

    # acting on items (S4) ----------------------------------------------------------------
    def marked_here(self) -> list:
        """The marked items that are listed in this panel. The marks are shared, but a command works on what the
        user sees marked in the panel it is started from, never on marks left in the other panel."""
        if self.is_home:
            return []
        marked = self.selection.paths()
        if not marked:
            return []
        listed = {self.model.entry_at(r).path for r in range(self.model.entry_count())
                  if not self.model.is_up_row(r) and self.model.entry_at(r) is not None}
        return [p for p in marked if p in listed]

    def marked_in_view_order(self) -> list:
        """The marked entries of this panel in the order the list shows them (what a counter must count in)."""
        marked = set(self.marked_here())
        if not marked:
            return []
        out = []
        for r in range(self.model.entry_count()):
            e = self.model.entry_at(r)
            if e is not None and not self.model.is_up_row(r) and e.path in marked:
                out.append(e)
        return out

    target_override = None      # set while a context menu command runs: exactly the items that were right-clicked

    def targets(self) -> list:
        """The marked items, else the item under the cursor (or, during a right-click command, the items it was on)."""
        if self.target_override is not None:
            return list(self.target_override)
        if self.is_home:
            return []                                        # the Home page lists shortcuts, not files
        marked = self.marked_here()
        if marked:
            return marked
        e = self.current_entry()
        return [e.path] if e else []
