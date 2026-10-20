"""The drive selector, in two looks the user can switch between (View > Drive Selector):

* menu  - a chip left of the address bar that opens a list of drives with free space (default)
* strip - one button per drive above the panel

Alt+F1 and Alt+F2 open the list for the left and right panel in either look. The list is built
without touching the disks; free space arrives a moment later from background threads, so a
dead network drive can never freeze the window.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from ..core.drives import Drive, drive_of, list_drives, usage_async
from ..core.filetypes import DRIVE_ICONS
from . import icon_set, look, theme
from .models import human_size

STYLES = ("menu", "strip")


class DriveBar(QObject):
    chosen = pyqtSignal(object)    # a Drive

    def __init__(self, dispatch: Optional[Callable] = None, parent=None) -> None:
        super().__init__(parent)
        self._dispatch = dispatch
        self.drives: list = []
        self.current: Optional[Drive] = None
        self.style = "menu"
        self._free: dict = {}
        self._chip_color: Optional[str] = None

        self.strip = QWidget()
        self.strip.setObjectName("drivestrip")
        self._strip_row = QHBoxLayout(self.strip)
        self._strip_row.setContentsMargins(4, 3, 4, 3)
        self._strip_row.setSpacing(4)

        self.chip = QToolButton()
        self.chip.setObjectName("drivechip")
        self.chip.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.chip.setToolTip("Change drive (Alt+F1 left panel, Alt+F2 right panel)")
        self.menu = QMenu(self.chip)
        self.menu.aboutToShow.connect(self.reload)
        self.chip.setMenu(self.menu)

        self.reload()
        self.set_style("menu")
        self.restyle()

    # look -------------------------------------------------------------------------------
    def set_style(self, style: str) -> None:
        self.style = style if style in STYLES else "menu"
        self.strip.setVisible(self.style == "strip")
        self.chip.setVisible(self.style == "menu")

    def restyle(self) -> None:
        t = theme.current()
        self.strip.setStyleSheet(
            f"#drivestrip{{background:{t['card']};border-bottom:1px solid {t['line']};}}"
            f"#drivestrip QPushButton{{border:1px solid {t['line']};border-radius:6px;padding:2px 8px;"
            f"color:{t['dim']};background:transparent;}}"
            f"#drivestrip QPushButton:checked{{background:{t['accent']};color:{t['accent_fg']};"
            f"border-color:{t['accent']};font-weight:{look.weight()};}}")
        self._rebuild_menu()
        self._refresh_current()

    # content ------------------------------------------------------------------------------
    def reload(self) -> None:
        """List the drives again (cheap) and ask for their free space (in the background)."""
        self.drives = list_drives()
        while self._strip_row.count():
            item = self._strip_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._strip_buttons: dict = {}
        for d in self.drives:
            b = QPushButton(d.name)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, drive=d: self.chosen.emit(drive))
            self._strip_row.addWidget(b)
            self._strip_buttons[d.path] = b
        self._strip_row.addStretch(1)
        self._rebuild_menu()
        self._refresh_current()
        usage_async([d.path for d in self.drives], self._usage_from_thread)

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        self._menu_actions: dict = {}
        for d in self.drives:
            act = self.menu.addAction(icon_set.icon(DRIVE_ICONS.get(d.kind, 'database'), theme.current()['fg']),
                                      self._menu_text(d))
            act.triggered.connect(lambda _c=False, drive=d: self.chosen.emit(drive))
            self._menu_actions[d.path] = act

    def _menu_text(self, d: Drive) -> str:
        free = self._free.get(d.path)
        return f"{d.title}\t{human_size(free[1])} free" if free else d.title

    def _usage_from_thread(self, path: str, usage) -> None:
        def apply() -> None:
            if usage:
                self._free[path] = usage
            act = self._menu_actions.get(path)
            if act is not None and usage:
                act.setText(self._menu_text(next(d for d in self.drives if d.path == path)))
            btn = self._strip_buttons.get(path)
            if btn is not None and usage:
                btn.setToolTip(f"{human_size(usage[1])} free of {human_size(usage[0])}")

        if self._dispatch is not None:
            self._dispatch(apply)

    # state ---------------------------------------------------------------------------------
    def set_current_path(self, path: str) -> None:
        self.current = drive_of(path, self.drives)
        self._refresh_current()

    def set_chip_color(self, color: Optional[str]) -> None:
        """The chip sits on the address bar, which is solid gold when its panel is active."""
        self._chip_color = color
        self._refresh_current()

    def _refresh_current(self) -> None:
        cur = self.current
        t = theme.current()
        self.chip.setText(cur.name if cur else "Drive")
        kind = DRIVE_ICONS.get(cur.kind, "database") if cur else "device-desktop"
        self.chip.setIcon(icon_set.icon(kind, self._chip_color or t["dim"]))
        for d in self.drives:
            b = self._strip_buttons.get(d.path)
            if b is None:
                continue
            on = cur is not None and cur.path == d.path
            b.setChecked(on)
            b.setIcon(icon_set.icon(DRIVE_ICONS.get(d.kind, "database"), t["accent_fg"] if on else t["dim"]))

    def open_menu(self) -> None:
        """Open the drive list (Alt+F1 / Alt+F2), under whichever look is shown."""
        anchor = self.chip if self.style == "menu" else self.strip
        self.menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height())))
