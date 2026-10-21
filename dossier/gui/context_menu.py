"""The right-click menu of the file lists (and the Menu key / Shift+F10).

It acts on the items under the same rule as dragging: right-click a marked item and the menu works on all the marked items, right-click
an unmarked item and it works on that item alone, and the marks stay as they are. Every entry runs a command the program already has
(the same one as its menu entry and key), so there is nothing here that decides what a command does. Nothing in the menu touches the
disk: whether an entry shows is judged from the names alone.
"""
from __future__ import annotations

from contextlib import contextmanager

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu

from ..core import archives, shellmenu
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

    # the Windows menu ---------------------------------------------------------------------------------------------------------
    def _start_shell_menu(self, paths, x, y, on_done, background, extended) -> None:     # a seam for tests
        shellmenu.show_in_thread(paths, x, y, on_done, background=background, extended=extended)

    def _windows_menu(self, panel, paths, background: bool) -> None:
        """The shell's own menu, built and shown on a thread of its own (a slow extension never freezes this window). Shift held shows
        the extended entries. Cut, Copy, Paste, Delete and Rename come back here and run as Dossier's own commands."""
        x, y = shellmenu.cursor_pos()
        extended = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._say("Opening the Windows menu...")
        self._start_shell_menu(list(paths), x, y, lambda outcome: self.dispatcher(lambda: self._windows_menu_done(panel, paths, background, outcome)),
                               background, extended)

    def _windows_menu_done(self, panel, paths, background: bool, outcome) -> None:
        if outcome.error:
            self._say(outcome.error)
            return
        if outcome.verb:
            commands = {"cut": self.clip_cut, "copy": self.clip_copy, "paste": self.clip_paste, "delete": self.delete,
                        "rename": self.rename}
            run = commands.get(outcome.verb)
            if run is not None and (not background or outcome.verb == "paste"):
                self._set_active(panel)
                with self._acting_on(panel, None if background else paths):
                    run()
            return
        self._say("")
        if outcome.ran:                                  # the shell may have made, extracted or changed files
            self.left.refresh()
            self.right.refresh()

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
            add("Terminal Here", lambda: self.open_terminal(folder=entry.path), enabled=not many, keys="Ctrl+Shift+T")
            add("Pin to the Home Page", lambda: self.pin_folder(entry.path), enabled=not many, keys="Ctrl+D")
            add("Find Duplicate Files in This Folder...", lambda: self.find_duplicate_files(panel, entry.path), enabled=not many)
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
        batch = menu.addMenu("Batch Rename")
        for text, slot, keys in (("By Pattern...", self.rename_by_pattern, "Ctrl+M"),
                                 ("Search and Replace in Names...", self.rename_search_replace, ""),
                                 ("Change Case...", self.rename_case, ""), ("Number the Files...", self.rename_number, "")):
            self._entry_action(batch, text, slot, panel, paths, True, keys, row)
        add("Delete", self.delete, keys="F8")
        menu.addSeparator()
        add("Pack to Zip...", self.pack_to_zip, keys="Alt+F5")
        if is_archive:
            add("Unpack...", self.unpack_archive, enabled=not many, keys="Alt+F9")
        if convertible:
            add("Convert Archive to Zip", self.convert_archive_to_zip, enabled=not many)
        menu.addSeparator()
        add("Properties", self.show_properties, keys="Alt+Enter")
        if shellmenu.can_show(paths):
            menu.addSeparator()
            add("More Options (Windows Menu)...", lambda: self._windows_menu(panel, paths, False))
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
        add("Find Duplicate Files...", self.find_duplicate_files, keys="Alt+Shift+F7")
        add("Compare with the Other Panel...", self.compare_folders, keys="Alt+Shift+F8")
        add("All Files Below This Folder", lambda: self.show_all_files_below(panel), keys="Ctrl+Shift+B")
        add("Refresh", self.refresh, keys="Ctrl+R")
        menu.addSeparator()
        self._entry_action(menu, "Properties of This Folder", self.show_properties, panel, here, keys="Alt+Enter")
        if shellmenu.folder_can_show(panel.path):
            menu.addSeparator()
            add("More Options (Windows Menu)...", lambda: self._windows_menu(panel, here, True))
        return menu

    def _home_menu(self, panel, entry, row: int = -1) -> QMenu:
        menu = QMenu(self)
        add = lambda text, slot, enabled=True: self._entry_action(menu, text, slot, panel, None, enabled, "", row)  # noqa: E731
        if entry is not None and entry.kind not in ("header",):
            if entry.kind == "action":
                add(entry.name.rstrip("."), panel.open_current)
            elif entry.kind == "server":
                conn = self.connection_for(entry.path)
                live = conn is not None and self.fs.sftp.connected(conn.authority())
                add("Open" if live else "Connect", panel.open_current)
                add("Open in a New Tab", lambda: panel.open_current(new_tab=True))
                if conn is not None:
                    menu.addSeparator()
                    add("Disconnect", lambda: self.disconnect_server(conn), enabled=live)
                    add("Edit...", lambda: self.edit_server(conn))
                    add("Remove from the Home Page", lambda: self.remove_server(conn))
            else:
                add("Open", panel.open_current)
                add("Open in a New Tab", lambda: panel.open_current(new_tab=True))
                if entry.kind in ("pin", "netloc"):
                    menu.addSeparator()
                    add("Remove from the Home Page", self.remove_from_home)
        if not menu.actions():
            add("Add a Network Share...", self.add_network_share)
        return menu
