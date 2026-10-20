"""The table model behind one panel: the entries of a folder plus, when the folder has a note,
one last row that the panel fills with the rendered note (it scrolls with the list, like a README
under a repository's file list)."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import replace as dc_replace
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtCore import QPointF, QSize
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication

from ..core.columns import KEYS as column_keys, LABELS as column_labels, RIGHT_ALIGNED, attributes_text, location_text, type_text
from ..core.columns import LABEL_COLORS, META_KEYS, label_text, rating_text, when
from ..core import covers
from ..core.drives import is_remote_quick
from ..core.filetypes import DRIVE_ICONS, icon_name
from ..core.home import HOME_URL, TYPE_NAMES, USER_FOLDER_NOTE
from ..core.selection import SelectionStore
from ..core.vfs import Entry, FileSystem, natural_key
from . import icon_set, look, theme

COLUMNS = tuple(column_labels[k] for k in column_keys)       # one per logical column, see core/columns.py
HOME_COLUMNS = ("Name", "Type", "Details")
ENTRY_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


from ..core.sizefmt import human_size  # noqa: E402,F401  (one formatter; callers import it from here)


def marked_color() -> QColor:
    """The gold of the current colour scheme (see theme.py), readable on its page and cursor row."""
    return QColor(theme.current()["marked"])


def name_fits(name: str, text: str) -> bool:
    """The quick filter's test: a pattern when it has * ? or [, otherwise a part of the name, in either case ignoring case."""
    if any(ch in text for ch in "*?["):
        return fnmatch.fnmatch(name.lower(), text.lower())
    return text.lower() in name.lower()


LIGHT_COLORS = {"ok": "#2e9e5b", "unchecked": "#8a8f98", "failed": "#d64545", "changed": "#e0a020"}
_light_cache: dict = {}


def with_light(icon: QIcon, status: str) -> QIcon:
    """The icon with a small indicator light in its lower right corner. The shapes differ as well as the colours
    (filled dot, hollow dot, cross, diamond), so the state can be told without telling the colours apart."""
    key = (icon.cacheKey(), status)
    if key in _light_cache:
        return _light_cache[key]
    ratio = 2
    base = icon.pixmap(16 * ratio, 16 * ratio)
    pm = QPixmap(base)
    pm.setDevicePixelRatio(1)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = pm.width()
    r = size * 0.25
    cx, cy = size - r - 1, size - r - 1
    color = QColor(LIGHT_COLORS.get(status, "#8a8f98"))
    backdrop = QColor(0, 0, 0, 170)                        # a dark ring keeps the light visible on any row colour
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(backdrop)
    p.drawEllipse(QPointF(cx, cy), r + 1.5, r + 1.5)
    if status == "ok":
        p.setBrush(color)
        p.drawEllipse(QPointF(cx, cy), r, r)
    elif status == "unchecked":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, size * 0.09))
        p.drawEllipse(QPointF(cx, cy), r * 0.8, r * 0.8)
    elif status == "failed":
        p.setPen(QPen(color, size * 0.12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        d = r * 0.7
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    else:                                                  # changed: a diamond
        p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(cx, cy - r * 1.15), QPointF(cx + r * 1.15, cy), QPointF(cx, cy + r * 1.15),
                                 QPointF(cx - r * 1.15, cy)]))
    p.end()
    result = QIcon(pm)
    _light_cache[key] = result
    return result


