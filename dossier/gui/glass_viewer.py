"""The picture viewer with the see-through glass look: a frameless window over the screen, a dark layer with the desktop showing through
(blurred, when Windows can), the picture on top, and a floating bar that fades in when the mouse moves and out when it rests.

The look comes from ``core/glass.py`` (``frosted``, ``dim`` or ``solid``, with the fallback between them); the Windows blur call is in
``core/platform.py``. The picture itself is the same widget the F3 viewer uses (zoom, turn, wheel and keys), read on a thread.

Keys: Esc or Q closes; Right, Page Down and Space step to the next picture, Left, Page Up and Backspace to the previous (a zoomed picture
scrolls with the arrows first); Home and End go to the first and last; ``+``, ``-``, ``0`` (fit), ``1`` (every pixel), ``L`` and ``R``
(turn) are the picture's own.
"""
from __future__ import annotations

import functools
import os
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ..core import glass, platform, viewmodes
from ..core.platform import has_scheme
from ..core.worker import JobRunner, JobState
from . import theme
from .frost import blurred, grab_backdrop, screen_under_cursor  # noqa: F401  (shared with the file manager)
from .floating_bar import FADE_MS, BAR_IDLE_MS, FloatingBar  # noqa: F401  (re-exported)
from .image_view import ImageView, read_image
from .qt_bridge import QtDispatcher



def pictures_around(path: str) -> tuple:
    """The pictures in the folder of ``path`` in natural order, and the place of ``path`` among them."""
    folder, name = os.path.dirname(os.path.abspath(path)), os.path.basename(path)
    try:
        names = viewmodes.image_siblings(os.listdir(folder))
    except OSError:
        return [path], 0
    if name not in names:
        lower = [n.lower() for n in names]
        if name.lower() in lower:
            name = names[lower.index(name.lower())]
        else:
            return [path], 0
    return [os.path.join(folder, n) for n in names], names.index(name)


def saved_look(settings) -> tuple:
    """``(mode, level)`` the owner chose in Settings (``viewer/glass``, ``viewer/glass_level``); the default look when nothing was chosen."""
    try:
        mode, level = glass.parse(str(settings.value("viewer/glass", glass.DEFAULT_MODE)))
    except ValueError:
        mode, level = None, None
    saved_level = str(settings.value("viewer/glass_level", ""))
    return mode or glass.DEFAULT_MODE, int(saved_level) if saved_level.isdigit() else level


class GlassImageView(ImageView):
    """The picture, on a clear background; the arrow keys, Page keys, Space and Backspace step through the pictures when the picture
    does not need them to scroll."""

    def restyle(self) -> None:
        self.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))

    def _can_scroll(self) -> bool:
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        return h.maximum() > h.minimum() or v.maximum() > v.minimum()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        forward = key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Space)
        back = key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Backspace)
        if (forward or back) and not self._can_scroll():
            self.step_requested.emit(1 if forward else -1)
            return
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q, Qt.Key.Key_Home, Qt.Key.Key_End):
            event.ignore()                                    # to the window
            return
        super().keyPressEvent(event)


