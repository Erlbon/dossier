"""The Tailnet section of the Home page: the devices of the owner's Tailscale network, read from the local ``tailscale`` program.

Nothing is scanned and nothing is changed: the list is what the local client already knows (``core/tailnet.py``). It is read on a thread
when the window opens and again, at most every half minute, when a panel shows the Home page. Enter on a device (or a right-click) adds it
as a saved server with its address filled in; the owner finishes the dialog. Without Tailscale there is no section.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QGuiApplication

from ..core import servers, tailnet
from ..core.home import TAILNET_PREFIX, TailnetItem

SETTING = "tailnet/show"
MIN_GAP = 30.0                  # seconds between two readings caused by showing the Home page
KINDS = (("sftp", "SFTP Server"), ("webdav", "WebDAV Server"), ("opds", "OPDS Book Catalogue"), ("subsonic", "Subsonic Music Server"))


class TailnetMixin:
    """Part of ``MainWindow``."""

    def build_tailnet(self) -> None:
        self._tailnet_items: list = []
        self._tailnet_read_at = 0.0
        self._tailnet_reading = False
        self._tailnet_again = False
        for panel in (self.left, self.right):
            panel.folder_changed.connect(lambda p: self.refresh_tailnet() if p.is_home else None)
        QTimer.singleShot(0, lambda: self.refresh_tailnet(force=True))

    def build_tailnet_menu(self, network_menu) -> None:
        self.act_tailnet = QAction("Show Tailnet Devices on the Home Page", self)
        self.act_tailnet.setCheckable(True)
        self.act_tailnet.setChecked(self.tailnet_enabled())
        self.act_tailnet.toggled.connect(self.set_tailnet_enabled)
        network_menu.addSeparator()
        network_menu.addAction(self.act_tailnet)

    def tailnet_enabled(self) -> bool:
        return str(self.settings.value(SETTING, "true")).lower() != "false"

    def set_tailnet_enabled(self, on: bool) -> None:
        self.settings.setValue(SETTING, "true" if on else "false")
        if on:
            self.refresh_tailnet(force=True)
        self._refresh_home_panels()

    def tailnet_items(self) -> list:
        return list(self._tailnet_items) if self.tailnet_enabled() else []

    def refresh_tailnet(self, force: bool = False) -> None:
        """Read the devices again on a thread (not more often than ``MIN_GAP`` seconds unless ``force``)."""
        if self._closing or not self.tailnet_enabled():
            return
        if self._tailnet_reading:
            self._tailnet_again = self._tailnet_again or force          # a reading is under way: a forced one follows it
            return
        if not force and time.monotonic() - self._tailnet_read_at < MIN_GAP:
            return
        self._tailnet_reading = True

        def work() -> None:
            devices = None
            try:
                devices = tailnet.read_devices()
            except Exception:                                  # noqa: BLE001 -- no Tailscale is not an error, whatever went wrong
                devices = None
            self.dispatcher(lambda: self._tailnet_loaded(devices))
        threading.Thread(target=work, daemon=True, name="dossier-tailnet").start()

    def _tailnet_loaded(self, devices: Optional[list]) -> None:
        self._tailnet_reading = False
        self._tailnet_read_at = time.monotonic()
        if self._closing:
            return
        again, self._tailnet_again = self._tailnet_again, False
        if again:
            self.refresh_tailnet(force=True)
        items = [TailnetItem(d.name, d.host, d.detail(), d.online) for d in (devices or [])]
        if items != self._tailnet_items:
            self._tailnet_items = items
            self._refresh_home_panels()

    def _refresh_home_panels(self) -> None:
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()

    # what a device can become ---------------------------------------------------------------------------------------------------------
    def tailnet_item(self, path: str) -> Optional[TailnetItem]:
        name = path[len(TAILNET_PREFIX):] if path.startswith(TAILNET_PREFIX) else path
        return next((i for i in self._tailnet_items if i.name == name), None)

    def add_tailnet_server(self, path: str, kind: str = "sftp") -> None:
        """Open the Add a Server dialog with this device's name and address in it."""
        item = self.tailnet_item(path)
        if item is None:
            self._say("This device is no longer in the list")
            return
        self.add_server(prefill=servers.Connection(item.name, item.host, "", servers.default_port(kind, True), kind))

    def copy_tailnet_address(self, path: str) -> None:
        item = self.tailnet_item(path)
        if item is not None:
            QGuiApplication.clipboard().setText(item.host)
            self._say(f"Copied {item.host}")
