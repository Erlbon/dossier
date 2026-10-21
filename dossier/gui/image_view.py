"""The picture view of the F3 viewer: fit to the window or zoom, turn, and an information panel with the EXIF of a photo.

The picture is decoded on a thread by the window (``read_image``); this file only shows it. Zoom: ``+`` and ``-`` or Ctrl+wheel, ``0`` fits
the window, the wheel steps to the next or previous picture, ``1`` shows every pixel, double-click toggles between the two; ``L`` and ``R`` turn the picture a quarter (the file is
never changed); dragging moves a zoomed picture. A photo taken upright but stored sideways is turned by its EXIF orientation when it is
read.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap, QTransform
from PyQt6.QtWidgets import (QAbstractItemView, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHeaderView, QSplitter,
                             QTreeWidget, QTreeWidgetItem, QWidget)

from ..core.exif import Exif
from . import theme

MIN_ZOOM, MAX_ZOOM = 0.02, 32.0


def read_image(path: str) -> QImage:
    """Decode a picture file (upright by its EXIF orientation). Safe on a worker thread; a null image when it cannot be read."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    return reader.read()


class ImageView(QGraphicsView):
    changed = pyqtSignal()
    step_requested = pyqtSignal(int)                    # the wheel asks for the next (1) or previous (-1) picture

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._wheel_steps = 0
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: Optional[QGraphicsPixmapItem] = None
        self._image: Optional[QImage] = None
        self._turn = 0                                   # quarter turns clockwise, by the owner
        self._fit = True
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.restyle()

    def restyle(self) -> None:
        self.setBackgroundBrush(QColor(theme.current()["bg"]))

    # the picture ------------------------------------------------------------------------------------------------------------------
    def set_image(self, image: Optional[QImage]) -> None:
        self._scene.clear()
        self._item = None
        self._image = image if image is not None and not image.isNull() else None
        self._turn = 0
        if self._image is not None:
            self._show()
            self.fit()
        self.changed.emit()

    def has_image(self) -> bool:
        return self._image is not None

    def image_size(self) -> tuple:
        return (self._image.width(), self._image.height()) if self._image is not None else (0, 0)

    def _show(self) -> None:
        image = self._image
        if self._turn:
            image = image.transformed(QTransform().rotate(90 * self._turn), Qt.TransformationMode.SmoothTransformation)
        self._scene.clear()
        self._item = self._scene.addPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(QRectF(self._item.boundingRect()))

    # zoom and turn ----------------------------------------------------------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def fit(self) -> None:
        """Show the whole picture in the window (never bigger than it is)."""
        if self._item is None:
            return
        self._fit = True
        self.resetTransform()
        view, pic = self.viewport().size(), self._item.boundingRect()
        if pic.width() > 0 and pic.height() > 0:
            scale = min(view.width() / pic.width(), view.height() / pic.height(), 1.0)
            self.scale(scale, scale)
        self.centerOn(self._item)
        self.changed.emit()

    def actual_size(self) -> None:
        if self._item is None:
            return
        self._fit = False
        self.resetTransform()
        self.changed.emit()

    def zoom_by(self, factor: float) -> None:
        if self._item is None:
            return
        target = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self._fit = False
        self.scale(target / self.zoom, target / self.zoom)
        self.changed.emit()

    def turn(self, quarters: int) -> None:
        if self._image is None:
            return
        self._turn = (self._turn + quarters) % 4
        was_fit = self._fit
        self._show()
        if was_fit:
            self.fit()
        else:
            self.centerOn(self._item)
        self.changed.emit()

    def toggle_fit(self) -> None:
        self.actual_size() if self._fit else self.fit()

    # events -------------------------------------------------------------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self.fit()

    def wheelEvent(self, event) -> None:
        """Wheel: the next or previous picture of the folder. Ctrl+wheel zooms; Shift+wheel moves a zoomed picture."""
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.25 if event.angleDelta().y() > 0 else 0.8)
            event.accept()
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            super().wheelEvent(event)
        else:
            self._wheel_steps += event.angleDelta().y()          # a notch is 120; a touchpad sends many small ones
            while abs(self._wheel_steps) >= 120:
                self.step_requested.emit(-1 if self._wheel_steps > 0 else 1)
                self._wheel_steps -= 120 if self._wheel_steps > 0 else -120
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_fit()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.25)
        elif key == Qt.Key.Key_Minus:
            self.zoom_by(0.8)
        elif key == Qt.Key.Key_0:
            self.fit()
        elif key == Qt.Key.Key_1:
            self.actual_size()
        elif key == Qt.Key.Key_R:
            self.turn(1)
        elif key == Qt.Key.Key_L:
            self.turn(-1)
        else:
            super().keyPressEvent(event)


class InfoPanel(QTreeWidget):
    """The facts of the picture file and, for a photo, its EXIF, in groups."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.setMinimumWidth(260)

    def show_info(self, facts: list, exif: Optional[Exif]) -> None:
        """``facts`` are ``(label, text)`` pairs (name, size, dimensions...); ``exif`` is what the photo itself says (or None)."""
        self.clear()
        top = QTreeWidgetItem(self, ["File"])
        for label, text in facts:
            QTreeWidgetItem(top, [label, text])
        top.setExpanded(True)
        if exif is not None and exif.fields:
            groups: dict = {}
            for group, label, text in exif.fields:
                node = groups.get(group)
                if node is None:
                    node = groups[group] = QTreeWidgetItem(self, [group])
                    node.setExpanded(True)
                QTreeWidgetItem(node, [label, text])
        elif exif is not None and exif.error:
            QTreeWidgetItem(QTreeWidgetItem(self, ["Photo"]), ["EXIF", exif.error])
            self.expandAll()


class ImagePage(QSplitter):
    """The picture and, on request, the information panel beside it."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.view = ImageView()
        self.info = InfoPanel()
        self.addWidget(self.view)
        self.addWidget(self.info)
        self.setStretchFactor(0, 1)
        self.setCollapsible(0, False)
        self.info.hide()

    def show_info(self, on: bool) -> None:
        self.info.setVisible(on)
        if on:
            self.setSizes([max(200, self.width() - 320), 320])
        self.view.setFocus()

    def setFocus(self) -> None:                     # the picture is what takes the keys
        self.view.setFocus()
