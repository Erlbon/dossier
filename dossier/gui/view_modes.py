"""The view of a panel: Details or Thumbnails, the thumbnail size, how the list is arranged, and the thumbnail settings.

The mode and size belong to a panel and are remembered for it. The View menu shows the active panel's choice. The Home page always
shows details (it has no pictures to show).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from ..core.columns import index_of
from .thumbnails import SIZE_NAMES, STEPS, Thumbnails, nearest_step

ARRANGE = (("Name", "name"), ("Size", "size"), ("Date", "modified"), ("Type", "type"), ("Created", "created"),
           ("Last opened", "accessed"))


class ThumbnailSettingsDialog(QDialog):
    def __init__(self, parent, network: bool, video: bool, ffmpeg_found: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thumbnails")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Thumbnails are made on the side, only for what is on screen, and kept in memory while the program runs. "
                                "Nothing is written to disk."))
        self.network = QCheckBox("Also on network drives (every picture has to be read over the network)")
        self.network.setChecked(network)
        self.video = QCheckBox("A frame from videos" + ("" if ffmpeg_found else " (ffmpeg was not found, so this does nothing yet)"))
        self.video.setChecked(video)
        layout.addWidget(self.network)
        layout.addWidget(self.video)
        self.forget = QPushButton("Forget the thumbnails made so far")
        self.forget.setAutoDefault(False)
        layout.addWidget(self.forget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ViewModesMixin:
    """Part of ``MainWindow``."""

    def build_thumbnails(self) -> None:
        self.thumbs = Thumbnails(self)
        self.thumbs.on_network = str(self.settings.value("thumbs/network", "false")).lower() == "true"
        self.thumbs.video = str(self.settings.value("thumbs/video", "false")).lower() == "true"
        if self.thumbs.video:
            self.thumbs.ffmpeg = self._find_ffmpeg()
        for panel in (self.left, self.right):
            panel.model.thumbs = self.thumbs
            self.thumbs.ready.connect(panel.model.thumb_ready)
            panel.mode_changed.connect(self._panel_mode_changed)
        for name, panel in (("left", self.left), ("right", self.right)):
            mode = str(self.settings.value(f"view/mode_{name}", "details"))
            try:
                px = int(self.settings.value(f"view/size_{name}", 128))
            except (TypeError, ValueError):
                px = 128
            panel.set_view_mode(mode, px)

    def _find_ffmpeg(self) -> str:
        try:
            from redactor_common.core.tool_locator import find_tool
            found = find_tool("ffmpeg.exe")
            return str(found) if found else ""
        except Exception:   # noqa: BLE001 -- no ffmpeg, no video frames
            return ""

    # the menu --------------------------------------------------------------------------------------------------------------
    def add_view_mode_actions(self, view_menu, mode_group: QActionGroup) -> None:
        details = self.view_mode_actions["details"]
        details.setShortcut("Ctrl+1")
        details.triggered.connect(lambda: self.choose_mode("details"))
        icons = QAction("Thumbnails", self)
        icons.setCheckable(True)
        icons.setShortcut("Ctrl+2")
        icons.triggered.connect(lambda: self.choose_mode("icons"))
        mode_group.addAction(icons)
        view_menu.addAction(icons)
        self.view_mode_actions["icons"] = icons
        sizes = view_menu.addMenu("Thumbnail Size")
        size_group = QActionGroup(self)
        size_group.setExclusive(True)
        self.size_actions = {}
        for px in STEPS:
            act = QAction(f"{SIZE_NAMES[px]} ({px})", self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, p=px: self.choose_mode("icons", p))
            size_group.addAction(act)
            sizes.addAction(act)
            self.size_actions[px] = act
        arrange = view_menu.addMenu("Arrange By")
        arrange_group = QActionGroup(self)
        arrange_group.setExclusive(True)
        self.arrange_actions = {}
        for label, key in ARRANGE:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, k=key: self.arrange_by(k))
            arrange_group.addAction(act)
            arrange.addAction(act)
            self.arrange_actions[key] = act
        arrange.addSeparator()
        order_group = QActionGroup(self)
        order_group.setExclusive(True)
        self.order_actions = {}
        for label, desc in (("Ascending", False), ("Descending", True)):
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, d=desc: self.arrange_by(None, d))
            order_group.addAction(act)
            arrange.addAction(act)
            self.order_actions[desc] = act
        arrange.aboutToShow.connect(self.sync_mode_actions)

    def sync_mode_actions(self) -> None:
        panel = self.active
        mode = panel.view_mode if not panel.is_home else "details"
        for key, act in self.view_mode_actions.items():
            act.setChecked(key == mode)
        for px, act in self.size_actions.items():
            act.setChecked(px == nearest_step(panel.icon_px))
        header = panel.table.horizontalHeader()
        column = header.sortIndicatorSection()
        for key, act in self.arrange_actions.items():
            act.setChecked(index_of(key) == column)
        descending = header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        self.order_actions[descending].setChecked(True)

    # acting --------------------------------------------------------------------------------------------------------------------
    def choose_mode(self, mode: str, px: int = 0) -> None:
        self.active.set_view_mode(mode, px)

    def _panel_mode_changed(self, panel) -> None:
        name = "left" if panel is self.left else "right"
        if getattr(panel, "_applying_layout", False):            # a folder layout is being applied: not the owner's own choice
            pass
        elif self._mode_changed_in_rule(panel):                  # the folder has a layout: the change belongs to it
            pass
        else:
            self.settings.setValue(f"view/mode_{name}", panel.view_mode)
            self.settings.setValue(f"view/size_{name}", panel.icon_px)
        if panel is self.active:
            self.sync_mode_actions()

    def arrange_by(self, key=None, descending=None) -> None:
        """Sort the list of the active panel (the thumbnail view has no header to click)."""
        header = self.active.table.horizontalHeader()
        column = index_of(key) if key else header.sortIndicatorSection()
        if descending is None:
            descending = header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        self.active.table.sortByColumn(column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        self.sync_mode_actions()

    # settings ------------------------------------------------------------------------------------------------------------------
    def open_thumbnail_settings(self) -> None:
        dlg = ThumbnailSettingsDialog(self, self.thumbs.on_network, self.thumbs.video, bool(self._find_ffmpeg()))
        dlg.forget.clicked.connect(self.thumbs.clear)
        if not self._run_thumb_dialog(dlg):
            return
        self.thumbs.on_network, self.thumbs.video = dlg.network.isChecked(), dlg.video.isChecked()
        self.thumbs.ffmpeg = self._find_ffmpeg() if self.thumbs.video else ""
        self.settings.setValue("thumbs/network", "true" if self.thumbs.on_network else "false")
        self.settings.setValue("thumbs/video", "true" if self.thumbs.video else "false")
        self.thumbs.clear()                                   # pictures made under the old rules are not kept
        for panel in (self.left, self.right):
            panel.model.refresh_all()

    def _run_thumb_dialog(self, dlg) -> bool:                   # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted
