"""Dossier in the Linux desktop (card 52A): the offer to add a launcher on the first start from the tarball, and Settings > Linux
Desktop (add the launcher, open folders with Dossier). The files are written by ``core/linux_desktop.py``; here is the window's side,
with every disk access on a thread."""
from __future__ import annotations

import json
from typing import Optional

from ..core import desktop_entries as D
from ..core import linux_desktop as L
from ..core.platform import IS_LINUX
from .background import run_in_background

OFFER_KEY = "linux/launcher_offered"
FOLDERS_KEY = "linux/folders_with_dossier"
BEFORE_KEY = "linux/folders_before"
HAD_BEFORE_KEY = "linux/folders_had_before"
DESKTOP_BEFORE_KEY = "linux/folders_desktop_before"   # JSON {path: value or null}, question 72A

OFFER_TEXT = ("Add Dossier to the application menu?" + chr(10) * 2 +
              "This puts a launcher and an icon in your own folders (under ~/.local/share). Nothing is installed for other users and "
              "nothing outside your home is touched." + chr(10) * 2 +
              "You can also do this later from Settings > Linux Desktop.")


def _true(value) -> bool:
    return str(value).lower() == "true"


class LinuxDesktopMixin:
    """Part of ``MainWindow``."""

    desktop_homes: Optional[tuple] = None       # tests put (data folder, config folder) here, so nothing real is written
    program_words: Optional[list] = None        # tests put the program's command words here
    icon_source: Optional[str] = None
    desktop_names: Optional[tuple] = None       # tests put the XDG_CURRENT_DESKTOP names here

    def _linux_folders(self) -> tuple:
        return self.desktop_homes or (L.data_home(), L.config_home())

    def _linux_command(self) -> list:
        return self.program_words or L.program_command()

    def _linux_icon(self) -> str:
        from .appicon import PNG
        return self.icon_source or PNG

    # the first start ------------------------------------------------------------------------------------------------------
    def linux_first_start(self, tarball: Optional[bool] = None, linux: bool = IS_LINUX) -> None:
        """On the first start from the Linux tarball, offer once to add the launcher; the answer, "no" too, is remembered. A copy run
        from source, and every other system, is never asked. ``tarball`` skips reading the ``update-channel`` file (tests)."""
        if not linux or _true(self.settings.value(OFFER_KEY, "false")):
            return

        def decide(is_tarball) -> None:
            if not is_tarball or _true(self.settings.value(OFFER_KEY, "false")):
                return
            self.settings.setValue(OFFER_KEY, "true")
            if self.dialogs.confirm("Application menu", OFFER_TEXT, "Add"):
                self.linux_add_launcher()

        if tarball is not None:
            decide(tarball)
            return
        run_in_background(self, self.cmd_runner, "Looking at how Dossier was installed", lambda progress, cancel: L.running_from_tarball(linux=True),
                          on_result=decide, tracked=self._size_jobs, indeterminate=True)

    # the launcher -------------------------------------------------------------------------------------------------------------
    def linux_add_launcher(self) -> None:
        """Settings > Linux Desktop > Add Dossier to the Application Menu: the launcher and the icon, in the user's own folders."""
        data, _config = self._linux_folders()
        command, icon = self._linux_command(), self._linux_icon()

        def work(progress, cancel):
            progress(0, 0)
            path = L.install_launcher(data, command, icon)
            L.refresh_menu_cache(data)
            return path

        run_in_background(self, self.cmd_runner, "Adding Dossier to the application menu", work,
                          on_result=lambda path: self._say(f"Dossier is in the application menu ({path})"), tracked=self._size_jobs,
                          indeterminate=True, failed_title="Application menu")

    # folders -------------------------------------------------------------------------------------------------------------------
    def open_folders_with_dossier(self) -> bool:
        return _true(self.settings.value(FOLDERS_KEY, "false"))

    def _sync_open_folders_action(self) -> None:
        act = getattr(self, "act_open_folders", None)
        if act is not None and act.isChecked() != self.open_folders_with_dossier():
            act.blockSignals(True)
            act.setChecked(self.open_folders_with_dossier())
            act.blockSignals(False)

    def set_open_folders_with_dossier(self, on: bool) -> None:
        """Settings > Linux Desktop > Open Folders with Dossier. On: Dossier is the default for folders in the user's own
        ``mimeapps.list`` (the launcher is added first when it is missing) and what the key said before is kept. Off: that is put
        back."""
        data, config = self._linux_folders()
        command, icon = self._linux_command(), self._linux_icon()
        before_raw = str(self.settings.value(BEFORE_KEY, ""))
        before = before_raw if _true(self.settings.value(HAD_BEFORE_KEY, "false")) else None
        desktops = self.desktop_names if self.desktop_names is not None else D.current_desktops()
        try:
            desktop_before = dict(json.loads(str(self.settings.value(DESKTOP_BEFORE_KEY, "") or "{}")))
        except (ValueError, TypeError):
            desktop_before = {}

        def switch_on(progress, cancel):
            progress(0, 0)
            if not L.is_installed(data):
                L.install_launcher(data, command, icon)
                L.refresh_menu_cache(data)
            try:
                fallback = tuple(D.parse_mimeapps(D.read_texts(D.mimeapps_files(
                    D.config_dirs(), D.data_dirs(), D.current_desktops()))).default.get(L.FOLDER_TYPE, []))
            except OSError:
                fallback = ()
            before_now = L.set_folder_default(config, fallback=fallback)
            # the desktop's own file wins over mimeapps.list: change it too where it names a folder program (question 72A)
            return before_now, L.set_desktop_folder_defaults(config, desktops)

        def switch_off(progress, cancel):
            progress(0, 0)
            restored = L.restore_desktop_folder_defaults(desktop_before)
            return L.restore_folder_default(config, before) or restored > 0

        def on_done(result) -> None:
            if on:
                result, desktop_changed = result
                self.settings.setValue(HAD_BEFORE_KEY, "false" if result is None else "true")
                self.settings.setValue(BEFORE_KEY, result or "")
                merged = dict(desktop_before)
                for path, value in desktop_changed.items():
                    merged.setdefault(path, value)                   # a second On keeps the first way back
                self.settings.setValue(DESKTOP_BEFORE_KEY, json.dumps(merged))
                self.settings.setValue(FOLDERS_KEY, "true")
                self._say("Folders now open with Dossier from other programs. Switch this off to go back.")
            else:
                self.settings.setValue(FOLDERS_KEY, "false")
                self.settings.setValue(DESKTOP_BEFORE_KEY, "{}")
                self._say("Folders open with the program they used before" if result else
                          "Folders were not changed: another program has been chosen for them since")
            self._sync_open_folders_action()

        run_in_background(self, self.cmd_runner, "Changing the program for folders", switch_on if on else switch_off, on_result=on_done,
                          tracked=self._size_jobs, indeterminate=True, failed_title="Open Folders with Dossier",
                          on_end=self._sync_open_folders_action)

    # the menu --------------------------------------------------------------------------------------------------------------------
    def build_linux_desktop_menu(self, settings, linux: bool = IS_LINUX):
        """The Settings > Linux Desktop submenu; nothing is added on Windows and the Mac. Returns the menu, or None."""
        if not linux:
            return None
        from PyQt6.QtGui import QAction
        menu = settings.addMenu("Linux Desktop")
        add = self._action("Add Dossier to the Application Menu", None, self.linux_add_launcher)
        add.setToolTip("A launcher and an icon in your own folders (~/.local/share), nothing system-wide")
        menu.addAction(add)
        self.act_open_folders = QAction("Open Folders with Dossier", self)
        self.act_open_folders.setToolTip("Other programs' \"Show in folder\" opens Dossier. Off puts back the program that was set before.")
        self.act_open_folders.setCheckable(True)
        self.act_open_folders.setChecked(self.open_folders_with_dossier())
        self.act_open_folders.toggled.connect(self.set_open_folders_with_dossier)
        menu.addAction(self.act_open_folders)
        return menu
