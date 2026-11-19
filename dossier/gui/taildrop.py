"""Taildrop in the window (card 64A): Send to Device in the right-click menu, and Files Waiting for You on the Home page.

Sending runs ``tailscale file cp`` for each marked file on a thread, with a box and Cancel. Receiving takes the waiting files into a new
hidden folder inside the folder you pick (``tailscale file get``, on a thread), then shows them as an ordinary move plan: the same
confirmation and the same questions about files that are already there (keep both, skip or replace), run as a normal operation. The
window's thread never starts the program and never touches the disk. The program is found and run through ``core/tailnet.py`` and
``core/taildrop.py``; ``taildrop_runner`` is the seam tests replace.
"""
from __future__ import annotations

import os
import tempfile
import threading

from PyQt6.QtWidgets import QMenu

from ..core import taildrop, tailnet
from ..core.ops import plan_move
from ..core.platform import KNOWN_FOLDERS, home_dir, user_folders
from .background import run_in_background

STAGING_PREFIX = ".dossier-taildrop-"


class TaildropMixin:
    """Part of ``MainWindow``."""

    taildrop_runner = staticmethod(taildrop.run_command)

    # sending ----------------------------------------------------------------------------------------------------------------------
    def add_send_to_device(self, menu: QMenu, panel, paths: list, row: int) -> None:
        """The Send to Device submenu of the right-click menu: the devices Taildrop can reach, the offline ones greyed. Nothing when
        there is no such device (Tailscale missing, or switched off on the Home page)."""
        devices = [i for i in self.tailnet_items() if i.receiver]
        if not devices:
            return
        sub = menu.addMenu("Send to Device")
        sub.setToolTipsVisible(True)
        for item in devices:
            action = self._entry_action(sub, item.name, lambda n=item.name: self.send_to_device(list(paths), n), panel, paths,
                                        enabled=item.online, row=row)
            action.setToolTip("Send the files with Taildrop" if item.online else f"{item.name} is offline: it can only get files while it is on")

    def send_to_device(self, paths: list, device_name: str) -> None:
        """Send the files to a device of the tailnet, on a thread, one file at a time."""
        item = next((i for i in self._tailnet_items if i.name == device_name), None)
        if item is None or not paths:
            self._say("This device is no longer in the list")
            return
        host = item.host or item.name
        current = {"name": ""}

        def work(progress, cancel):
            exe = tailnet.find_tailscale()
            if not exe:
                return None
            return taildrop.send_files(exe, paths, host, runner=self.taildrop_runner, cancel=cancel, progress=progress,
                                       on_file=lambda name: current.__setitem__("name", name))

        def done(results) -> None:
            if results is None:
                self.dialogs.info("Send to Device", "Tailscale was not found on this computer.")
                return
            self._say(taildrop.sent_summary(results, device_name))
            bad = taildrop.failure_text(results)
            if bad:
                self.dialogs.info("Send to Device", f"Some files were not sent to {device_name}:" + chr(10) * 2 + bad)

        run_in_background(self, self.cmd_runner, f"Sending to {device_name}", work, on_result=done, tracked=self._size_jobs,
                          detail=lambda: current["name"], failed_title="Send to Device")

    # receiving --------------------------------------------------------------------------------------------------------------------
    def receive_taildrop(self) -> None:
        """Home page > Fetch files sent to you: ask where to, take the files into a folder there, show the move, run it."""
        def find_default(progress, cancel):
            home = home_dir()
            keys = [k for k, _name in KNOWN_FOLDERS]
            path = user_folders(home)[keys.index("DOWNLOAD")][1]
            return path if os.path.isdir(path) else home

        def asked(default: str) -> None:
            folder = self.dialogs.ask_folder("Receive Taildrop Files", default)
            if folder:
                self._receive_into(folder)
        run_in_background(self, self.cmd_runner, "Receive Taildrop Files", find_default, on_result=asked, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Receive Taildrop Files")

    def _receive_into(self, dest: str) -> None:
        def work(progress, cancel):
            exe = tailnet.find_tailscale()
            if not exe:
                return None
            staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=dest)
            found = taildrop.receive_files(exe, staging, runner=self.taildrop_runner, cancel=cancel)
            if not found.files:
                try:
                    os.rmdir(staging)
                except OSError:
                    pass
            return staging, found

        def done(result) -> None:
            if result is None:
                self.dialogs.info("Receive Taildrop Files", "Tailscale was not found on this computer.")
                return
            staging, found = result
            if not found.ok and not found.files:
                self.dialogs.info("Receive Taildrop Files", found.message)
                return
            if not found.files:
                self.dialogs.info("Receive Taildrop Files", "No files are waiting for you.")
                return
            if not found.ok:
                self.dialogs.info("Receive Taildrop Files", "Tailscale reported a problem, so some files may be missing:" + chr(10) * 2 + found.message)
            self._place_received(staging, found.files, dest)

        run_in_background(self, self.cmd_runner, "Receiving files", work, on_result=done, tracked=self._size_jobs, indeterminate=True,
                          failed_title="Receive Taildrop Files")

    def _place_received(self, staging: str, names: list, dest: str) -> None:
        """The files are in ``staging``: plan the move into ``dest`` on a thread, show it, ask about clashes, run it."""
        staged = [self.fs.join(staging, n) for n in names]

        def build(watch):
            return plan_move(self.fs, staged, dest, watch=watch)

        def left_in_place(why: str) -> None:
            self.dialogs.info("Receive Taildrop Files", f"{why} The files are in {staging}")

        def then(plan) -> None:
            text = self._summary(plan, dest, staged, "Taildrop") + chr(10) * 2 + "Files with the same name as one already there are asked about; none is replaced without your say."
            if not self.dialogs.confirm("Receive Taildrop Files", text, "Receive"):
                left_in_place("Nothing was moved.")
                return
            settled = self._settle(plan)
            if settled is None:
                left_in_place("Nothing was moved.")
                return
            self._run(settled, on_done=lambda _job: self._remove_staging(staging))

        self._plan_in_background("Preparing the move", build, then)

    @staticmethod
    def _remove_staging(staging: str) -> None:
        """The hidden folder is empty once everything moved out of it; a folder that still holds files stays (they were skipped)."""
        def work() -> None:
            try:
                os.rmdir(staging)
            except OSError:
                pass
        threading.Thread(target=work, daemon=True, name="dossier-taildrop-clean").start()
