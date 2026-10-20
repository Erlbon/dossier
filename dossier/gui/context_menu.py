"""The right-click menu of the file lists (and the Menu key / Shift+F10).

It acts on the items under the same rule as dragging: right-click a marked item and the menu works on all the marked items, right-click
an unmarked item and it works on that item alone, and the marks stay as they are. Every entry runs a command the program already has
(the same one as its menu entry and key), so there is nothing here that decides what a command does. Nothing in the menu touches the
disk: whether an entry shows is judged from the names alone.
"""
from __future__ import annotations

from contextlib import contextmanager

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from ..core import archives
from ..core.home import is_home
from . import file_clipboard

ARCHIVE_NAMES = archives.FOLDER_EXTENSIONS


class ContextMenuMixin:
    """Part of ``MainWindow``."""

    @contextmanager
    def _acting_on(self, panel, paths):
        """Run a command on exactly ``paths`` (what the right-click was on), whatever else is marked."""
        panel.target_override = list(paths) if paths is not None else None
        try:
            yield
        finally:
            panel.target_override = None

    def _entry_action(self, menu: QMenu, text: str, slot, panel, paths, enabled: bool = True, keys: str = "",
                      row: int = -1) -> QAction:
        action = menu.addAction(text + ("\t" + keys if keys else ""))
        action.setEnabled(enabled)

        def run(_checked=False) -> None:
            self._set_active(panel)
            if row >= 0:
                panel.table.setCurrentIndex(panel.model.index(row, 0))          # the item the menu was opened on
            with self._acting_on(panel, paths):
                slot()

        action.triggered.connect(run)
        return action

    # which menu ----------------------------------------------------------------------------------------------------------
    def build_context_menu(self, panel, row: int) -> QMenu:
        entry = panel.model.entry_at(row) if row >= 0 else None
        if panel.is_home or is_home(panel.path):
            return self._home_menu(panel, entry, row)
        if entry is not None and entry.name != ".." and entry.kind not in ("header", "action"):
            return self._item_menu(panel, entry, row)
        return self._empty_menu(panel)

    def show_context_menu(self, panel, global_pos, row: int) -> None:
        menu = self.build_context_menu(panel, row)
        if menu.actions():
            self._popup_menu(menu, global_pos)

    def _popup_menu(self, menu: QMenu, global_pos) -> None:      # a seam for tests
        menu.exec(global_pos)

    # the menus -----------------------------------------------------------------------------------------------------------
    def _item_menu(self, panel, entry, row: int = -1) -> QMenu:
        marked = panel.marked_here()
        paths = marked if entry.path in marked else [entry.path]
        many = len(paths) > 1
        name = entry.name.lower()
        is_archive = (not entry.is_dir) and name.endswith(ARCHIVE_NAMES)
        convertible = is_archive and not name.endswith(".zip")
        menu = QMenu(self)
        add = lambda text, slot, enabled=True, keys="": self._entry_action(menu, text, slot, panel, paths, enabled, keys, row)  # noqa: E731
        add("Open", panel.open_current, keys="Enter")
        if entry.is_dir:
            add("Open in a New Tab", lambda: panel.open_current(new_tab=True), keys="Ctrl+Enter")
            add("Open in the Other Panel", self.open_in_other_panel, keys="Ctrl+Left/Right")
        else:
            add("View", self.view_file, enabled=not many, keys="F3")
            add("Edit", self.edit_file, enabled=not many, keys="F4")
        menu.addSeparator()
        add("Copy to the Other Panel", self.copy, keys="F5")
        add("Move to the Other Panel", self.move, keys="F6")
        menu.addSeparator()
        add("Copy", self.clip_copy, keys="Ctrl+C")
        add("Cut", self.clip_cut, keys="Ctrl+X")
        add("Paste", self.clip_paste, enabled=bool(file_clipboard.get()[0]), keys="Ctrl+V")
        add("Copy the Path as Text", self.copy_marked_paths)
        menu.addSeparator()
        add("Rename", self.rename, enabled=not many, keys="F2")
        add("Delete", self.delete, keys="F8")
        menu.addSeparator()
        add("Pack to Zip...", self.pack_to_zip, keys="Alt+F5")
        if is_archive:
            add("Unpack...", self.unpack_archive, enabled=not many, keys="Alt+F9")
        if convertible:
            add("Convert Archive to Zip", self.convert_archive_to_zip, enabled=not many)
        menu.addSeparator()
        add("Properties", self.show_properties, keys="Alt+Enter")
        return menu

    def _empty_menu(self, panel) -> QMenu:
        menu = QMenu(self)
        here = [panel.path]
        add = lambda text, slot, enabled=True, keys="": self._entry_action(menu, text, slot, panel, None, enabled, keys)  # noqa: E731
        add("New Folder", self.new_folder, keys="F7")
        add("Paste", self.clip_paste, enabled=bool(file_clipboard.get()[0]), keys="Ctrl+V")
        add("Select All", self.select_all, keys="Ctrl+A")
        menu.addSeparator()
        add("Terminal Here", self.open_terminal, keys="Ctrl+Shift+T")
        add("Search...", self.search_files, keys="Alt+F7")
        add("All Files Below This Folder", lambda: self.show_all_files_below(panel), keys="Ctrl+Shift+B")
        add("Refresh", self.refresh, keys="Ctrl+R")
        menu.addSeparator()
        self._entry_action(menu, "Properties of This Folder", self.show_properties, panel, here, keys="Alt+Enter")
        return menu

    def _home_menu(self, panel, entry, row: int = -1) -> QMenu:
        menu = QMenu(self)
        add = lambda text, slot, enabled=True: self._entry_action(menu, text, slot, panel, None, enabled, "", row)  # noqa: E731
        if entry is not None and entry.kind not in ("header",):
            if entry.kind == "action":
                add(entry.name.rstrip("."), panel.open_current)
            else:
                add("Open", panel.open_current)
                add("Open in a New Tab", lambda: panel.open_current(new_tab=True))
                if entry.kind in ("pin", "netloc"):
                    menu.addSeparator()
                    add("Remove from the Home Page", self.remove_from_home)
        if not menu.actions():
            add("Add a Network Share...", self.add_network_share)
        return menu
