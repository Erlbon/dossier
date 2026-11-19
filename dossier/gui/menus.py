"""The menu bar: File, Edit, Mark, View, Go, Tools, Network, Settings, Help.

Each menu answers one question, and a new command goes in the menu whose question it answers (CLAUDE.md, "Menus"). File: what can I do
to the files under the cursor. Edit: undo and the clipboard. Mark: which files are marked. View: how a folder is shown. Go: where am I,
and where to next (folders, panels, tabs, drives). Tools: the bigger jobs on many files (search, compare, rename, archives, checksums,
quarantine, operations, terminals). Network: servers, shares and network drives. Settings: how Dossier looks (Appearance) and behaves.
Help: shortcuts, updates, About and the slowness log. Every command keeps its shortcut wherever it lives.

The right-click menu takes the label and the key hint of a command from its menu-bar action (``bar_command``), so the two never say
different things and the hint follows Settings > Function Keys. ``tests/test_menu_rules.py`` keeps the menus from drifting.
"""
from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import QMenu

from redactor_common.gui.command_palette import add_command_palette

from ..core import fkey_config, second_keys
from ..core.platform import FILE_MANAGER_NAME
from ..core.version import APP_NAME, APP_REPO_URL
from . import fkeys


def command_label(action: QAction) -> str:
    """The label of a menu action without its key hint."""
    return action.text().split("\t")[0]


def command_keys(action: QAction) -> str:
    """The keys of a menu action as the menus show them: its shortcuts, or the hint after a tab for a key the window does not own
    (Enter belongs to the panel)."""
    keys = [s.toString(QKeySequence.SequenceFormat.NativeText) for s in action.shortcuts()]
    hint = action.text().split("\t", 1)[1] if "\t" in action.text() else ""
    return ", ".join(([hint] if hint else []) + keys)        # the hint is the panel's own key (Enter, Backspace): it stays first