class FolderModel(QAbstractTableModel):
    def __init__(self, fs: FileSystem, selection: SelectionStore, parent=None) -> None:
        super().__init__(parent)
        self.fs = fs
        self.selection = selection
        self.path = ""
        self._up: Optional[Entry] = None
        self._rows: list = []
        self._source_rows: list = []             # the whole listing; _rows is what the quick filter lets through
        self._filter = ""
        self._tree_sizes: dict = {}
        self.drop_row = -1                       # the row a drag is hovering over (a folder that would take the drop)
        self.icon_px = 0                         # 0: the details table; otherwise the thumbnail view, with pictures this big
        self.thumbs = None                       # the Thumbnails that make the pictures, set by the window
        self._network = False                    # the folder shown is on a network drive (no thumbnails unless allowed)
        self._rc_key = None
        self._rc: dict = {}
        self._framed_cache: dict = {}
        self._tag_info: dict = {}                # path -> (tags text, rating, label), filled in on a thread when a column is on
        self._meta_info: dict = {}               # path -> {metadata column key: text}, read from the files on a thread
        self._has_note = False
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder

    @property
    def is_home(self) -> bool:
        return self.path == HOME_URL

    def entry_kind(self, row: int) -> str:
        e = self.entry_at(row)
        return e.kind if e else ""

    def first_selectable_row(self) -> int:
        """The first row the cursor can stand on (the Home page starts with a header it cannot)."""
        for r in range(self.entry_count()):
            if self.entry_kind(r) != "header":
                return r
        return -1

    def _tag(self, path: str) -> tuple:
        return self._tag_info.get(path, ("", 0, ""))

    def refresh_all(self) -> None:
        """Every cell is drawn again (the font or bold was changed)."""
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
        self.layoutChanged.emit()

    def set_tag_info(self, info: dict) -> None:
        """The tags, ratings and labels of the items on screen (``{path: (tags text, rating, label)}``): shown in the Tags,
        Rating and Label columns, and sortable. They arrive after the listing, from a thread."""
        self._tag_info = {p: tuple(v) + ("",) * (3 - len(v)) for p, v in info.items()}
        if self._sort_col in (8, 9, 10):
            self.sort(self._sort_col, self._sort_order)
        if self.entry_count():
            self.dataChanged.emit(self.index(0, 8), self.index(self.entry_count() - 1, 10))

    def _meta(self, path: str, key: str) -> str:
        return self._meta_info.get(path, {}).get(key, "")

    def set_meta_info(self, info: dict) -> None:
        """Values for the metadata columns (``{path: {column key: text}}``), a few files at a time as they are read. Sorting by one of
        those columns is done again with what has arrived."""
        self._meta_info.update(info)
        first = column_keys.index(META_KEYS[0])
        if self._sort_col >= first:
            self.sort(self._sort_col, self._sort_order)
        if self.entry_count():
            self.dataChanged.emit(self.index(0, first), self.index(self.entry_count() - 1, len(column_keys) - 1))

    def update_detail(self, path: str, detail: str, status: Optional[str] = None, note: str = "") -> None:
        """Fill in the third column of one Home entry (free space arrives after the page is shown), and its light."""
        for i, e in enumerate(self._rows):
            if e.path == path and e.kind not in ("header", "action"):
                changes = {"detail": detail} if detail else {}
                if status is not None:
                    changes.update(status=status, note=note)
                self._rows[i] = dc_replace(e, **changes)
                row = i + (1 if self._up else 0)
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(HOME_COLUMNS) - 1))
                return

    # content -----------------------------------------------------------------------
    def set_folder(self, path: str) -> None:
        """List ``path`` now. Raises OSError (the old listing stays) when it cannot be read."""
        self.set_entries(path, self.fs.list(path))

    def set_tree_sizes(self, sizes: dict) -> None:
        """Show the size of whole folder trees (``{path: bytes}``) in the Size column, and sort by it like any size.
        They belong to this listing: the next listing starts again from DIR."""
        if self.is_home or not sizes:
            return
        self._tree_sizes.update(sizes)
        self._source_rows = [dc_replace(e, size=sizes[e.path]) if e.is_dir and e.path in sizes else e
                             for e in self._source_rows]
        self._rows = [dc_replace(e, size=sizes[e.path]) if e.is_dir and e.path in sizes else e for e in self._rows]
        self.sort(self._sort_col, self._sort_order)               # the cursor stays on its item, whatever the order

    def set_entries(self, path: str, entries: list) -> None:
        """Show an already made listing of ``path`` (the panel lists on a worker thread and hands it over)."""
        parent = self.fs.parent(path)
        up = Entry("..", parent, True) if parent else None
        previous = self.path
        self.beginResetModel()
        self._tree_sizes = {}
        if path != previous:
            self._meta_info = {}                 # the values of another folder are of no use here
        self._network = is_remote_quick(path) if path and not path.startswith("home:") else False
        self.path = path
        self._up = up
        if path != previous:
            self._filter = ""                    # a filter belongs to one folder; a refresh of it keeps the filter
        self._source_rows = entries
        self._rows = self._filtered(entries)
        self._resort()
        self.endResetModel()

    # the quick filter -------------------------------------------------------------------------------------
    @property
    def filter_text(self) -> str:
        return self._filter

    def counts(self) -> tuple:
        """(shown, all) items of the listing, not counting the up row."""
        return len(self._rows), len(self._source_rows)

    def set_filter(self, text: str) -> None:
        """Show only the items whose name fits ``text``: a part of the name, or a pattern with * and ?. Marks stay."""
        if self.is_home or text == self._filter:
            return
        self.beginResetModel()
        self._filter = text
        self._rows = self._filtered(self._source_rows)
        self._resort()
        self.endResetModel()

    def _filtered(self, entries: list) -> list:
        text = self._filter.strip()
        if not text or self.is_home:
            return entries
        return [e for e in entries if name_fits(e.name, text)]

    def set_has_note(self, has: bool) -> None:
        if has != self._has_note:
            self.beginResetModel()
            self._has_note = has
            self.endResetModel()

    @property
    def note_row(self) -> int:
        return self.entry_count() if self._has_note else -1

    def entry_count(self) -> int:
        return len(self._rows) + (1 if self._up else 0)

    def entry_at(self, row: int) -> Optional[Entry]:
        if row < 0 or row >= self.entry_count():
            return None
        if self._up:
            return self._up if row == 0 else self._rows[row - 1]
        return self._rows[row]

    def is_up_row(self, row: int) -> bool:
        return self._up is not None and row == 0

    def row_of(self, name: str) -> int:
        for r in range(self.entry_count()):
            e = self.entry_at(r)
            if e and self.fs.basename(e.path) == name and not self.is_up_row(r):
                return r
        return -1

    # sorting -----------------------------------------------------------------------
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_col, self._sort_order = column, order
        if self.is_home:
            return                                   # the Home page keeps its own order: sections, not a sorted list
        self.layoutAboutToBeChanged.emit()
        before = {(idx.row(), idx.column()): idx for idx in self.persistentIndexList()}
        old_paths = {r: (self.entry_at(r).path if self.entry_at(r) else None) for r, _c in before}
        self._resort()
        new_row = {self.entry_at(r).path: r for r in range(self.entry_count())}
        for (r, c), idx in before.items():
            path = old_paths.get(r)
            if path in new_row:                       # the cursor stays on the same item, not the same row
                self.changePersistentIndex(idx, self.index(new_row[path], c))
        self.layoutChanged.emit()

    def _resort(self) -> None:
        if self.is_home:
            return
        keys = {0: lambda e: natural_key(e.name), 1: lambda e: (e.size, natural_key(e.name)),
                2: lambda e: (e.mtime, natural_key(e.name)),
                3: lambda e: (type_text(e.name, e.is_dir).lower(), natural_key(e.name)),
                4: lambda e: (e.ctime, natural_key(e.name)), 5: lambda e: (e.atime, natural_key(e.name)),
                6: lambda e: (attributes_text(e.attrs), natural_key(e.name)),
                7: lambda e: (self.fs.dirname(e.path).lower(), natural_key(e.name)),
                8: lambda e: (self._tag(e.path)[0].lower(), natural_key(e.name)),
                9: lambda e: (self._tag(e.path)[1], natural_key(e.name)),
                10: lambda e: (self._tag(e.path)[2], natural_key(e.name))}
        if self._sort_col >= len(keys):                  # a metadata column: by its text, numbers in their natural order
            meta_key = column_keys[self._sort_col]
            keys[self._sort_col] = lambda e: (natural_key(self._meta(e.path, meta_key)), natural_key(e.name))
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        folders = sorted((e for e in self._rows if e.is_dir), key=keys[self._sort_col], reverse=reverse)
        files = sorted((e for e in self._rows if not e.is_dir), key=keys[self._sort_col], reverse=reverse)
        self._rows = folders + files   # folders stay first whatever the order

    # Qt model interface ----------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self.entry_count() + (1 if self._has_note else 0)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if self.is_home:
                return HOME_COLUMNS[section] if section < len(HOME_COLUMNS) else ""
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        if self._has_note and index.row() == self.note_row:
            return Qt.ItemFlag.NoItemFlags
        if self.is_home and self.entry_kind(index.row()) == "header":
            return Qt.ItemFlag.NoItemFlags           # a section title: the cursor skips it
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def is_marked(self, entry: Entry) -> bool:
        return not self.is_home and entry.name != ".." and entry.path in self.selection

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or (self._has_note and index.row() == self.note_row):
            return None
        entry = self.entry_at(index.row())
        if entry is None:
            return None
        col = index.column()
        if self.is_home:
            return self._home_data(entry, col, role)
        if role == Qt.ItemDataRole.BackgroundRole and index.row() == self.drop_row:
            highlight = QColor(theme.current()["accent"])
            highlight.setAlpha(110)
            return QBrush(highlight)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return entry.name
            if self.is_up_row(index.row()):
                return "UP" if col == 1 else ""
            if col == 1:
                if entry.is_dir:
                    return human_size(entry.size) if entry.path in self._tree_sizes else "DIR"
                return human_size(entry.size)
            if col == 2:
                return datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M") if entry.mtime else ""
            if col == 3:
                return type_text(entry.name, entry.is_dir)
            if col == 4:
                return when(entry.ctime)
            if col == 5:
                return when(entry.atime)
            if col == 6:
                return attributes_text(entry.attrs)
            if col == 8:
                return self._tag(entry.path)[0]
            if col == 9:
                return rating_text(self._tag(entry.path)[1])
            if col == 10:
                return label_text(self._tag(entry.path)[2])
            if col == 7:
                return location_text(entry.path, self.fs.dirname)
            return self._meta(entry.path, column_keys[col])
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            if self.icon_px:
                if self.is_up_row(index.row()):
                    return self._framed(self._icon(entry, True))
                return self._thumb_icon(entry)
            return self._icon(entry, self.is_up_row(index.row()))
        if role == Qt.ItemDataRole.SizeHintRole and self.icon_px and col == 0:
            return QSize(self.icon_px + 24, self.icon_px + QFontMetrics(QApplication.font()).height() * 2 + 16)       # every tile alike
        if role == Qt.ItemDataRole.TextAlignmentRole and column_keys[col] in RIGHT_ALIGNED:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col == 10 and self._tag(entry.path)[2] in LABEL_COLORS:
            return QBrush(QColor(LABEL_COLORS[self._tag(entry.path)[2]]))
        if role == Qt.ItemDataRole.ForegroundRole and self.is_marked(entry):
            return QBrush(marked_color())
        if role == Qt.ItemDataRole.FontRole and look.bold_lists and (self.is_marked(entry) or entry.is_dir):
            font = QFont()
            font.setBold(True)
            return font
        if role == ENTRY_ROLE:
            return entry
        return None

    def _home_data(self, entry: Entry, col: int, role):
        t = theme.current()
        if col > 2:
            return None                                  # the Home page has three columns; the others are hidden there
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.name if col == 0 else (TYPE_NAMES.get(entry.kind, "") if col == 1 else entry.detail)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._home_icon(entry)
        if role == Qt.ItemDataRole.ToolTipRole and entry.note:
            return entry.note
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(look.bold_lists and (entry.kind in ("header", "action") or col == 0))      # section titles, actions, names
            return font
        if role == Qt.ItemDataRole.ForegroundRole:
            if entry.kind == "header":
                return QBrush(QColor(t["accent"]))
            if col == 2:
                return QBrush(QColor(t["dim"]))
        if role == ENTRY_ROLE:
            return entry
        return None

    def _home_icon(self, entry: Entry):
        icon = self._home_base_icon(entry)
        return with_light(icon, entry.status) if entry.status and icon is not None else icon

    def _home_base_icon(self, entry: Entry):
        t = theme.current()
        if entry.kind == "header":
            return None
        if entry.kind in DRIVE_ICONS:
            return icon_set.icon(DRIVE_ICONS[entry.kind], t["dim"])
        if entry.kind == "place":
            return icon_set.icon("home" if entry.note == USER_FOLDER_NOTE else "folder", t["accent"])
        if entry.kind == "pin":
            return icon_set.icon("folder", t["accent"])
        if entry.kind == "netloc":
            return icon_set.icon("network", t["dim"])
        if entry.kind == "action":
            return icon_set.icon("folder-plus", t["accent"])
        return None

    def _thumb_icon(self, entry: Entry):
        """The picture of an item in the thumbnail view: its thumbnail when there is one, its type icon until it is made (or if it has none)."""
        base = self._framed(self._icon(entry, False))
        provider = self.thumbs
        kind = covers.kind_of(entry.name, entry.is_dir)
        if provider is None or not provider.wanted(kind, self._network):
            return base
        key = provider.key(entry.path, entry.mtime, entry.size, self.icon_px)
        known, pixmap = provider.get(key)
        if known:
            return QIcon(pixmap) if pixmap is not None else base
        provider.request(key, kind, entry.path, self.icon_px)
        return base

    def _framed(self, icon: QIcon) -> QIcon:
        """A type icon for the thumbnail view: in the middle of a tile-sized square, about half as big, so it reads as a symbol and
        not as a picture."""
        key = (icon.cacheKey(), self.icon_px)
        cached = self._framed_cache.get(key)
        if cached is not None:
            return cached
        app = QApplication.instance()
        ratio = (app.devicePixelRatio() if app is not None else 1.0) or 1.0
        side = int(self.icon_px * ratio)
        inner = int(side * 0.55)
        canvas = QPixmap(side, side)
        canvas.fill(Qt.GlobalColor.transparent)
        symbol = icon.pixmap(QSize(inner, inner))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap((side - inner) // 2, (side - inner) // 2, inner, inner, symbol)
        painter.end()
        canvas.setDevicePixelRatio(ratio)
        framed = QIcon(canvas)
        if len(self._framed_cache) > 400:
            self._framed_cache.clear()
        self._framed_cache[key] = framed
        return framed

    def thumb_ready(self, path: str) -> None:
        """A thumbnail was made: redraw that item."""
        if not self.icon_px:
            return
        key = (id(self._rows), len(self._rows))
        if self._rc_key != key:
            self._rc = {e.path: i for i, e in enumerate(self._rows)}
            self._rc_key = key
        i = self._rc.get(path)
        if i is not None:
            row = i + (1 if self._up else 0)
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def _icon(self, entry: Entry, is_up: bool):
        """Gold for marked items and folders, the quiet text colour for the rest."""
        t = theme.current()
        name = icon_name(entry.name, is_dir=entry.is_dir, is_link=entry.is_link, is_up=is_up)
        color = t["marked"] if self.is_marked(entry) else (t["accent"] if entry.is_dir and not is_up else t["dim"])
        return icon_set.icon(name, color)

    def refresh_marks(self) -> None:
        if self.entry_count():
            self.dataChanged.emit(self.index(0, 0), self.index(self.entry_count() - 1, len(COLUMNS) - 1))
