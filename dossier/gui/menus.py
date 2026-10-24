"""The menu bar: Files, Edit, Mark, View, Go, Tools, Network, Settings, Help.

Each menu answers one question. Files: what can I do to the files under the cursor. Edit: undo and the clipboard. Mark: which files are
marked. View: how a folder is shown. Go: where am I, and where to next. Tools: the bigger jobs (search, compare, rename, archives,
checksums, terminals). Network: servers, shares and network drives. Settings: how Dossier looks (Appearance) and behaves. Help: About
and the slowness log. Every command keeps its shortcut wherever it lives.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction, QActionGroup, QKeySequence

from ..core.version import APP_NAME


class MenusMixin:
    """Part of ``MainWindow``."""

    def _action(self, text: str, keys, slot) -> QAction:
        act = QAction(text, self)
        if keys:
            act.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
        act.triggered.connect(lambda _checked=False: slot())
        self.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        self._build_files_menu(bar.addMenu("&Files"))
        self._build_edit_menu(bar.addMenu("&Edit"))
        self._build_mark_menu(bar.addMenu("&Mark"))
        self._build_view_menu(bar.addMenu("&View"))
        self._build_go_menu(bar.addMenu("&Go"))
        self._build_tools_menu(bar.addMenu("&Tools"))
        self._build_network_menu(bar.addMenu("&Network"))
        self._build_settings_menu(bar.addMenu("&Settings"))
        self._build_help_menu()

    # Files ----------------------------------------------------------------------------------------------------------------------
    def _build_files_menu(self, files) -> None:
        self.act_view = self._action("View", "F3", self.view_file)
        self.act_edit = self._action("Edit", "F4", self.edit_file)
        self.act_rename = self._action("Rename", "F2", self.rename)
        self.act_copy = self._action("Copy to Other Panel", "F5", self.copy)
        self.act_move = self._action("Move to Other Panel", "F6", self.move)
        self.act_mkdir = self._action("New Folder", "F7", self.new_folder)
        self.act_delete = self._action("Delete", ["F8", "Delete"], self.delete)
        self.act_delete_perm = self._action("Delete Permanently", "Shift+F8", lambda: self.delete(permanent=True))
        self.act_properties = self._action("Properties", "Alt+Return", self.show_properties)
        quit_ = self._action("Quit", "Ctrl+Q", self.close)
        for a in (self.act_view, self.act_edit, self.act_rename, self.act_copy, self.act_move, self.act_mkdir, self.act_delete,
                  self.act_delete_perm):
            files.addAction(a)
        files.addSeparator()
        files.addAction(self.act_properties)
        files.addSeparator()
        files.addAction(quit_)

    # Edit -----------------------------------------------------------------------------------------------------------------------
    def _build_edit_menu(self, edit) -> None:
        edit.addAction(self._action("Undo", "Ctrl+Z", self.undo))
        edit.addSeparator()
        for a in (self._action("Copy Files to Clipboard", "Ctrl+C", self.clip_copy),
                  self._action("Cut Files to Clipboard", "Ctrl+X", self.clip_cut),
                  self._action("Paste Files Here", "Ctrl+V", self.clip_paste)):
            edit.addAction(a)
        edit.addAction(self._action("Paste Picture or Text as New File...", "Ctrl+Shift+V", self.paste_as_new_file))
        edit.addSeparator()
        edit.addAction(self._action("Copy Marked Paths as Text", None, self.copy_marked_paths))

    # Mark -----------------------------------------------------------------------------------------------------------------------
    def _build_mark_menu(self, mark) -> None:
        for a in (self._action("Select All", "Ctrl+A", self.select_all),
                  self._action("Mark by Pattern...", "Ctrl+F", self.mark_by_pattern),
                  self._action("Unmark by Pattern...", "Ctrl+Shift+F", lambda: self.mark_by_pattern(False)),
                  self._action("Invert Selection", "*", self.invert_selection),
                  self._action("Deselect All", "Ctrl+Shift+A", self.selection.clear)):
            mark.addAction(a)
        mark.addSeparator()
        mark.addAction(self._action("Mark by Tag...", None, self.mark_by_tag))
        mark.addAction(self._action("Unmark by Tag...", None, lambda: self.mark_by_tag(False)))
        mark.addSeparator()
        saved = mark.addMenu("Saved Selections")
        saved.addAction(self._action("Save Selection As...", None, self.save_selection))
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
        self.add_view_mode_actions(view_menu, mode_group)
        self.add_layout_actions(view_menu)
        view_menu.addSeparator()
        self.act_notes = QAction("Folder Notes", self)
        self.act_notes.setCheckable(True)
        self.act_notes.setChecked(str(self.settings.value("view/notes", "true")).lower() != "false")
        self.act_notes.toggled.connect(self.set_notes_visible)
        view_menu.addAction(self.act_notes)
        self.act_tools_bar = QAction("Tools Bar", self)
        self.act_tools_bar.setCheckable(True)
        self.act_tools_bar.setChecked(self.tools_bar.isVisibleTo(self))
        self.act_tools_bar.toggled.connect(self.set_tools_bar_visible)
        view_menu.addAction(self.act_tools_bar)
        self.build_bar_place_menus(view_menu)
        tabs_menu = view_menu.addMenu("Tabs")
        for text, keys, slot in (("New Tab", "Ctrl+T", lambda: self.active.new_tab()),
                                 ("Close Tab", "Ctrl+W", lambda: self.active.close_tab(self.active.tabs.currentIndex())),
                                 ("Next Tab", "Ctrl+Tab", lambda: self.active.next_tab(1)),
                                 ("Previous Tab", "Ctrl+Shift+Tab", lambda: self.active.next_tab(-1)),
                                 ("Open Folder in New Tab", "Ctrl+Return", lambda: self.active.open_current(True))):
            tabs_menu.addAction(self._action(text, keys, slot))
        tabs_menu.addSeparator()
        tabs_menu.addAction(self._action("Save Tab Set As...", None, self.save_tab_set))
        self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu = (tabs_menu.addMenu("Open Tab Set"), tabs_menu.addMenu("Add Tab Set"),
                                                                          tabs_menu.addMenu("Forget Tab Set"))
        tabs_menu.aboutToShow.connect(lambda: self.build_tab_set_menus(self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu))
        self.build_tab_set_menus(self._tab_open_menu, self._tab_add_menu, self._tab_forget_menu)
        view_menu.addSeparator()
        view_menu.addAction(self._action("Quick Filter", "Ctrl+S", lambda: self.active.start_filter()))
        view_menu.addAction(self._action("Folder Sizes", "Alt+Shift+Return", lambda: self.calculate_folder_sizes()))
        view_menu.addAction(self._action("Refresh", "Ctrl+R", self.refresh))

    # Go -------------------------------------------------------------------------------------------------------------------------
    def _build_go_menu(self, go) -> None:
        self.act_back = self._action("Back", "Alt+Left", lambda: self.active.history_back())
        self.act_forward = self._action("Forward", "Alt+Right", lambda: self.active.history_forward())
        for a in (self.act_back, self.act_forward,
                  self._action("Folder History...", "Alt+Down", self.show_history),
                  self._action("Hotlist...", "Ctrl+B", self.show_hotlist)):
            go.addAction(a)
        go.addSeparator()
        go.addAction(self._action("Home Page", "Alt+Home", lambda: self.active.go_home()))
        go.addAction(self._action("Edit the Path", "Ctrl+L", lambda: self.active.address_bar.start_edit()))
        go.addAction(self._action("Pin Folder to Home Page", "Ctrl+D", self.pin_folder))
        go.addAction(self._action("Quarantine Folder", None, self.show_quarantine_folder))
        go.addSeparator()
        for a in (self._action("All Files Below This Folder", "Ctrl+Shift+B", self.show_all_files_below),
                  self._action("Open Folder in the Other Panel", ["Ctrl+Right", "Ctrl+Left"], self.open_in_other_panel),
                  self._action("Other Panel Shows This Folder", "Ctrl+Shift+O", self.same_in_other_panel),
                  self._action("Swap Panels", "Ctrl+U", self.swap_panels)):
            go.addAction(a)

    # Tools ----------------------------------------------------------------------------------------------------------------------
    def _build_tools_menu(self, tools) -> None:
        tools.addAction(self._action("Search...", "Alt+F7", self.search_files))
        tools.addAction(self._action("Find Duplicate Files...", "Alt+Shift+F7", self.find_duplicate_files))
        tools.addAction(self._action("Check Folder Health...", None, self.check_folder_health))
        tools.addAction(self._action("Compare Folders and Synchronize...", "Alt+Shift+F8", self.compare_folders))
        tools.addAction(self._action("Compare the Two Current Files", None, self.compare_files))
        tools.addSeparator()
        rename_menu = tools.addMenu("Batch Rename")
        for text, keys, slot in (("By Pattern...", "Ctrl+M", self.rename_by_pattern),
                                 ("Search and Replace in Names...", None, self.rename_search_replace),
                                 ("Change Case...", None, self.rename_case),
                                 ("Number the Files...", None, self.rename_number)):
            rename_menu.addAction(self._action(text, keys, slot))
        archives = tools.addMenu("Archives")
        archives.addAction(self._action("Open as Archive", "Ctrl+PgDown", lambda: self.active.open_as_archive()))
        archives.addAction(self._action("Pack to Zip...", "Alt+F5", self.pack_to_zip))
        archives.addAction(self._action("Unpack...", "Alt+F9", self.unpack_archive))
        archives.addAction(self._action("Convert Archive to Zip", None, self.convert_archive_to_zip))
        tools.addAction(self._action("Change Dates and Attributes...", None, self.change_dates))
        tools.addAction(self._action("New Link...", None, self.new_link))
        tools.addAction(self._action("Move to Quarantine...", None, self.move_to_quarantine))
        tools.addAction(self._action("Put Back from Quarantine", None, self.put_back_from_quarantine))
        tools.addAction(self._action("Checksums of Marked Files", None, self.show_checksums))
        tools.addAction(self._action("Verify Checksum...", None, self.verify_checksum))
        tools.addAction(self._action("Edit Folder Note", "Ctrl+Shift+E", self.edit_folder_note))
        tools.addAction(self._action("Command Line History...", None, lambda: (self.cmdline.setFocus(), self.show_command_history())))
        tools.addSeparator()
        operations = tools.addMenu("Operations")
        operations.addAction(self._action("Pause or Resume Operations", "Ctrl+Shift+P", self.toggle_pause))
        operations.addAction(self._action("Cancel Waiting Operations", None, self.cancel_waiting))
        operations.addAction(self._action("Unfinished Operations...", None, lambda: self.offer_resume(manual=True)))
        tools.addSeparator()
        for a in (self._action("Terminal Here", "Ctrl+Shift+T", self.open_terminal),
                  self._action("Administrator Terminal Here", None, lambda: self.open_terminal(admin=True))):
            tools.addAction(a)

    # Network --------------------------------------------------------------------------------------------------------------------
    def _build_network_menu(self, network) -> None:
        network.addAction(self._action("Add a Server...", None, self.add_server))
        network.addAction(self._action("Disconnect from the Server of This Panel", None, self.disconnect_active_server))
        network.addSeparator()
        network.addAction(self._action("Add Network Share...", None, self.add_network_share))
        net_menu = network.addMenu("Network Drives")
        self._nfs_status = net_menu.addAction(self.nfs_status_text())
        self._nfs_status.setEnabled(False)
        net_menu.aboutToShow.connect(lambda: self._nfs_status.setText(self.nfs_status_text()))
        net_menu.addAction(self._action("How to Switch On Client for NFS...", None, self.explain_nfs))
        self.build_tailnet_menu(network)

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
        look.addAction(self._action("Thumbnails...", None, self.open_thumbnail_settings))
        columns_menu = look.addMenu("Columns")
        columns_menu.addAction(self._action("Add or Remove Columns...", None, self.open_column_settings))
        columns_menu.addAction(self._action("Back to the Default Columns", None, self.reset_columns))
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
        self._action("Drives of Left Panel", "Alt+F1", lambda: self.left.open_drive_menu())
        self._action("Drives of Right Panel", "Alt+F2", lambda: self.right.open_drive_menu())
        settings.addSeparator()
        settings.addAction(self._action("Copy and Move...", None, self.open_copy_settings))
        settings.addAction(self._action("Quarantine...", None, self.open_quarantine_settings))
        self.build_open_menu(settings)
        settings.addAction(self._action("Mouse Wheel...", None, self.open_wheel_settings))
        drives_menu = settings.addMenu("Drive Memory")
        self.act_remember_drives = QAction("Remember Drives Between Sessions (to notice a different drive under a letter)", self)
        self.act_remember_drives.setCheckable(True)
        self.act_remember_drives.setChecked(self._remember_drives())
        self.act_remember_drives.toggled.connect(self.set_remember_drives)
        drives_menu.addAction(self.act_remember_drives)
        drives_menu.addAction(self._action("Forget Remembered Drives", None, self.forget_remembered_drives))
        settings.addSeparator()
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

    # Help -----------------------------------------------------------------------------------------------------------------------
    def _build_help_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")
        slow_menu = help_menu.addMenu("Slowness Log")
        self.act_stall_log = QAction("Record Slow Moments (window stalls over 200 ms)", self)
        self.act_stall_log.setCheckable(True)
        self.act_stall_log.setChecked(str(self.settings.value("debug/stall_log", "false")).lower() == "true")
        self.act_stall_log.toggled.connect(self.set_stall_log)
        slow_menu.addAction(self.act_stall_log)
        slow_menu.addAction(self._action("Open the Log", None, self.open_stall_log))
        slow_menu.addAction(self._action("Delete the Log", None, self.delete_stall_log))
        help_menu.addSeparator()
        help_menu.addAction(self._action(f"About {APP_NAME}...", None, self.about))
