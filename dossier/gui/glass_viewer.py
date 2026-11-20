"""The picture viewer with the see-through glass look: a frameless window over the screen, a dark layer with the desktop showing through
(blurred, when Windows can), the picture on top, and a floating bar that fades in when the mouse moves and out when it rests.

The look comes from ``core/glass.py`` (``frosted``, ``dim`` or ``solid``, with the fallback between them); the Windows blur call is in
``core/platform.py``. The picture itself is the same widget the F3 viewer uses (zoom, turn, wheel and keys), read on a thread.

Keys: Esc or Q closes; Right, Page Down and Space step to the next picture, Left, Page Up and Backspace to the previous (a zoomed picture
scrolls with the arrows first; Space pauses a moving GIF or WebP instead); Home and End go to the first and last; ``+``, ``-``, ``0`` (fit),
``1`` (every pixel), ``L`` and ``R`` (turn, kept in a JPEG) are the picture's own, and so is Ctrl+C (copy the picture and its file).
I shows the photo's facts at the top right (90A), Delete sends the picture to the Recycle Bin (88A), E opens it in the program for
pictures (95B); the gear has Open With. The next and the previous picture are read ahead (92A).
"""
from __future__ import annotations

import functools
import os
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget)

from ..core import glass, platform, viewmodes
from ..core.platform import has_scheme
from ..core.worker import JobRunner, JobState
from . import theme
from .frost import blurred, grab_backdrop, screen_under_cursor  # noqa: F401  (shared with the file manager)
from .floating_bar import FADE_MS, BAR_IDLE_MS, FloatingBar, Toast  # noqa: F401  (re-exported)
from .image_view import ImageView, read_image  # noqa: F401  (read_image: re-exported)
from .picture_tools import FactsCard, PictureActions, ReadAhead, facts_for, read_picture
from .qt_bridge import QtDispatcher

FACTS_KEY = "viewer/facts"               # the facts card is remembered (90A)



def saved_look(settings) -> tuple:
    """``(mode, level)`` the owner chose in Settings (``viewer/glass``, ``viewer/glass_level``); the default look when nothing was chosen."""
    try:
        mode, level = glass.parse(str(settings.value("viewer/glass", glass.DEFAULT_MODE)))
    except ValueError:
        mode, level = None, None
    saved_level = str(settings.value("viewer/glass_level", ""))
    return mode or glass.DEFAULT_MODE, int(saved_level) if saved_level.isdigit() else level


class GlassImageView(ImageView):
    """The picture, on a clear background; the stepping keys are the shared view's, the closing and first/last keys the window's."""

    def restyle(self) -> None:
        self.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_I):
            event.ignore()                                    # to the window
            return
        super().keyPressEvent(event)


class GlassViewer(PictureActions, QWidget):
    closed = pyqtSignal()

    def __init__(self, paths: list, index: int = 0, mode: str = glass.DEFAULT_MODE, level: Optional[int] = None, *,
                 capabilities: Optional[glass.Capabilities] = None, blur: Optional[Callable] = None, blur_kind: str = "snapshot",
                 tint: Optional[int] = None, backdrop: Optional[Callable] = None, dispatch=None, parent=None, settings=None,
                 trasher: Optional[Callable] = None, ask: Optional[Callable] = None, open_with: Optional[Callable] = None,
                 launcher: Optional[Callable] = None, changed: Optional[Callable] = None, reader: Callable = read_picture) -> None:
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
        self._reader = reader
        self.cache = ReadAhead(self._dispatch, reader=reader)
        self.setup_picture_actions(settings, trasher, ask, open_with, launcher, changed)
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
        self.view.delete_requested.connect(self.delete_picture)
        self.view.edit_requested.connect(self.edit_picture)
        self.view.turned.connect(self.keep_turn)
        self.view.can_delete = self.view.can_edit = True
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.view)

        self.floating = FloatingBar(self, self.view, self.step, self.close, captioned=True)
        self.floating.add_button("copy", "Copy", "Copy the picture and its file (Ctrl+C)", self.view.copy, icon="copy")
        self.info_button = self.floating.add_button("info", "ⓘ", "The photo's facts (I)", self.toggle_facts, checkable=True)
        self.floating.add_button("settings", "Settings", "Open With, Edit (E)", self._popup_settings, icon="settings")
        self.facts = FactsCard(self)
        self.facts_on = settings is not None and str(settings.value(FACTS_KEY, "false")).lower() == "true"
        self.info_button.setChecked(self.facts_on)
        self._picture = None                                                # what is shown, for the facts card
        self.floating.toggle_on_click(self.view)                            # a click shows the bar and keeps it; again hides it (83A)
        self.floating.add_slider(lambda: len(self.paths), lambda: self.index,   # a strip for long folders (84A)
                                 lambda i: os.path.basename(self.paths[i]), lambda i: self.step(i - self.index))
        self.bar, self.caption, self.buttons = self.floating.bar, self.floating.caption, self.floating.buttons
        self._said = QTimer(self)                                           # the window's own, so it dies with the window
        self._said.setSingleShot(True)
        self._said.setInterval(Toast.SHOW_MS)
        self._said.timeout.connect(self._unsay)
        self.view.copied.connect(self._say)
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
        kept = self.cache.get(path) if path else None
        if kept is not None:                                                # read ahead: shown at once (92A)
            self._shown(path, kept)
            return

        def work(progress, cancel):
            return self._reader(path)

        def finished(job) -> None:
            ok = job.state is JobState.DONE and job.result is not None and not job.result.image.isNull()
            if ok:
                self.cache.put(path, job.result)
            if path != self.current_path():
                return                                                      # the owner has stepped on since
            if not ok:
                self.view.set_image(None)
                self._picture = None
                self._update_facts()
                self._set_caption(f"{os.path.basename(path)} cannot be decoded here   {self.index + 1} / {len(self.paths)}")
                self._read_ahead()
                return
            self._shown(path, job.result)

        if path:
            self._runner.submit("Picture", work, on_done=finished)

    def _shown(self, path: str, picture) -> None:
        self.view.set_image(picture.image, path, picture.movie)
        self._picture = picture
        self._update_facts()
        self._read_ahead()

    def _read_ahead(self) -> None:
        """The next and the previous picture, read while this one is looked at; not while the slider is dragged (92A)."""
        slider = self.floating.slider
        if slider is not None and slider.dragging:
            return
        self.cache.read_ahead([self.paths[i] for i in (self.index + 1, self.index - 1) if 0 <= i < len(self.paths)])

    # 90A: the facts card -------------------------------------------------------------------------------------------------------
    def toggle_facts(self) -> None:
        self.facts_on = not self.facts_on
        self.info_button.setChecked(self.facts_on)
        if self._picture_settings is not None:
            self._picture_settings.setValue(FACTS_KEY, "true" if self.facts_on else "false")
        self._update_facts()

    def _update_facts(self) -> None:
        if not self.facts_on or not self.paths:
            self.facts.hide()
            return
        self.facts.show_facts(facts_for(self.current_path(), self._picture))
        self.facts.show()

    # the gear menu (95B) and what PictureActions needs ------------------------------------------------------------------------
    def _popup_settings(self) -> None:
        menu = QMenu(self)
        self.add_picture_menu(menu)
        self.floating.popup_menu(menu, "settings")

    def _picture_view(self):
        return self.view

    def _tell(self, text: str) -> None:
        self._say(text)

    def _after_delete(self) -> None:
        if not self.paths:
            self.close()
            return
        self._show_current()
        self._poke()

    def step(self, delta: int) -> None:
        index = max(0, min(len(self.paths) - 1, self.index + delta))
        if index != self.index:
            self.index = index
            self._show_current()
        self._poke()

    def _set_caption(self, text: str) -> None:
        self._name_caption = text
        self.floating.set_caption(text)

    def _say(self, text: str) -> None:
        """A message in the caption for a few seconds (the window has no status line), then the name of the picture again."""
        self.floating.set_caption(text)
        self._poke()
        self._said.start()

    def _unsay(self) -> None:
        self.floating.set_caption(self._name_caption)

    def _place_overlay(self) -> None:
        self.floating.place()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_overlay()
        self.facts.place()

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
        elif key == Qt.Key.Key_I:
            self.toggle_facts()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.floating._idle.stop()
        self._said.stop()
        self.view.set_image(None)                                           # a moving picture stops
        self.cache.close()
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
        shown, first = viewmodes.pictures_around(local[0]) if len(local) == 1 else (local, 0)
        mode, level = saved_look(self.settings)
        win = GlassViewer(shown, first, mode, level, dispatch=self.dispatcher, **self.picture_viewer_services())
        self.viewers.append(win)
        win.destroyed.connect(lambda _o=None, w=win: self.viewers.remove(w) if w in self.viewers else None)
        win.show()

    def picture_viewer_services(self) -> dict:
        """What a picture viewer opened from this window uses: the settings (facts card, the program for E), the window's Recycle Bin
        seam, the panel's Open With, the tools' starter, and a call back when a picture was turned or deleted."""
        return {"settings": self.settings, "trasher": self.trasher, "open_with": self.viewer_open_with,
                "launcher": self.launch_picture_editor, "changed": self.picture_file_changed}

    def launch_picture_editor(self, program: str, path: str) -> None:
        from ..core import tools
        tools.launch(tools.Tool(os.path.basename(program), program, "{file}"), [path], os.path.dirname(path), "",
                     starter=self.tool_starter)

    def picture_file_changed(self, path: str) -> None:
        """A viewer turned or deleted ``path``: its thumbnail is old, and a panel showing its folder is read again."""
        thumbs = getattr(self, "thumbs", None)
        if thumbs is not None:
            thumbs.forget(path)
        folder = os.path.normcase(os.path.dirname(path))
        for panel in (self.left, self.right):
            if not panel.is_home and os.path.normcase(panel.path) == folder:
                panel.refresh()

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
