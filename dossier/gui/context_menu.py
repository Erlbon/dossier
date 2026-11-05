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

from ..core import archives, sharing, shellmenu
from ..core.mounting import SMB
from ..core.platform import FILE_MANAGER_NAME
from ..core.home import is_home
from . import file_clipboard
from .menus import command_keys, command_label
from .tailnet import KINDS as TAILNET_KINDS

ARCHIVE_NAMES = archives.FOLDER_EXTENSIONS
SHARABLE_HOME_KINDS = ("fixed", "removable", "other", "place", "pin")     # drives and folders of this computer (not network, servers)


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

    def _entry_action(self, menu: QMenu, text, slot, panel, paths, enabled: bool = True, keys: str = "",
                      row: int = -1) -> QAction:
        """One entry. ``slot`` is a function, or the name of a menu-bar command ("rename"): then the key hint is always that menu action's
        own keys (so it follows Settings > Function Keys), ``text=None`` takes its label too (a text given here is a label that fits this
        menu better, "Properties of This Folder"), and the command is looked up when the entry is clicked."""
        if isinstance(slot, str):
            bar = self.bar_command(slot)
            text = text or command_label(bar)
            keys = command_keys(bar)
        action = menu.addAction(text + ("\t" + keys if keys else ""))
        action.setEnabled(enabled)

        def run(_checked=False) -> None:
            self._set_active(panel)
            if row >= 0:
                panel.table.setCurrentIndex(panel.model.index(row, 0))          # the item the menu was opened on
            with self._acting_on(panel, paths):
                (getattr(self, slot) if isinstance(slot, str) else slot)()

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
        if sharing.machine_of(panel.path):
            return self._machine_share_menu(panel, entry, row)
        marked = panel.marked_here()
        paths = marked if entry.path in marked else [entry.path]
        many = len(paths) > 1
        name = entry.name.lower()
        is_archive = (not entry.is_dir) and name.endswith(ARCHIVE_NAMES)
        convertible = is_archive and not name.endswith(".zip")
        menu = QMenu(self)
        add = lambda text, slot, enabled=True, keys="": self._entry_action(menu, text, slot, panel, paths, enabled, keys, row)  # noqa: E731
        cmd = lambda slot, enabled=True: add(None, slot, enabled)   # noqa: E731  a menu-bar command, with its label and keys
        cmd("open_cursor_item")
        if entry.is_dir:
            add("Open in a New Tab", lambda: panel.open_current(new_tab=True), keys="Ctrl+Enter")
            add("Open in the Other Panel", "open_in_other_panel")
            add("Terminal Here", lambda: self.open_terminal(folder=entry.path), enabled=not many, keys=self.keys_of("open_terminal"))
            add("Pin to the Home Page", lambda: self.pin_folder(entry.path), enabled=not many, keys=self.keys_of("pin_folder"))
            if not many:
                self.add_share_entries(menu, entry.path)
            add("Find Duplicate Files in This Folder...", lambda: self.find_duplicate_files(panel, entry.path), enabled=not many)
        else:
            cmd("view_file", enabled=not many)
            cmd("edit_file", enabled=not many)
        menu.addSeparator()
        cmd("copy")
        cmd("move")
        menu.addSeparator()
        cmd("clip_copy")
        cmd("clip_cut")
        cmd("clip_paste", enabled=bool(file_clipboard.get()[0]))
        cmd("copy_marked_paths")
        menu.addSeparator()
        cmd("rename", enabled=not many)
        batch = menu.addMenu("Batch Rename")
        for slot in ("rename_by_pattern", "rename_search_replace", "rename_case", "rename_number"):
            self._entry_action(batch, None, slot, panel, paths, True, "", row)
        cmd("delete")
        menu.addSeparator()
        cmd("pack_to_zip")
        if is_archive:
            cmd("unpack_archive", enabled=not many)
        if convertible:
            cmd("convert_archive_to_zip", enabled=not many)
        menu.addSeparator()
        cmd("change_dates")
        cmd("move_to_quarantine")
        cmd("new_link", enabled=not many)
        cmd("show_properties")
        cmd("show_in_file_manager")
        if shellmenu.can_show(paths):
            menu.addSeparator()
            add("More Options (Windows Menu)...", lambda: self._windows_menu(panel, paths, False))
        return menu

    def _machine_share_menu(self, panel, entry, row: int = -1) -> QMenu:
        """A share in another computer's list (``\\\\machine``): open it, keep it on the Home page or mount it. Nothing that would
        change, move or delete the share itself."""
        menu = QMenu(self)
        add = lambda text, slot, enabled=True, keys="": self._entry_action(menu, text, slot, panel, [entry.path], enabled, keys, row)  # noqa: E731
        add(None, "open_cursor_item")
        add("Open in a New Tab", lambda: panel.open_current(new_tab=True), keys="Ctrl+Enter")
        add("Open in the Other Panel", "open_in_other_panel")
        menu.addSeparator()
        add("Save on the Home Page", lambda: self.save_network_location(entry.path))
        add("Mount on a Drive Letter", lambda: self.mount_share_with(SMB, entry.path))
        add(None, "copy_marked_paths")
        return menu

    def _empty_menu(self, panel) -> QMenu:
        menu = QMenu(self)
        here = [panel.path]
        add = lambda text, slot, enabled=True, keys="": self._entry_action(menu, text, slot, panel, None, enabled, keys)  # noqa: E731
        if sharing.machine_of(panel.path):                       # another computer's list of shares
            add(None, "refresh")
            add("Save This Computer on the Home Page", lambda: self.save_network_location(panel.path))
            return menu
        add(None, "new_folder")
        add(None, "clip_paste", enabled=bool(file_clipboard.get()[0]))
        add(None, "select_all")
        menu.addSeparator()
        add(None, "open_terminal")
        self.add_share_entries(menu, panel.path, here=True)
        add(None, "search_files")
        add(None, "find_duplicate_files")
        add("Compare with the Other Panel...", "compare_folders")
        add("All Files Below This Folder", lambda: self.show_all_files_below(panel), keys=self.keys_of("show_all_files_below"))
        add(None, "refresh")
        menu.addSeparator()
        self._entry_action(menu, "Properties of This Folder", "show_properties", panel, here)
        add(f"Open This Folder in {FILE_MANAGER_NAME}", lambda: self.show_in_file_manager(folder_only=True))
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
            elif entry.kind == "tailnet":
                add("Show Shared Folders", lambda p=entry.path: self.show_tailnet_shares(p))
                add("Show Shared Folders in a New Tab", lambda p=entry.path: self.show_tailnet_shares(p, new_tab=True))
                menu.addSeparator()
                for kind, label in TAILNET_KINDS:
                    add(f"Add as {label}...", lambda k=kind, p=entry.path: self.add_tailnet_server(p, k))
                menu.addSeparator()
                add("Copy the Address", lambda p=entry.path: self.copy_tailnet_address(p))
                add("Read the Tailnet Again", lambda: self.refresh_tailnet(force=True))
            elif entry.kind == "server":
                conn = self.connection_for(entry.path)
                live = conn is not None and self.server_connected(conn)
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
                if entry.kind in SHARABLE_HOME_KINDS:
                    menu.addSeparator()
                    label = entry.name.split("  ", 1)[1] if "  " in entry.name else ""
                    self.add_share_entries(menu, entry.path, label=label)
        if not menu.actions():
            add(None, "add_network_share")
        return menu
