"""The picture view of the F3 viewer: fit to the window or zoom, turn, and an information panel with the EXIF of a photo.

The picture is decoded on a thread by the window (``read_image``); this file only shows it. Zoom: ``+`` and ``-`` or Ctrl+wheel, ``0`` fits
the window, the wheel steps to the next or previous picture and so do Right, Page Down and Space (forward) and Left, Page Up and
Backspace (back) unless a zoomed picture needs them to scroll, ``1`` shows every pixel, double-click toggles between the two; ``L`` and ``R``
turn the picture a quarter (``turned`` tells the window, which keeps the turn in a JPEG, 89A); dragging moves a zoomed picture. Zoom, fit
and 1:1 glide there in about a sixth of a second toward the point under the mouse (93A); a new picture is fitted at once. An animated GIF
or WebP plays round and round, and Space pauses it (94A). A photo taken upright but stored sideways is turned by its EXIF orientation when
it is read. Ctrl+C copies the picture as it is shown (turned too) and its file. Delete and E are the window's (``delete_requested``,
``edit_requested``). A right-click gives the same as a menu.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QBuffer, QByteArray, QEasingCurve, QIODevice, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QImage, QImageReader, QKeySequence, QMovie, QPainter, QPixmap, QTransform
from PyQt6.QtWidgets import (QAbstractItemView, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHeaderView, QMenu, QSplitter,
                             QTreeWidget, QTreeWidgetItem, QWidget)

from ..core import viewmodes, wheel
from ..core.exif import Exif
from . import file_clipboard, theme

MIN_ZOOM, MAX_ZOOM = 0.02, 32.0
SETTLE = 0.35        # seconds after the wheel last scrolled the picture before the same spin may step to the next one
GLIDE_MS = 160       # zoom, fit and 1:1 glide this long (93A); 0 jumps (the tests set it so, except the one about gliding)


def read_image(path: str) -> QImage:
    """Decode a picture file (upright by its EXIF orientation). Safe on a worker thread; a null image when it cannot be read."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    return reader.read()


