"""The window's side of the sidebar (card 60B): making it, showing and hiding it (View > Bars > Sidebar), keeping its list fresh from
the Home page's entries on a thread, and what a click, the eject mark and the right-click menu do."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QSplitter

from ..core.eject import can_eject
from .background import run_in_background
from .sidebar import DEFAULT_WIDTH, SideList, build_sidebar_entries, short_title


class SidebarMixin:
    """Part of ``MainWindow``."""

    _sidebar_reading = False
    _sidebar_again = False

    def build_sidebar(self) -> QSplitter:
        """The sidebar beside the two panels, in a splitter of its own; hidden until View > Bars > Sidebar (or the saved choice) shows it."""
        self.sidebar = SideList()
        self._sidebar_jobs: list = []
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.sidebar)
        self.split.addWidget(self.panel_split)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.sidebar.setMinimumWidth(110)
        self.sidebar.setVisible(False)
        self.sidebar.place_clicked.connect(self._sidebar_clicked)
        self.sidebar.place_menu.connect(self._sidebar_menu)
        self.sidebar.eject_clicked.connect(lambda e: self.eject_drive(e.path, e.kind, short_title(e)))   # looked up when used: a test swaps it
        self.split.splitterMoved.connect(lambda *_a: self._remember_sidebar_width())
        return self.split

    def sidebar_wanted(self) -> bool:
        return str(self.settings.value("view/sidebar", "false")).lower() == "true"

    def sidebar_width(self) -> int:
        try:
            return max(110, int(self.settings.value("window/sidebar_width", DEFAULT_WIDTH)))
        except (TypeError, ValueError):
            return DEFAULT_WIDTH

    def set_sidebar_visible(self, on: bool) -> None:
        self.settings.setValue("view/sidebar", "true" if on else "false")
        self.sidebar.setVisible(on)
        if on:
            width = self.sidebar_width()
            self.split.setSizes([width, max(1, self.split.width() - width)])
            self.refresh_sidebar()

    def _remember_sidebar_width(self) -> None:
        if self.sidebar.isVisibleTo(self):
            width = self.split.sizes()[0]
            if width > 0:
                self.settings.setValue("window/sidebar_width", width)

    # the list ------------------------------------------------------------------------------------------------------------------
    def refresh_sidebar(self) -> None:
        """Read the places again, on a thread, and show them. Does nothing while the sidebar is hidden (showing it reads them)."""
        if getattr(self, "_closing", False) or not self.sidebar.isVisibleTo(self):
            return
        if self._sidebar_reading:
            self._sidebar_again = True                  # a reading is under way: one more follows it
            return
        self._sidebar_reading = True

        def work(progress, cancel):
            try:
                return build_sidebar_entries(self.home_provider)
            except Exception:                           # a failing drive list leaves the sidebar as it was; it is not worth a box
                return None

        def done(groups) -> None:
            if groups is not None and self.sidebar.isVisibleTo(self):
                self.sidebar.set_groups(groups)

        def ended() -> None:
            self._sidebar_reading = False
            if self._sidebar_again:
                self._sidebar_again = False
                self.refresh_sidebar()

        run_in_background(self, self.cmd_runner, "Reading places", work, on_result=done, tracked=self._sidebar_jobs,
                          on_end=ended, failed_title="Sidebar")

    # what it does --------------------------------------------------------------------------------------------------------------
    def open_place(self, entry, panel=None, new_tab: bool = False) -> None:
        """Open a place of the sidebar in ``panel`` (default: the active one), as Enter does on that entry of the Home page."""
        panel = panel or self.active
        if entry.kind == "trash":
            self.open_trash(panel, new_tab)                 # the Mac's Trash is Finder's
        elif entry.kind == "server":
            self.open_server(entry.path, new_tab, panel)    # connects first, as from the Home page
        elif new_tab or panel._locked_here():
            panel.new_tab(entry.path)
        else:
            panel.set_folder(entry.path)

    def _sidebar_clicked(self, entry) -> None:
        self.open_place(entry)
        self.active.view.setFocus()

    def sidebar_menu(self, entry) -> QMenu:
        """The right-click menu of one place: Open, Open in the Other Panel, Eject where it works."""
        menu = QMenu(self)
        menu.addAction("Open" if entry.kind != "server" else "Open (connects first)").triggered.connect(lambda: self.open_place(entry))
        menu.addAction("Open in the Other Panel").triggered.connect(lambda: self.open_place(entry, self.other))
        if can_eject(entry.path, entry.kind):
            menu.addSeparator()
            menu.addAction("Eject").triggered.connect(lambda: self.eject_drive(entry.path, entry.kind, short_title(entry)))
        return menu

    def _sidebar_menu(self, entry, pos) -> None:
        self.sidebar_menu(entry).popup(pos)
