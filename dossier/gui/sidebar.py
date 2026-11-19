"""The sidebar (card 60B): a narrow list of places at the left of the window, shared by both panels.

It shows pinned folders, drives (with an eject mark where Eject works), servers and the Trash, taken from the Home page's own
entries (``core/home.build_entries``), so places are gathered once. The entries are built on a thread (they look at the disk);
this widget only shows a finished list. A click goes to the active panel (the window decides what opening an entry means).
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QToolButton, QWidget

from ..core.eject import can_eject
from ..core.filetypes import DRIVE_ICONS
from ..core.home import HomeProvider, build_entries
from . import icon_set, theme

DRIVE_KINDS = ("fixed", "removable", "optical", "other", "network")
SECTIONS = (("Pinned", ("pin",)), ("Drives", DRIVE_KINDS), ("Servers", ("server",)), ("", ("trash",)))
ENTRY_ROLE = Qt.ItemDataRole.UserRole
DEFAULT_WIDTH = 170


def sidebar_entries(entries: list) -> list:
    """The Home page's entries the sidebar shows, in its order, as ``(heading, [entry, ...])`` (a section with none is left out)."""
    out = []
    for heading, kinds in SECTIONS:
        found = [e for e in entries if e.kind in kinds]
        if found:
            out.append((heading, found))
    return out


def build_sidebar_entries(provider: HomeProvider) -> list:
    """Worked out on a thread: the Home page's entries, grouped for the sidebar. ``build_entries`` is looked up here so a test can watch it."""
    return sidebar_entries(build_entries(provider))


def short_title(entry) -> str:
    """The drive's name without its label, as the drive menu words it ("E:" not "E:  Stick") for messages and the eject call."""
    return entry.name.split("  ")[0]


class SideList(QListWidget):
    """The list itself: one click on a place opens it; the eject mark is its own button."""
    place_clicked = pyqtSignal(object)
    place_menu = pyqtSignal(object, object)       # entry, global position
    eject_clicked = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setIconSize(QSize(16, 16))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.itemClicked.connect(self._clicked)
        self.customContextMenuRequested.connect(self._menu)
        self.groups: list = []

    def entry_of(self, item) -> Optional[object]:
        return item.data(ENTRY_ROLE) if item is not None else None

    def _clicked(self, item) -> None:
        entry = self.entry_of(item)
        if entry is not None:
            self.place_clicked.emit(entry)

    def _menu(self, pos) -> None:
        entry = self.entry_of(self.itemAt(pos))
        if entry is not None:
            self.place_menu.emit(entry, self.viewport().mapToGlobal(pos))

    def set_groups(self, groups: list, ejectable: Callable[[object], bool] = lambda e: can_eject(e.path, e.kind)) -> None:
        self.groups = groups
        self.clear()
        fg, dim, accent = theme.current()["fg"], theme.current()["dim"], theme.current()["accent"]
        for heading, entries in groups:
            if heading:
                head = QListWidgetItem(heading.upper())
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                font = head.font()
                font.setPointSizeF(max(7.0, font.pointSizeF() * 0.8))
                head.setFont(font)
                self.addItem(head)
            for entry in entries:
                self._add_entry(entry, fg, dim, accent, ejectable(entry))

    def _add_entry(self, entry, fg: str, dim: str, accent: str, can_eject_it: bool) -> None:
        if entry.kind in ("pin", "place"):
            name, color = "folder", accent
        elif entry.kind == "trash":
            name, color = "trash", dim
        else:
            name, color = DRIVE_ICONS.get(entry.kind, "database"), dim
        item = QListWidgetItem(icon_set.icon(name, color), short_title(entry) if entry.kind in DRIVE_KINDS else entry.name)
        item.setData(ENTRY_ROLE, entry)
        item.setToolTip(entry.detail or entry.path)
        self.addItem(item)
        if can_eject_it:
            self._add_eject_mark(item, entry, fg)

    def _add_eject_mark(self, item, entry, fg: str) -> None:
        """A small button at the right end of the row; the row's own text stays under it."""
        holder = QWidget()
        holder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 4, 0)
        spacer = QLabel()
        spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(spacer, 1)
        button = QToolButton()
        button.setObjectName("ejectmark")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setText(chr(0x23CF))                    # the eject sign: the icon sets draw none
        button.setStyleSheet(f"QToolButton {{ color: {fg}; border: none; padding: 0 2px; }}")
        button.setToolTip(f"Eject {short_title(entry)}")
        button.clicked.connect(lambda _c=False, e=entry: self.eject_clicked.emit(e))
        row.addWidget(button)
        item.setSizeHint(QSize(0, max(24, button.sizeHint().height() + 2)))
        holder.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setItemWidget(item, holder)

    def restyle(self) -> None:
        self.set_groups(self.groups)

    def entries(self) -> list:
        """Every place on show, in order (headings left out)."""
        return [e for _h, es in self.groups for e in es]