class ImageView(QGraphicsView):
    changed = pyqtSignal()
    step_requested = pyqtSignal(int)                    # the wheel asks for the next (1) or previous (-1) picture
    copied = pyqtSignal(str)                            # what a copy did, for the window to say
    turned = pyqtSignal(int)                            # the owner turned the picture this many quarters (89A: the window keeps it)
    delete_requested = pyqtSignal()                     # Delete (88A)
    edit_requested = pyqtSignal()                       # E (95B)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.glide_ms = GLIDE_MS
        self._glide = QVariantAnimation(self)
        self._glide.setStartValue(0.0)
        self._glide.setEndValue(1.0)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(self._glide_step)
        self._glide_plan: Optional[tuple] = None
        self._movie: Optional[QMovie] = None
        self._movie_buffer: Optional[QBuffer] = None
        self.can_delete = self.can_edit = False         # the window says whether Delete and E do something (the right-click menu)
        self._wheel_steps = 0
        self._scrolled_at = 0.0
        self.wheel_map = dict(wheel.DEFAULTS)           # what the wheel does, set by the viewer from the settings
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: Optional[QGraphicsPixmapItem] = None
        self._image: Optional[QImage] = None
        self._path = ""                                  # the file of the picture, copied along with it
        self._turn = 0                                 # quarter turns clockwise, by the owner
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
    def set_image(self, image: Optional[QImage], path: str = "", movie: bytes = b"") -> None:
        """Show ``image`` (fitted at once, no glide). ``movie``: the bytes of an animated GIF or WebP, which then plays (94A)."""
        self._glide.stop()
        self._glide_plan = None
        self._stop_movie()
        self._scene.clear()
        self._item = None
        self._image = image if image is not None and not image.isNull() else None
        self._path = path if self._image is not None else ""
        self._turn = 0
        if self._image is not None:
            self._show()
            self.fit(glide=False)
            if movie:
                self._start_movie(movie)
        self.changed.emit()

    # 94A: a moving picture ------------------------------------------------------------------------------------------------------
    def _start_movie(self, data: bytes) -> None:
        buffer = QBuffer(self)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        movie = QMovie(buffer, QByteArray(), self)
        if not movie.isValid():
            buffer.close()
            return
        self._movie, self._movie_buffer = movie, buffer
        movie.frameChanged.connect(self._next_frame)
        movie.finished.connect(movie.start)                     # round and round, also when the file says to play once
        movie.start()

    def _stop_movie(self) -> None:
        movie, buffer = self._movie, self._movie_buffer
        self._movie = self._movie_buffer = None
        if movie is not None:
            movie.frameChanged.disconnect()
            movie.finished.disconnect()
            movie.stop()
            movie.deleteLater()
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

    def _next_frame(self, _number: int) -> None:
        movie = self._movie
        if movie is None or self._item is None:
            return
        frame = movie.currentImage()
        if frame.isNull():
            return
        self._image = frame
        self._item.setPixmap(QPixmap.fromImage(self.shown_image()))

    def is_animated(self) -> bool:
        return self._movie is not None

    def is_paused(self) -> bool:
        return self._movie is not None and self._movie.state() == QMovie.MovieState.Paused

    def toggle_pause(self) -> None:
        if self._movie is not None:
            self._movie.setPaused(self._movie.state() != QMovie.MovieState.Paused)
            self.changed.emit()

    def frame_number(self) -> int:
        return self._movie.currentFrameNumber() if self._movie is not None else 0

    def has_image(self) -> bool:
        return self._image is not None

    def image_size(self) -> tuple:
        return (self._image.width(), self._image.height()) if self._image is not None else (0, 0)

    def shown_image(self) -> Optional[QImage]:
        """The picture as it is shown: turned when the owner turned it."""
        if self._image is None or not self._turn:
            return self._image
        return self._image.transformed(QTransform().rotate(90 * self._turn), Qt.TransformationMode.SmoothTransformation)

    def copy(self) -> str:
        """The picture to the clipboard as it is shown, with its file: a program pastes the picture, a folder the file."""
        image = self.shown_image()
        if image is None:
            message = "There is no picture to copy"
        else:
            file_clipboard.put([self._path] if self._path else [], False, image=image)
            message = f"Copied the picture ({image.width()} x {image.height()}): paste it into a program, or into a folder as the file"
        self.copied.emit(message)
        return message

    def _is_svg(self) -> bool:
        return self._path.lower().endswith(viewmodes.SVG_EXTENSIONS)

    def _show(self) -> None:
        self._scene.clear()
        if self._is_svg():
            from PyQt6.QtSvgWidgets import QGraphicsSvgItem
            item = QGraphicsSvgItem(self._path)        # drawn from the vector at every zoom: sharp, where a picture would blur
            if item.renderer().isValid():
                box = item.boundingRect()
                item.setTransformOriginPoint(box.center())
                item.setRotation(90 * self._turn)
                self._scene.addItem(item)
                self._item = item
                self._scene.setSceneRect(item.sceneBoundingRect())
                return
        self._item = self._scene.addPixmap(QPixmap.fromImage(self.shown_image()))
        self._scene.setSceneRect(QRectF(self._item.boundingRect()))

    # zoom and turn ----------------------------------------------------------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def gliding(self) -> bool:
        return self._glide_plan is not None

    def target_zoom(self) -> float:
        """Where the zoom is going (the zoom itself when it is not gliding)."""
        return self._glide_plan[1] if self._glide_plan is not None else self.zoom

    def _fit_scale(self) -> float:
        view, pic = self.viewport().size(), self._scene.sceneRect()
        if pic.width() <= 0 or pic.height() <= 0:
            return 1.0
        scale = min(view.width() / pic.width(), view.height() / pic.height())
        return scale if self._is_svg() else min(scale, 1.0)

    def _center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect()).boundingRect().center()

    def _go(self, zoom: float, center: Optional[QPointF] = None, glide: bool = True) -> None:
        """To ``zoom``, with ``center`` in the middle (fit), or else keeping the point under the mouse where it is (the middle when
        the mouse is elsewhere), as Qt's own anchor did. Glides over ``glide_ms`` (93A) unless ``glide`` is False."""
        z0 = self.zoom
        if center is None:
            mouse = self.viewport().mapFromGlobal(QCursor.pos())
            under = self.viewport().rect().contains(mouse) and self.underMouse()
            middle = QPointF(self.viewport().rect().center())
            m = QPointF(mouse) if under else None
            anchor = self._center() + ((m - middle) / z0 if m is not None else QPointF())   # the scene point under the mouse
            offset = m                                                   # where it stays (None: the middle)
        else:
            anchor, offset = None, None
        plan = (z0, zoom, self._center(), center, anchor, offset)
        self._glide.stop()
        if not glide or self.glide_ms <= 0 or not self.isVisible() or abs(zoom - z0) < 1e-9 and center is None:
            self._glide_plan = plan
            self._glide_step(1.0)
            self._glide_plan = None
            self.changed.emit()
            return
        self._glide_plan = plan
        self._glide.setDuration(self.glide_ms)
        self._glide.start()

    def _glide_step(self, t) -> None:
        plan = self._glide_plan
        if plan is None:
            return
        z0, z1, c0, center, anchor, offset = plan
        t = float(t)
        z = z0 * (z1 / z0) ** t if z0 > 0 and z1 > 0 else z1
        self.setTransform(QTransform.fromScale(z, z))
        if center is not None:
            self.centerOn(c0 + (center - c0) * t)
        else:                                                               # the anchor stays under the mouse all the way; the
            middle = QPointF(self.viewport().rect().center())               # middle is taken again, as scroll bars come and go
            self.centerOn(anchor - ((offset - middle) / z if offset is not None else QPointF()))
        if t >= 1.0:
            self._glide_plan = None
        self.changed.emit()

    def fit(self, glide: bool = True) -> None:
        """Show the whole picture in the window (a photo never bigger than it is; an SVG, being drawn, as big as fits)."""
        if self._item is None:
            return
        self._fit = True
        self._go(self._fit_scale(), self._scene.sceneRect().center(), glide)

    def actual_size(self) -> None:
        if self._item is None:
            return
        self._fit = False
        self._go(1.0)

    def zoom_by(self, factor: float) -> None:
        if self._item is None:
            return
        target = max(MIN_ZOOM, min(MAX_ZOOM, self.target_zoom() * factor))   # a quick spin adds up from where it is going
        self._fit = False
        self._go(target)

    def turn(self, quarters: int) -> None:
        if self._image is None:
            return
        self._turn = (self._turn + quarters) % 4
        was_fit = self._fit
        self._glide.stop()
        self._glide_plan = None
        self._show()
        if was_fit:
            self.fit(glide=False)
        else:
            self.centerOn(self._item)
        self.changed.emit()
        self.turned.emit(quarters)

    def toggle_fit(self) -> None:
        self.actual_size() if self._fit else self.fit()

    # events -------------------------------------------------------------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self.fit(glide=False)

    def wheelEvent(self, event) -> None:
        """The action the owner chose for this key combination (Settings > Mouse Wheel...). By default the wheel scrolls a zoomed
        picture and steps to the next or previous one when the picture is at its end (or fits), Ctrl+wheel zooms and Shift+wheel
        scrolls."""
        mods = event.modifiers()
        action = self.wheel_map[wheel.key_for(bool(mods & Qt.KeyboardModifier.ControlModifier),
                                              bool(mods & Qt.KeyboardModifier.ShiftModifier))]
        delta = event.angleDelta()
        amount = delta.y() or delta.x()                          # some mice send Shift+wheel as a sideways wheel
        if action == "zoom":
            self.zoom_by(1.25 if amount > 0 else 0.8)
        elif action == "step":
            self._step_by_wheel(amount)
        elif action == "scroll_step":
            bar = self.verticalScrollBar()
            can_scroll = bar.maximum() > bar.minimum()
            at_end = bar.value() >= bar.maximum() if amount < 0 else bar.value() <= bar.minimum()
            if can_scroll and not at_end:
                bar.setValue(bar.value() - amount)
                self._scrolled_at = time.monotonic()
                self._wheel_steps = 0
            elif not (can_scroll and time.monotonic() - self._scrolled_at < SETTLE):   # not while the wheel is still spinning past the end
                self._step_by_wheel(amount)
        elif action == "scroll":
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - amount)
        elif action == "scroll_sideways":
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - amount)
        event.accept()

    def _step_by_wheel(self, amount: int) -> None:
        self._wheel_steps += amount                              # a notch is 120; a touchpad sends many small ones
        while abs(self._wheel_steps) >= 120:
            self.step_requested.emit(-1 if self._wheel_steps > 0 else 1)
            self._wheel_steps -= 120 if self._wheel_steps > 0 else -120

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_fit()

    def _can_scroll(self) -> bool:
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        return h.maximum() > h.minimum() or v.maximum() > v.minimum()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        forward = key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Space)
        back = key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Backspace)
        plain = not (event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)     # the number pad's arrows count as plain
        if key == Qt.Key.Key_Space and plain and self.is_animated():
            self.toggle_pause()                                  # Space pauses a moving picture; it steps only past still ones (94A)
        elif key == Qt.Key.Key_Delete and plain:
            self.delete_requested.emit()
        elif key == Qt.Key.Key_E and plain:
            self.edit_requested.emit()
        elif (forward or back) and plain and not self._can_scroll():
            self.step_requested.emit(1 if forward else -1)
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
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

    def context_menu(self) -> QMenu:
        """The right-click menu: what the keys do, with the key beside each (greyed while there is no picture)."""
        menu = QMenu(self)
        items = (("Copy Picture", "Ctrl+C", self.copy), None, ("Fit to Window", "0", self.fit), ("Actual Size", "1", self.actual_size),
                 None, ("Turn Left", "L", lambda: self.turn(-1)), ("Turn Right", "R", lambda: self.turn(1)))
        if self.is_animated():
            items += (None, ("Play" if self.is_paused() else "Pause", "Space", self.toggle_pause))
        if self.can_edit or self.can_delete:
            items += (None,)
        if self.can_edit:
            items += (("Edit in Another Program", "E", self.edit_requested.emit),)
        if self.can_delete:
            items += (("Delete", "Del", self.delete_requested.emit),)
        for item in items:
            if item is None:
                menu.addSeparator()
                continue
            label, keys, slot = item
            action = menu.addAction(label + chr(9) + keys)
            action.setEnabled(self.has_image())
            action.triggered.connect(lambda _c=False, s=slot: s())
        return menu

    def contextMenuEvent(self, event) -> None:
        self.context_menu().exec(event.globalPos())


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

    def show_groups(self, groups: list) -> None:
        """``[(heading, [(label, text)])]``: the same panel for a document's, a table's or a PDF's own facts."""
        self.clear()
        for heading, rows in groups:
            if not rows:
                continue
            node = QTreeWidgetItem(self, [heading])
            for label, text in rows:
                item = QTreeWidgetItem(node, [label, text])
                item.setToolTip(1, text)
            node.setExpanded(True)

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
