"""The floating bar over a picture: previous, next, zoom out, zoom in, fit, every pixel, turn left, turn right, close. It fades in when the
mouse moves over the picture and out when it rests. Shared by the glass viewer and the F3 viewer, so a picture looks and behaves the same in both.

Other windows give their own buttons through ``specs`` (the notepad does): ``(key, glyph, tip, slot)`` tuples, the last one the close button.

``host`` is the widget the bar floats in, ``view`` the picture (an ``ImageView``) whose geometry it floats over. With ``captioned`` a
caption (the file name and place in the folder) floats at the top as well.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QEvent, QObject, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

from . import icon_set, theme

BAR_IDLE_MS = 2500           # the bar fades out after this long without the mouse moving
FADE_MS = 180


class FloatingBar(QObject):
    def __init__(self, host: QWidget, view, step: Callable, close: Callable, captioned: bool = False, specs=None) -> None:
        super().__init__(host)
        self.host = host
        self.view = view
        fg = QColor(theme.current()["fg"])
        shade = f"rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38)"
        text = fg.name()
        self.bar = QFrame(host)
        self.bar.setObjectName("glassbar")
        row = self.row = QHBoxLayout(self.bar)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(2)
        self.buttons: dict = {}
        for key, glyph, tip, slot in (specs if specs is not None else (("prev", "◀", "Previous picture (Left)", lambda: step(-1)),
                                      ("next", "▶", "Next picture (Right)", lambda: step(1)),
                                      ("out", "−", "Zoom out (-)", lambda: view.zoom_by(0.8)),
                                      ("in", "+", "Zoom in (+)", lambda: view.zoom_by(1.25)),
                                      ("fit", "▢", "Fit to the window (0)", lambda: view.fit()),
                                      ("actual", "1:1", "Every pixel (1)", lambda: view.actual_size()),
                                      ("left", "↶", "Turn left (L)", lambda: view.turn(-1)),
                                      ("right", "↷", "Turn right (R)", lambda: view.turn(1)),
                                      ("close", "✕", "Close (Esc)", close))):
            b = QPushButton(glyph)
            b.setToolTip(tip)
            b.setFlat(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMouseTracking(True)
            if len(glyph) > 2 and glyph != "1:1":
                b.setStyleSheet("font-size: 16px;")                             # a word, not a symbol
            b.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(b)
            self.buttons[key] = b
        self.bar.setStyleSheet(
            f"QFrame#glassbar {{ background: {shade}; border-radius: 21px; }}"
            f"QPushButton {{ color: {text}; border: 0; padding: 6px 16px; font-size: 24px; border-radius: 12px; }}"
            f"QPushButton:hover, QPushButton:checked {{ background: {shade}; }}")
        self.caption = QLabel(host)
        self.caption.setObjectName("glasscaption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet(f"QLabel#glasscaption {{ background: {shade}; color: {text}; border-radius: 10px; padding: 3px 12px; }}")
        self.captioned = captioned
        self._effects: dict = {}
        self._fades: dict = {}
        for widget in self._widgets():
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            self._effects[widget] = effect
        if not captioned:
            self.caption.hide()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(BAR_IDLE_MS)
        self._idle.timeout.connect(self.fade_out)
        self.watch(view)
        view.installEventFilter(self)                                       # a resize of the picture moves the bar with it
        self.enabled = True

    def add_button(self, key: str, glyph: str, tip: str, slot: Callable, checkable: bool = False, icon: str = "") -> QPushButton:
        """An extra button just before the close button. With ``icon`` (a name in the icon set) the button shows that icon, not ``glyph``."""
        b = QPushButton("" if icon else glyph)
        if icon:
            b.setIcon(icon_set.icon(icon, theme.current()["fg"]))
            b.setIconSize(QSize(24, 24))
            b.setStyleSheet("padding: 6px 10px;")
        b.setToolTip(tip)
        b.setFlat(True)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setMouseTracking(True)
        if len(glyph) > 2 and not icon:
            b.setStyleSheet("font-size: 16px;")                                 # a word, not a symbol
        b.clicked.connect(lambda _c=False: slot())
        self.row.insertWidget(self.row.count() - 1, b)
        self.buttons[key] = b
        self.bar.adjustSize()
        return b

    def watch(self, widget) -> None:
        """Mouse movement over ``widget`` (and its viewport) shows the bar."""
        for w in (widget, widget.viewport() if hasattr(widget, "viewport") else None):
            if w is not None:
                w.setMouseTracking(True)
                w.installEventFilter(self)

    def add_separator(self) -> QWidget:
        """A thin line between clusters of buttons (before the close button)."""
        line = _Separator(self.bar)
        self.row.insertWidget(self.row.count() - 1, line)
        return line

    def add_label(self, text: str = "") -> QLabel:
        """A readout in the bar (the cursor position), before the close button."""
        label = QLabel(text, self.bar)
        label.setStyleSheet(f"color: {QColor(theme.current()['fg']).name()}; font-size: 14px; padding: 0 8px;")
        self.row.insertWidget(self.row.count() - 1, label)
        return label

    def _widgets(self) -> tuple:
        return (self.bar, self.caption) if self.captioned else (self.bar,)

    # showing and hiding ----------------------------------------------------------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        """Off while something other than a picture is shown: the bar is hidden and stays hidden."""
        self.enabled = on
        if on:
            self.poke()
            return
        self._idle.stop()
        for widget in (self.bar, self.caption):
            widget.hide()

    def set_stepping(self, on: bool) -> None:
        """Previous and next only make sense with more than one picture."""
        for key in ("prev", "next"):
            if key in self.buttons:
                self.buttons[key].setVisible(on)
        self.bar.adjustSize()
        self.place()

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)
        self.caption.adjustSize()
        self.place()

    def is_visible(self) -> bool:
        return not self.bar.isHidden()

    def place(self) -> None:
        area = self.view.geometry() if self.view.parentWidget() is self.host else self.host.rect()
        self.bar.adjustSize()
        self.bar.move(area.x() + (area.width() - self.bar.width()) // 2, area.y() + area.height() - self.bar.height() - max(24, area.height() // 24))
        self.caption.move(area.x() + (area.width() - self.caption.width()) // 2, area.y() + max(18, area.height() // 40))
        self.bar.raise_()
        self.caption.raise_()

    def _fade(self, widget: QWidget, to: float) -> None:
        effect = self._effects[widget]
        old = self._fades.get(widget)
        if old is not None:
            old.stop()
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setEndValue(to)
        if to == 0.0:
            animation.finished.connect(widget.hide)
        else:
            widget.show()
        self._fades[widget] = animation
        animation.start()

    def poke(self) -> None:
        """The mouse moved or a picture was stepped to: show the bar, and hide it again after a rest."""
        if not self.enabled:
            return
        for widget in self._widgets():
            if widget.isHidden() or self._effects[widget].opacity() < 1.0:
                self._fade(widget, 1.0)
        self.place()
        self._idle.start()

    def fade_out(self) -> None:
        if self.bar.underMouse():
            self._idle.start()                                              # the mouse is on the bar: leave it
            return
        for widget in self._widgets():
            self._fade(widget, 0.0)

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self.poke()
        elif kind == QEvent.Type.Resize:
            self.place()
        return False


class _Separator(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setFixedSize(11, 26)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        fg = QColor(theme.current()["fg"])
        fg.setAlpha(70)
        painter.fillRect(5, 3, 1, 20, fg)


class Toast(QLabel):
    """A short message that floats at the top of ``host`` and goes away by itself (the status line of a window that has none).
    ``setText`` shows it; an empty text hides it. ``text()`` is the message, so a test can read it."""

    SHOW_MS = 5000

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host
        fg = QColor(theme.current()["fg"])
        self.setStyleSheet(f"background: rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38); color: {fg.name()}; border-radius: 10px; padding: 3px 12px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.SHOW_MS)
        self._timer.timeout.connect(self.hide)
        host.installEventFilter(self)
        self.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        if not text:
            self.hide()
            return
        self.setMaximumWidth(max(120, self.host.width() - 40))
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start()

    def set_quiet(self, text: str) -> None:
        """Keep ``text`` (it can be read back) without showing it: a standing fact, not news."""
        super().setText(text)
        if not self._timer.isActive():
            self.hide()

    def _place(self) -> None:
        self.move(max(0, (self.host.width() - self.width()) // 2), max(10, self.host.height() // 40))

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