class GlassViewer(QWidget):
    closed = pyqtSignal()

    def __init__(self, paths: list, index: int = 0, mode: str = glass.DEFAULT_MODE, level: Optional[int] = None, *,
                 capabilities: Optional[glass.Capabilities] = None, blur: Optional[Callable] = None, blur_kind: str = "snapshot",
                 tint: Optional[int] = None, backdrop: Optional[Callable] = None, dispatch=None, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Dossier picture viewer")
        self.paths = list(paths)
        self.index = max(0, min(index, len(self.paths) - 1))
        self.requested = mode
        self.level = level
        self.capabilities = capabilities if capabilities is not None else glass.detect()
        self._blur = blur or functools.partial(platform.set_blur_behind, kind=blur_kind, **({} if tint is None else {"tint": tint}))
        self.mode = glass.resolve(mode, self.capabilities)                  # the best look this computer can do
        self._system_blur = blur is not None or blur_kind != "snapshot"    # Windows' own blur, only when asked for; else the blur is ours
        self._backdrop: Optional[QPixmap] = None
        if self.mode == glass.FROSTED and not self._system_blur:
            shot = (backdrop or grab_backdrop)()                            # the screen as it is now, blurred, is the glass
            if shot is None or shot.isNull():
                self.mode = glass.DIM
            else:
                self._backdrop = blurred(shot)
        self._dispatch = dispatch or QtDispatcher(self)
        self._runner = JobRunner(self._dispatch)
        if self.mode != glass.SOLID and self._backdrop is None:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.view = GlassImageView(self)
        self.view.setStyleSheet("QGraphicsView { background: transparent; border: 0; }")
        self.view.viewport().setAutoFillBackground(False)
        self.view.setMouseTracking(True)
        self.view.viewport().setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        self.view.step_requested.connect(self.step)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.view)

        self.floating = FloatingBar(self, self.view, self.step, self.close, captioned=True)
        self.bar, self.caption, self.buttons = self.floating.bar, self.floating.caption, self.floating.buttons
        self._cover_screen()
        self._show_current()
        self._poke()

    # the look -------------------------------------------------------------------------------------------------------------------
    def alpha(self) -> int:
        """The opacity (0 to 255) of the dark layer over the desktop in the mode that is in force."""
        return glass.alpha_for(self.mode, self.level)

    def paintEvent(self, event) -> None:
        tint = QColor(theme.current()["bg"])
        tint.setAlpha(self.alpha())
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.drawPixmap(self.rect(), self._backdrop)
            painter.fillRect(self.rect(), tint)
            return
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), tint)

    def _cover_screen(self) -> None:
        screen = screen_under_cursor()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.mode == glass.FROSTED and self._system_blur and not self._blur(int(self.winId())):
            self.mode = glass.DIM                                           # the system would not blur: see-through without the blur
            self.update()
        self.activateWindow()
        self.view.setFocus()

    # the picture -----------------------------------------------------------------------------------------------------------------
    def current_path(self) -> str:
        return self.paths[self.index] if self.paths else ""

    def _show_current(self) -> None:
        path = self.current_path()
        self._set_caption(f"{os.path.basename(path)}   {self.index + 1} / {len(self.paths)}")

        def work(progress, cancel):
            return read_image(path)

        def finished(job) -> None:
            if path != self.current_path():
                return                                                      # the owner has stepped on since
            if job.state is not JobState.DONE or job.result is None or job.result.isNull():
                self.view.set_image(None)
                self._set_caption(f"{os.path.basename(path)} cannot be decoded here   {self.index + 1} / {len(self.paths)}")
                return
            self.view.set_image(job.result)

        if path:
            self._runner.submit("Picture", work, on_done=finished)

    def step(self, delta: int) -> None:
        index = max(0, min(len(self.paths) - 1, self.index + delta))
        if index != self.index:
            self.index = index
            self._show_current()
        self._poke()

    def _set_caption(self, text: str) -> None:
        self.floating.set_caption(text)

    def _place_overlay(self) -> None:
        self.floating.place()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_overlay()

    def bar_visible(self) -> bool:
        return self.floating.is_visible()

    def _poke(self) -> None:
        self.floating.poke()

    def _fade_out(self) -> None:
        self.floating.fade_out()

    def mouseMoveEvent(self, event) -> None:
        self._poke()
        super().mouseMoveEvent(event)

    # keys and closing ---------------------------------------------------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        elif key == Qt.Key.Key_Home:
            self.step(-len(self.paths))
        elif key == Qt.Key.Key_End:
            self.step(len(self.paths))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.floating._idle.stop()
        self._runner.shutdown(wait=False)
        super().closeEvent(event)
        self.closed.emit()


class GlassViewMixin:
    """Part of ``MainWindow``: View as Glass (the picture under the cursor, or the marked pictures)."""

    def glass_view(self) -> None:
        local = [p for p in self.active.targets() if not has_scheme(p) and viewmodes.is_image_name(p)]
        if not local:
            self._say("Put the cursor on a picture on this computer to view it as glass")
            return
        shown, first = pictures_around(local[0]) if len(local) == 1 else (local, 0)
        mode, level = saved_look(self.settings)
        win = GlassViewer(shown, first, mode, level, dispatch=self.dispatcher)
        self.viewers.append(win)
        win.destroyed.connect(lambda _o=None, w=win: self.viewers.remove(w) if w in self.viewers else None)
        win.show()

    def open_glass_settings(self) -> None:
        from .glass_settings import GlassDialog
        mode, level = saved_look(self.settings)
        dlg = GlassDialog(mode, level, glass.detect(), self)
        if dlg.exec() != GlassDialog.DialogCode.Accepted:
            return
        mode, level = dlg.values()
        self.settings.setValue("viewer/glass", mode)
        if level is None:
            self.settings.remove("viewer/glass_level")
        else:
            self.settings.setValue("viewer/glass_level", level)
