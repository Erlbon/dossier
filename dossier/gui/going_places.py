"""Going places: the folder history, the hotlist, and opening a folder in the other panel."""
from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu


class GoingPlacesMixin:
    """Part of ``MainWindow``."""

    def _popup_at_address(self, menu: QMenu) -> None:
        bar = self.active.address_bar
        menu.popup(bar.mapToGlobal(QPoint(0, bar.height())))

    def build_history_menu(self) -> QMenu:
        """The folders the active panel's tab has shown, newest first; the one it stands on is ticked."""
        panel = self.active
        menu = QMenu(self)
        entries = panel.history_entries()
        if not entries:
            menu.addAction("No folders yet").setEnabled(False)
        for index, path in entries[:30]:
            label = path if len(path) <= 70 else path[:30] + "..." + path[-37:]
            act = menu.addAction(label.replace("&", "&&"))
            act.setData(path)
            act.setToolTip(path)
            act.setCheckable(True)
            act.setChecked(index == panel.history_position)
            act.triggered.connect(lambda _c=False, i=index: panel.history_go(i))
        return menu

    def show_history(self) -> None:
        self._history_menu = self.build_history_menu()
        self._popup_at_address(self._history_menu)

    def build_hotlist_menu(self) -> QMenu:
        """The pinned folders, numbered so a digit picks one, and the way to pin another."""
        panel = self.active
        menu = QMenu(self)
        pins = self._saved_list("home/pins")
        if not pins:
            menu.addAction("No pinned folders yet").setEnabled(False)
        for n, path in enumerate(pins[:9], start=1):
            name = self.fs.basename(path.rstrip(chr(92) + "/")) or path
            act = menu.addAction(f"&{n}  {name}".replace("&&", "&"))
            act.setToolTip(path)
            act.triggered.connect(lambda _c=False, p=path: self._go_to_pin(panel, p))
        menu.addSeparator()
        menu.addAction("Pin This Folder (Ctrl+D)").triggered.connect(lambda _c=False: self.pin_folder())
        return menu

    def _go_to_pin(self, panel, path: str) -> None:
        if not panel.set_folder(path):
            self._say(f"Cannot open {path}")

    def show_hotlist(self) -> None:
        if self.active.is_home:
            self._say("Open a folder first")
            return
        self._hotlist_menu = self.build_hotlist_menu()
        self._popup_at_address(self._hotlist_menu)

    def open_in_other_panel(self) -> None:
        """Ctrl+Left or Ctrl+Right: the other panel opens the folder under the cursor (the folder itself when the
        cursor is on a file)."""
        panel = self.active
        if panel.is_home:
            return
        entry = panel.current_entry()
        target = entry.path if entry is not None and entry.is_dir else panel.path
        self.other.set_folder(target)
        self._say(f"The other panel shows {target}")

    def same_in_other_panel(self) -> None:
        if self.active.is_home:
            return
        self.other.set_folder(self.active.path)
        self._say(f"The other panel shows {self.active.path}")

    # which drive each letter held (opt-in: off by default, stored only when switched on) ------------------------------
    def _remember_drives(self) -> bool:
        return str(self.settings.value("home/remember_drives", "false")).lower() == "true"

    def _load_seen_drives(self) -> dict:
        out = {}
        for line in self._saved_list("home/seen_drives"):
            root, _sep, identity = line.partition("=")
            if root and identity:
                out[root] = identity
        return out

    def _save_seen_drives(self, seen: dict) -> None:
        if seen:
            self.settings.setValue("home/seen_drives", [f"{r}={i}" for r, i in sorted(seen.items())])
        else:
            self.settings.remove("home/seen_drives")

    def set_remember_drives(self, on: bool) -> None:
        self.settings.setValue("home/remember_drives", "true" if on else "false")
        if not on:
            self.settings.remove("home/seen_drives")           # switching it off also deletes what was kept
        self._say("Drives are remembered between sessions" if on else "Remembered drives deleted; drives are only compared within one session")

    def forget_remembered_drives(self) -> None:
        self.home_provider.memory.forget()
        self._say("Remembered drives deleted")