class MenusMixin:
    """Part of ``MainWindow``."""

    def _action(self, text: str, keys, slot) -> QAction:
        """A menu action. The keys given here are the fixed ones; the function keys (F5, Shift+F5, Ctrl+F5) are not set from here but from the
        function key table (``apply_fkey_shortcuts``), for every action whose slot is one of the commands in ``fkeys.COMMANDS``."""
        act = QAction(text, self)
        fixed = [k for k in (keys if isinstance(keys, (list, tuple)) else [keys] if keys else []) if not fkey_config.assignable(k)]
        if fixed:
            act.setShortcuts([QKeySequence(k) for k in fixed])
        self.__dict__.setdefault("_fixed_keys", {})[act] = fixed
        command = getattr(slot, "__name__", "")
        if command in fkeys.COMMANDS:
            self.__dict__.setdefault("_command_actions", {})[command] = (act, fixed)
        if getattr(slot, "__self__", None) is self:          # a command of the window: the right-click menu finds it by its slot
            self.__dict__.setdefault("_bar_commands", {})[command] = act
        act.triggered.connect(lambda _checked=False: slot())
        self.addAction(act)
        return act

    def bar_command(self, name: str) -> QAction:
        """The menu-bar action of the window's command ``name`` ("rename")."""
        return self.__dict__["_bar_commands"][name]

    def keys_of(self, name: str) -> str:
        """The key hint of the window's command ``name``, for a right-click entry that runs it on the clicked item."""
        return command_keys(self.bar_command(name))

    def apply_fkey_shortcuts(self) -> None:
        """Put every function key of the table on the action of its command (and take it off any other): one key, one action."""
        for command, (act, fixed) in self.__dict__.get("_command_actions", {}).items():
            assigned = [fkey_config.key_text(layer, n) for layer in fkey_config.LAYERS
                        for n, c in sorted(self._fkey_table.get(layer, {}).items()) if c == command]
            act.setShortcuts([QKeySequence(k) for k in self._dedupe(fixed + assigned + self._second_of(act))])

    @staticmethod
    def _dedupe(keys: list) -> list:
        return list(dict.fromkeys(keys))

    def _second_of(self, act: QAction) -> list:
        return list(self.__dict__.get("_second_map", {}).get(act, ()))

    def apply_second_keys(self, system: str = "") -> None:
        """Put Finder's or the Linux desktops' keys after each command's own keys (card 51A, ``core/second_keys.py``). ``system`` is
        ``"mac"``, ``"linux"`` or ``"windows"``; empty means this one. Calling it again for another system takes the old keys off."""
        self.keys_system = system or self.__dict__.get("keys_system") or second_keys.current_system()
        table = second_keys.second_keys(self.keys_system)
        self._second_map = {self._second_actions[name]: keys for name, keys in table.items() if name in self._second_actions}
        first_root = second_keys.first_key("go_root", self.keys_system)
        self._fixed_keys[self.act_root] = [first_root]
        fkey_actions = {act for act, _fixed in self.__dict__.get("_command_actions", {}).values()}
        for act, fixed in self._fixed_keys.items():
            if act not in fkey_actions:
                act.setShortcuts([QKeySequence(k) for k in self._dedupe(fixed + self._second_of(act))])
        self.apply_fkey_shortcuts()

    def guarded_keys(self) -> frozenset:
        """The second keys a text field keeps for itself while it has the focus (Cmd+Backspace deletes text there, not files). Alt+Left
        and Alt+Right are left out: they were Back and Forward everywhere before, text field or not."""
        return second_keys.second_key_set(self.keys_system) - {"Alt+Left", "Alt+Right"}

    def _build_menus(self) -> None:
        self.__dict__.setdefault("keys_system", second_keys.current_system())
        bar = self.menuBar()
        self._build_file_menu(bar.addMenu("&File"))
        self._build_edit_menu(bar.addMenu("&Edit"))
        self._build_mark_menu(bar.addMenu("&Mark"))
        self._build_view_menu(bar.addMenu("&View"))
        self._build_go_menu(bar.addMenu("&Go"))
        self._build_tools_menu(bar.addMenu("&Tools"))
        self._build_network_menu(bar.addMenu("&Network"))
        self._build_settings_menu(bar.addMenu("&Settings"))
        self._build_help_menu()
        for menu in bar.findChildren(QMenu):
            menu.setToolTipsVisible(True)                    # the explanations of entries are their tooltips, not grey lines
        self._second_actions = {"delete": self.act_delete, "go_up": self.act_parent, "open": self.act_open, "back": self.act_back,
                                "forward": self.act_forward, "go_to_folder": self.act_edit_path, "show_hidden": self.act_show_hidden,
                                "properties": self.act_properties, "new_folder": self.act_mkdir}
        self.apply_second_keys()

    @staticmethod
    def _add_all(menu, *groups) -> None:
        """Add groups of actions with a separator between the groups."""
        for i, group in enumerate(groups):
            if i:
                menu.addSeparator()
            for a in group:
                menu.addAction(a)

    # File -----------------------------------------------------------------------------------------------------------------------
    def open_cursor_item(self) -> None:
        """File > Open: what Enter does in the active panel."""
        self.active.open_current()

    def _build_file_menu(self, file_menu) -> None:
        self.act_open = self._action("Open\tEnter", None, self.open_cursor_item)
        self.act_view = self._action("View", None, self.view_file)
        self.act_glass_view = self._action("View as Glass", None, self.glass_view)
        self.act_edit = self._action("Edit", None, self.edit_file)
        self.act_rename = self._action("Rename", None, self.rename)
        self.act_copy = self._action("Copy to the Other Panel", None, self.copy)
        self.act_move = self._action("Move to the Other Panel", None, self.move)
        self.act_copy_box = self._action("Copy...", None, self.copy_with_box)          # the box: elsewhere, only some files, verify
        self.act_move_box = self._action("Move...", None, self.move_with_box)
        self.act_mkdir = self._action("New Folder", None, self.new_folder)
        self.act_new_file = self._action("New File...", None, self.new_file)
        self.act_change_dates = self._action("Change Dates and Attributes...", None, self.change_dates)
        self.act_new_link = self._action("New Link...", None, self.new_link)
        self.act_delete = self._action("Delete", "Delete", self.delete)
        self.act_delete_perm = self._action("Delete Permanently", None, self.delete_permanently)
        self.act_properties = self._action("Properties", "Alt+Return", self.show_properties)
        self.act_show_in_fm = self._action(f"Show in {FILE_MANAGER_NAME}", None, self.show_in_file_manager)
        # Quick Look (card 45A): the Mac's and the GNOME previewer, not on Windows. Ctrl+Y is Cmd+Y on the Mac. Hidden until the
        # system has one (on Linux that is looked up on a thread), so the key does nothing where there is no previewer.
        self.act_quick_look = self._action("Quick Look", "Ctrl+Y" if self.quick_look_info.system else None, self.quick_look)
        self.act_quick_look.setVisible(self.quick_look_info.available)
        # View, View as Glass and Quick Look share one submenu (owner, 2026-11-19, option A): with Quick Look the File menu had 17.
        preview_menu = QMenu("Preview", self)
        for act in (self.act_view, self.act_glass_view, self.act_quick_look):
            preview_menu.addAction(act)
        preview_menu.aboutToShow.connect(lambda: self.act_quick_look.setVisible(self.quick_look_info.available))
        # File keeps to 16 entries (tests/test_menu_rules.py): with Copy... and Move... (2026-11-11) the three New commands share a
        # submenu, as in Explorer. Their own labels stay, so the right-click menu reads the same.
        new_menu = QMenu("New", self)
        for act in (self.act_mkdir, self.act_new_file, self.act_new_link):
            new_menu.addAction(act)
        self._add_all(file_menu,
                      (self.act_open, preview_menu.menuAction(), self.act_edit),
                      (self.act_rename, self.act_copy, self.act_copy_box, self.act_move, self.act_move_box, new_menu.menuAction()),
                      (self.act_change_dates,),
                      (self.act_delete, self.act_delete_perm),
                      (self.act_properties, self.act_show_in_fm),
                      (self._action("Quit", "Ctrl+Q", self.close),))

    # Edit -----------------------------------------------------------------------------------------------------------------------
    def _build_edit_menu(self, edit) -> None:
        self._add_all(edit,
                      (self._action("Undo", "Ctrl+Z", self.undo),),
                      (self._action("Copy", "Ctrl+C", self.clip_copy),
                       self._action("Cut", "Ctrl+X", self.clip_cut),
                       self._action("Paste", "Ctrl+V", self.clip_paste),
                       self._action("Paste as New File...", "Ctrl+Shift+V", self.paste_as_new_file)),
                      (self._action("Copy Paths as Text", None, self.copy_marked_paths),
                       self._action("Copy Names as Text", None, self.copy_marked_names),
                       self._action("Copy This Folder's Path", None, self.copy_folder_path)))

    # Mark -----------------------------------------------------------------------------------------------------------------------
    def _build_mark_menu(self, mark) -> None:
        self._add_all(mark,
                      (self._action("Mark All", "Ctrl+A", self.select_all),
                       self._action("Unmark All", "Ctrl+Shift+A", self.selection.clear),
                       self._action("Invert Marks", "*", self.invert_selection)),
                      (self._action("Mark by Pattern...", "+", self.mark_by_pattern),
                       self._action("Unmark by Pattern...", "-", lambda: self.mark_by_pattern(False)),
                       self._action("Mark by Tag...", None, self.mark_by_tag),
                       self._action("Unmark by Tag...", None, lambda: self.mark_by_tag(False))))
        mark.addSeparator()
        saved = mark.addMenu("Saved Marks")
        saved.addAction(self._action("Save Marks As...", None, self.save_selection))
        saved.addSeparator()
        self._restore_menu, self._add_menu, self._forget_menu = (saved.addMenu("Restore"), saved.addMenu("Add to Marks"),
                                                                 saved.addMenu("Forget"))
        saved.aboutToShow.connect(lambda: self.build_selection_menus(self._restore_menu, self._add_menu, self._forget_menu))
        self.build_selection_menus(self._restore_menu, self._add_menu, self._forget_menu)

    # View -----------------------------------------------------------------------------------------------------------------------
    def _build_view_menu(self, view_menu) -> None:
        self.view_mode_actions = {}
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        details = QAction("Details", self)
        details.setCheckable(True)
        details.setChecked(True)
        mode_group.addAction(details)
        view_menu.addAction(details)
        self.view_mode_actions["details"] = details
        self.add_view_mode_actions(view_menu, mode_group)              # Thumbnails, Thumbnail Size, Sort By
        view_menu.addAction(self._action("Columns...", None, self.open_column_settings))
        self.act_fit_columns = QAction("Fit Columns to Panel", self)
        self.act_fit_columns.setToolTip("On: the columns share the panel's width and Name takes the slack. "
                                        "Off: the last column stretches, and a scrollbar shows when the columns are too wide")
        self.act_fit_columns.setCheckable(True)
        self.act_fit_columns.setChecked(self.fit_columns_on())
        self.act_fit_columns.toggled.connect(self.set_fit_columns)
        view_menu.addAction(self.act_fit_columns)
        self._apply_fit_columns(self.fit_columns_on())
        self.add_layout_actions(view_menu)
        view_menu.aboutToShow.connect(self.sync_mode_actions)            # Thumbnail Size is greyed while the panel shows Details
        view_menu.addSeparator()
        self.act_show_hidden = QAction("Show Hidden and System Files", self)
        self.act_show_hidden.setCheckable(True)
        self.act_show_hidden.setShortcut("Ctrl+H")
        self._fixed_keys[self.act_show_hidden] = ["Ctrl+H"]
        self.addAction(self.act_show_hidden)
        shown = str(self.settings.value("view/show_hidden", "true")).lower() != "false"
        self.act_show_hidden.setChecked(shown)
        self.act_show_hidden.toggled.connect(self.set_show_hidden)
        for panel in (self.left, self.right):
            panel.model.set_show_hidden(shown)
        view_menu.addAction(self.act_show_hidden)
        for a in (self._action("All Files Below This Folder", "Ctrl+Shift+B", self.show_all_files_below),
                  self._action("Quick Filter", "Ctrl+S", lambda: self.active.start_filter()),
                  self._action("Folder Sizes", "Alt+Shift+Return", self.calculate_folder_sizes),
                  self._action("Refresh", "Ctrl+R", self.refresh)):
            view_menu.addAction(a)
        view_menu.addSeparator()
        notes = view_menu.addMenu("Folder Notes")
        self.act_notes = QAction("Show Folder Notes", self)
        self.act_notes.setCheckable(True)
        self.act_notes.setChecked(str(self.settings.value("view/notes", "true")).lower() != "false")
        self.act_notes.toggled.connect(self.set_notes_visible)
        notes.addAction(self.act_notes)
        notes.addAction(self._action("Edit Folder Note", "Ctrl+Shift+E", self.edit_folder_note))
        bars = view_menu.addMenu("Bars")                  # View is full (16): the two things that show and hide share a submenu
        self.act_tools_bar = QAction("Tools Bar", self)
        self.act_tools_bar.setCheckable(True)
        self.act_tools_bar.setChecked(self.tools_bar.isVisibleTo(self))
        self.act_tools_bar.toggled.connect(self.set_tools_bar_visible)
        bars.addAction(self.act_tools_bar)
        self.act_sidebar = QAction("Sidebar", self)       # card 60B: hidden until shown here
        self.act_sidebar.setToolTip("Pinned folders, drives, servers and the Trash, at the left of both panels")
        self.act_sidebar.setCheckable(True)
        self.act_sidebar.toggled.connect(self.set_sidebar_visible)
        bars.addAction(self.act_sidebar)
        self.build_bar_place_menus(view_menu)
        view_menu.addAction(self._action("Full Screen", None, self.toggle_full_screen))

    # Go -------------------------------------------------------------------------------------------------------------------------
    def _build_go_menu(self, go) -> None:
        self.act_back = self._action("Back", "Alt+Left", lambda: self.active.history_back())
        self.act_forward = self._action("Forward", "Alt+Right", lambda: self.active.history_forward())
        self.act_parent = self._action("Parent Folder\tBackspace", None, lambda: self.active.go_up())   # Backspace belongs to the panel
        self.act_root = self._action("Root of the Drive", second_keys.first_key("go_root", self.keys_system), self.go_to_root)
        self.act_edit_path = self._action("Edit the Path", "Ctrl+L", lambda: self.active.address_bar.start_edit())
        self._add_all(go,
                      (self.act_back, self.act_forward,
                       self._action("Folder History...", "Alt+Down", self.show_history),
                       self._action("Hotlist...", "Ctrl+B", self.show_hotlist),
                       self._action("Folder Tree...", "Alt+F10", self.show_folder_tree)),
                      (self._action("Home Page", "Alt+Home", lambda: self.active.go_home()),
                       self.act_parent,
                       self.act_root,
                       self.act_edit_path,
                       self._action("Pin Folder to Home Page", "Ctrl+D", self.pin_folder)),
                      (self._action("Open Cursor Folder in the Other Panel", ["Ctrl+Right", "Ctrl+Left"], self.open_in_other_panel),
                       self._action("Same Folder in the Other Panel", "Ctrl+Shift+O", self.same_in_other_panel),
                       self._action("Swap Panels", "Ctrl+U", self.swap_panels)))
        go.addSeparator()
        tabs_menu = go.addMenu("Tabs")
        for text, keys, slot in (("New Tab", "Ctrl+T", lambda: self.active.new_tab()),
                                 ("Close Tab", "Ctrl+W", lambda: self.active.close_tab(self.active.tabs.currentIndex())),
                                 ("Next Tab", "Ctrl+Tab", lambda: self.active.next_tab(1)),
                                 ("Previous Tab", "Ctrl+Shift+Tab", lambda: self.active.next_tab(-1)),
                                 ("Open Folder in New Tab", "Ctrl+Return", lambda: self.active.open_current(True))):
            tabs_menu.addAction(self._action(text, keys, slot))
        tabs_menu.addAction(self._action("Reopen Closed Tab", None, self.reopen_closed_tab))
        tabs_menu.addSeparator()
        tabs_menu.addAction(self._action("Save Tab Set As...", None, self.save_tab_set))
        self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu = (tabs_menu.addMenu("Open Tab Set"), tabs_menu.addMenu("Add Tab Set"),
                                                                          tabs_menu.addMenu("Forget Tab Set"))
        tabs_menu.aboutToShow.connect(lambda: self.build_tab_set_menus(self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu))
        self.build_tab_set_menus(self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu)
        go.addSeparator()
        drives = go.addMenu("Drives")                    # Go keeps to 16 entries: Parent Folder (card 51) made room here
        drives.addAction(self._action("Drives of Left Panel", "Alt+F1", lambda: self.left.open_drive_menu()))
        drives.addAction(self._action("Drives of Right Panel", "Alt+F2", lambda: self.right.open_drive_menu()))
        go.addAction(self._action("Eject This Drive", None, self.eject_current_drive))

    # Tools ----------------------------------------------------------------------------------------------------------------------
    def _build_tools_menu(self, tools) -> None:
        self._add_all(tools,
                      (self._action("Search...", ["Alt+F7", "Ctrl+F"], self.search_files),
                       self._action("Find Duplicate Files...", "Alt+Shift+F7", self.find_duplicate_files),
                       self._action("Check Folder Health...", None, self.check_folder_health)))
        tools.addSeparator()
        compare = tools.addMenu("Compare")
        compare.addAction(self._action("Folders and Synchronize...", "Alt+Shift+F8", self.compare_folders))
        compare.addAction(self._action("Two Files Under the Cursors", None, self.compare_files))
        rename_menu = tools.addMenu("Batch Rename")
        for text, keys, slot in (("By Pattern...", "Ctrl+M", self.rename_by_pattern),
                                 ("Search and Replace in Names...", None, self.rename_search_replace),
                                 ("Change Case...", None, self.rename_case),
                                 ("Number the Files...", None, self.rename_number)):
            rename_menu.addAction(self._action(text, keys, slot))
        archives = tools.addMenu("Archives")
        archives.addAction(self._action("Open as Archive", "Ctrl+PgDown", lambda: self.active.open_as_archive()))
        archives.addAction(self._action("Compress", None, self.compress_marked))
        archives.addAction(self._action("Extract Here", None, self.extract_here))
        archives.addAction(self._action("Pack to Zip...", "Alt+F5", self.pack_to_zip))
        archives.addAction(self._action("Unpack...", "Alt+F9", self.unpack_archive))
        archives.addAction(self._action("Convert Archive to Zip", None, self.convert_archive_to_zip))
        checksums = tools.addMenu("Checksums")
        checksums.addAction(self._action("Of Marked Files", None, self.show_checksums))
        checksums.addAction(self._action("Verify a Checksum File...", None, self.verify_checksum))
        quarantine = tools.addMenu("Quarantine")
        quarantine.addAction(self._action("Move to Quarantine...", None, self.move_to_quarantine))
        quarantine.addAction(self._action("Put Back", None, self.put_back_from_quarantine))
        quarantine.addAction(self._action("Show the Quarantine Folder", None, self.show_quarantine_folder))
        tools.addSeparator()
        operations = tools.addMenu("Operations")
        operations.addAction(self._action("Plan a Copy", None, self.plan_copy))                 # Shift+F5: onto the planned list
        operations.addAction(self._action("Plan a Move", None, self.plan_move))
        operations.addAction(self._action("Planned Operations...", None, self.show_planned))
        operations.addSeparator()
        operations.addAction(self._action("Pause or Resume Operations", "Ctrl+Shift+P", self.toggle_pause))
        operations.addAction(self._action("Cancel Waiting Operations", None, self.cancel_waiting))
        operations.addAction(self._action("Unfinished Operations...", None, lambda: self.offer_resume(manual=True)))
        operations.addAction(self._action("Export Log...", None, self.export_job_log))
        tools.addSeparator()
        for a in (self._action("Terminal Here", "Ctrl+Shift+T", self.open_terminal),
                  self._action("Administrator Terminal Here", None, self.open_admin_terminal),
                  self._action("SSH Terminal Here", None, self.open_ssh_terminal)):
            tools.addAction(a)
        command_line = tools.addMenu("Command Line")
        command_line.addAction(self._action("Go to Command Line", "Ctrl+E", self.focus_command_line))
        command_line.addAction(self._action("Name to Command Line", "Ctrl+J", self.put_in_command_line))
        command_line.addAction(self._action("Path to Command Line", "Ctrl+Shift+J", self.put_path_in_command_line))
        command_line.addAction(self._action("Command Line History...", None, lambda: (self.cmdline.setFocus(), self.show_command_history())))

    # Network --------------------------------------------------------------------------------------------------------------------
    def _build_network_menu(self, network) -> None:
        network.addAction(self._action("Add Server...", None, self.add_server))
        network.addAction(self._action("Disconnect This Panel's Server", None, self.disconnect_active_server))
        network.addSeparator()
        network.addAction(self._action("Add Network Share...", None, self.add_network_share))
        nfs_menu = network.addMenu("Client for NFS")
        self._nfs_status = nfs_menu.addAction(self.nfs_status_text())
        self._nfs_status.setEnabled(False)
        nfs_menu.aboutToShow.connect(lambda: self._nfs_status.setText(self.nfs_status_text()))
        nfs_menu.addAction(self._action("How to Switch On Client for NFS...", None, self.explain_nfs))
        self._share_separator = network.addSeparator()
        self.act_share_folder = self._action("Share This Folder...", None, self.share_this_folder)
        self.act_computer_shares = self._action("Shared Folders of a Computer...", None, self.show_computer_shares)
        network.addAction(self.act_share_folder)
        network.addAction(self.act_computer_shares)
        network.aboutToShow.connect(self._sync_network_menu)
        self._sync_network_menu()
        self.build_tailnet_menu(network)

    def _sync_network_menu(self) -> None:
        """The two sharing entries show only while Settings > Drives and Sharing > Allow Sharing Folders is on."""
        for act in (self._share_separator, self.act_share_folder, self.act_computer_shares):
            act.setVisible(self.sharing_allowed())

    # Settings -------------------------------------------------------------------------------------------------------------------
    def _build_settings_menu(self, settings) -> None:
        look = settings.addMenu("Appearance")
        scheme_menu = look.addMenu("Color Scheme")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.scheme_actions = {}
        for key, label in (("auto", "Follow System"), ("light", "Light"), ("dark", "Dark")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.theme.scheme == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_scheme(k))
            group.addAction(act)
            scheme_menu.addAction(act)
            self.scheme_actions[key] = act
        self.icon_menu = look.addMenu("Icon Set")
        self.icon_group = QActionGroup(self)
        self.icon_group.setExclusive(True)
        self.icon_set_actions = {}
        self.icon_menu.aboutToShow.connect(self._rebuild_icon_menu)   # picks up sets the user just added
        self._rebuild_icon_menu()
        look.addAction(self._action("Fonts and Bold...", None, self.open_look_settings))
        look.addAction(self._action("File Colours...", None, self.open_file_colors))
        look.addAction(self._action("Thumbnails...", None, self.open_thumbnail_settings))
        look.addAction(self._action("Picture Viewer Glass...", None, self.open_glass_settings))
        look.addAction(self._action("Frosted Background...", None, self.open_frost_settings))
        drive_menu = look.addMenu("Drive Selector")
        drive_group = QActionGroup(self)
        drive_group.setExclusive(True)
        self.drive_style_actions = {}
        wanted = str(self.settings.value("view/drive_selector", "menu"))
        for key, label in (("menu", "Dropdown in the Address Bar"), ("strip", "Button Strip Above the Panel")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(wanted == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_drive_style(k))
            drive_group.addAction(act)
            drive_menu.addAction(act)
            self.drive_style_actions[key] = act
        settings.addSeparator()
        settings.addAction(self._action("Copy and Move...", None, self.open_copy_settings))
        self.build_open_menu(settings)
        settings.addAction(self._action("Mouse Wheel...", None, self.open_wheel_settings))
        settings.addAction(self._action("Function Keys...", None, self.open_function_keys_settings))
        self.build_typing_menu(settings)
        self.add_auto_refresh_actions(settings)
        self.act_keep_place = QAction("Keep Cursor Position After Moving or Deleting", self)
        self.act_keep_place.setToolTip("On: the cursor goes to the next item. Off: back to the top of the folder")
        self.act_keep_place.setCheckable(True)
        self.act_keep_place.setChecked(self.keep_place_on())
        self.act_keep_place.toggled.connect(self.set_keep_place)
        settings.addAction(self.act_keep_place)
        self._apply_keep_place(self.keep_place_on())
        self.act_spring_open = QAction("Open Folders While Dragging Over Them", self)
        self.act_spring_open.setToolTip("Holding dragged files over a folder, a tab or a drive on the Home page for a moment opens it, "
                                        "so the drop can go deeper")
        self.act_spring_open.setCheckable(True)
        self.act_spring_open.setChecked(self.spring_open_on())
        self.act_spring_open.toggled.connect(self.set_spring_open)
        settings.addAction(self.act_spring_open)
        self._apply_spring_open(self.spring_open_on())
        self.add_git_actions(settings)
        drives_menu = settings.addMenu("Drives and Sharing")
        self.act_remember_drives = QAction("Remember Drives Between Sessions", self)
        self.act_remember_drives.setToolTip("To notice a different drive under the same letter")
        self.act_remember_drives.setCheckable(True)
        self.act_remember_drives.setChecked(self._remember_drives())
        self.act_remember_drives.toggled.connect(self.set_remember_drives)
        drives_menu.addAction(self.act_remember_drives)
        drives_menu.addAction(self._action("Forget Remembered Drives", None, self.forget_remembered_drives))
        drives_menu.addSeparator()
        self.act_allow_sharing = QAction("Allow Sharing Folders (Experimental)", self)
        self.act_allow_sharing.setCheckable(True)
        self.act_allow_sharing.setChecked(self.sharing_allowed())
        self.act_allow_sharing.toggled.connect(self.set_sharing_allowed)
        drives_menu.addAction(self.act_allow_sharing)
        self.build_linux_desktop_menu(settings)                  # Linux only: the launcher and "Open Folders with Dossier" (card 52A)
        settings.addSeparator()
        settings.addAction(self._action("Quarantine...", None, self.open_quarantine_settings))
        settings.addAction(self._action("Assistant Access...", None, self.open_assistant_settings))
        # these two hold the state of the choices the dialog (and the confirmation box) change; they are not in a menu
        self.act_verify = QAction("Verify Copies After Copying", self)
        self.act_verify.setCheckable(True)
        self.act_verify.setChecked(self.copy_settings()["verify"])
        self.act_verify.toggled.connect(lambda on: self.settings.setValue("copy/verify", "true" if on else "false"))
        self.act_ask_error = QAction("Ask When a File Cannot Be Copied", self)
        self.act_ask_error.setCheckable(True)
        self.act_ask_error.setChecked(self.copy_settings()["ask_on_error"])
        self.act_ask_error.toggled.connect(lambda on: self.settings.setValue("copy/ask_on_error", "true" if on else "false"))

    def keep_place_on(self) -> bool:
        """Settings > Keep Cursor Position After Moving or Deleting (the owner's option A, 2026-11-18). On by default."""
        return str(self.settings.value("panels/keep_place", "true")).lower() == "true"

    def set_keep_place(self, on: bool) -> None:
        self.settings.setValue("panels/keep_place", "true" if on else "false")
        self._apply_keep_place(on)
        self._say("After moving or deleting, the cursor goes to the next item" if on
                  else "After moving or deleting, the cursor goes to the top of the folder")

    def _apply_keep_place(self, on: bool) -> None:
        for panel in (self.left, self.right):
            panel.keep_place = on

    def spring_open_on(self) -> bool:
        """Settings > Open Folders While Dragging Over Them (card 62A). On by default."""
        return str(self.settings.value("panels/spring_open", "true")).lower() == "true"

    def set_spring_open(self, on: bool) -> None:
        self.settings.setValue("panels/spring_open", "true" if on else "false")
        self._apply_spring_open(on)
        self._say("Dragged files open the folder, tab or drive they are held over" if on
                  else "Dragged files no longer open what they are held over")

    def _apply_spring_open(self, on: bool) -> None:
        for panel in (self.left, self.right):
            panel.spring_open = on
            if not on:
                panel.spring.cancel()

    # Help -----------------------------------------------------------------------------------------------------------------------
    def open_web_page(self, url: str) -> None:
        """Open a page in the system's browser (a seam: the tests replace it, so no browser opens)."""
        QDesktopServices.openUrl(QUrl(url))

    def _build_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("Keyboard Shortcuts...", None, self.show_keys))
        self.act_palette = add_command_palette(self)            # Ctrl+K: type a few letters of any command (redactor_common)
        self.act_palette.setText("Command Palette...")
        help_menu.addAction(self.act_palette)
        help_menu.addSeparator()
        help_menu.addAction(self._action("Documentation (Online)", None, lambda: self.open_web_page(APP_REPO_URL)))
        help_menu.addAction(self._action("What's New (Online)", None, lambda: self.open_web_page(APP_REPO_URL + "/blob/main/CHANGELOG.md")))
        help_menu.addSeparator()
        help_menu.addAction(self._action("Check for Updates...", None, self.updates.check_now))
        self.act_daily_update = QAction("Check for Updates Once a Day", self)
        self.act_daily_update.setCheckable(True)
        self.act_daily_update.setToolTip("At start, at most once a day, ask GitHub whether a newer Dossier has been released. Nothing about you "
                                         "or your files is sent. Off unless you switch it on.")
        self.act_daily_update.setChecked(self.updates.settings.enabled)
        self.act_daily_update.toggled.connect(lambda on: self.updates.settings.update(check_for_updates=bool(on)))
        help_menu.addAction(self.act_daily_update)
        help_menu.addSeparator()
        slow_menu = help_menu.addMenu("Slowness Log")
        self.act_stall_log = QAction("Record Slow Moments (window stalls over 200 ms)", self)
        self.act_stall_log.setCheckable(True)
        self.act_stall_log.setChecked(str(self.settings.value("debug/stall_log", "false")).lower() == "true")
        self.act_stall_log.toggled.connect(self.set_stall_log)
        slow_menu.addAction(self.act_stall_log)
        slow_menu.addAction(self._action("Open the Slowness Log", None, self.open_stall_log))
        slow_menu.addAction(self._action("Delete the Slowness Log", None, self.delete_stall_log))
        error_menu = help_menu.addMenu("Error Log")
        self.act_error_log = QAction("Record Errors (failed copies, moves and deletes, network drops, errors in Dossier)", self)
        self.act_error_log.setCheckable(True)
        self.act_error_log.setToolTip("Write down what went wrong, with the file names and folders, in errors.log beside dossier.ini. "
                                      "Off unless you switch it on.")
        self.act_error_log.setChecked(str(self.settings.value("debug/error_log", "false")).lower() == "true")
        self.act_error_log.toggled.connect(self.set_error_log)
        error_menu.addAction(self.act_error_log)
        error_menu.addAction(self._action("Open the Error Log", None, self.open_error_log))
        error_menu.addAction(self._action("Delete the Error Log", None, self.delete_error_log))
        help_menu.addSeparator()
        help_menu.addAction(self._action(f"About {APP_NAME}...", None, self.about))
