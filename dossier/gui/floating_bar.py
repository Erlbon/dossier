"""The floating bar over a picture: previous, next, zoom out, zoom in, fit, every pixel, turn left, turn right, close. It fades in when the
mouse moves over the picture and out when it rests. Shared by the glass viewer and the F3 viewer, so a picture looks and behaves the same in both.

Other windows give their own buttons through ``specs`` (the notepad does): ``(key, glyph, tip, slot)`` tuples, the last one the close button.

``host`` is the widget the bar floats in, ``view`` the picture (an ``ImageView``) whose geometry it floats over. With ``captioned`` a
caption (the file name and place in the folder) floats at the top as well.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from . import icon_set, theme

BAR_IDLE_MS = 2500           # the bar fades out after this long without the mouse moving
FADE_MS = 180
SLIDER_GAP = 10              # between the slider and the bar below it
CLICK_SLOP = 4               # a press and release this close together (pixels) is a click on the picture, not a drag


BACKDROP_ALPHA = 205         # the bar's own backdrop: the theme's card colour, mostly opaque


def backdrop() -> str:
    """The backdrop of the bar, caption, slider and toasts: the scheme's card colour, nearly solid. A tint of the text colour alone
    (as before 2026-11-20) let a pale picture shine through a dark-scheme bar, so the light buttons vanished on it."""
    card = QColor(theme.current()["card"])
    return f"rgba({card.red()}, {card.green()}, {card.blue()}, {BACKDROP_ALPHA})"


def glass_menu(menu: QMenu) -> None:
    """Give a menu of the floating bar the bar's own look (the owner, 2026-11-19, option A): a rounded box with a faint edge in the
    bar's colours, room around each entry, and the same rounded highlight as the bar's buttons. Its submenus get it too. Called at
    every opening, so a change of colour scheme is followed."""
    t = theme.current()
    fg = QColor(t["fg"])
    hover = f"rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38)"
    sheet = (f"QMenu {{ background: {theme.mix(t['fg'], t['card'], 0.14)}; color: {fg.name()}; border: 1px solid {hover};"
             f" border-radius: 14px; padding: 8px; font-size: 14px; }}"
             f"QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 9px; background: transparent; }}"
             f"QMenu::item:selected {{ background: {hover}; }}"
             f"QMenu::item:disabled {{ color: {t['dim']}; }}"
             f"QMenu::separator {{ height: 1px; background: {hover}; margin: 5px 10px; }}"
             f"QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}"
             f"QMenu::right-arrow {{ margin-right: 8px; }}")
    menus, seen = [menu], set()
    while menus:
        m = menus.pop()
        if id(m) in seen:
            continue
        seen.add(id(m))
        if not m.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):   # the corners outside the rounding stay clear
            m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
            m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        m.setStyleSheet(sheet)
        menus += [a.menu() for a in m.actions() if a.menu() is not None]


class FloatingBar(QObject):
    def __init__(self, host: QWidget, view, step: Callable, close: Callable, captioned: bool = False, specs=None) -> None:
        super().__init__(host)
        self.host = host
        self.view = view
        # set first: the buttons send their events here as soon as they exist
        self.pinned = False              # shown by a click on the picture: stays until the next click there (83A)
        self.slider: Optional["GlassSlider"] = None
        self.buttons: dict = {}
        self._effects: dict = {}
        self._click_targets: set = set()
        self._press: Optional[tuple] = None
        fg = QColor(theme.current()["fg"])
        shade = f"rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38)"
        text = fg.name()
        self.bar = QFrame(host)
        self.bar.setObjectName("glassbar")
        row = self.row = QHBoxLayout(self.bar)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(2)
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
            b.installEventFilter(self)                                   # no click while the bar is still fading in (82A)
            row.addWidget(b)
            self.buttons[key] = b
        self.bar.setStyleSheet(
            f"QFrame#glassbar {{ background: {backdrop()}; border: 1px solid {shade}; border-radius: 21px; }}"
            f"QPushButton {{ color: {text}; border: 0; padding: 6px 16px; font-size: 24px; border-radius: 12px; }}"
            f"QPushButton:hover, QPushButton:checked {{ background: {shade}; }}")
        self.caption = QLabel(host)
        self.caption.setObjectName("glasscaption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet(f"QLabel#glasscaption {{ background: {backdrop()}; color: {text}; border-radius: 10px; padding: 3px 12px; }}")
        self.captioned = captioned
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
        self._click = QTimer(self)       # a click waits out the double-click time: a double click fits the picture instead
        self._click.setSingleShot(True)
        self._click.timeout.connect(self.toggle_pinned)
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
        b.installEventFilter(self)
        self.row.insertWidget(self.row.count() - 1, b)
        self.buttons[key] = b
        self.bar.adjustSize()
        return b

    def popup_menu(self, menu: QMenu, key: str) -> None:
        """A menu of the bar, in the bar's own look (``glass_menu``), opened upwards just above the bar with a small gap and lined up
        with its button, so the whole bar stays in sight (the owner, 2026-11-20, option A)."""
        glass_menu(menu)
        menu.popup(self.menu_position(menu, key))

    MENU_GAP = 8

    def menu_position(self, menu: QMenu, key: str) -> QPoint:
        """Where a menu opens: its left edge at the button's, its bottom ``MENU_GAP`` above the top of the bar (or of the slider,
        when it is shown above the bar)."""
        button = self.buttons[key]
        left = button.mapToGlobal(QPoint(0, 0)).x()
        top = self.bar.mapToGlobal(QPoint(0, 0)).y()
        if self._slider_shown():
            top = min(top, self.slider.mapToGlobal(QPoint(0, 0)).y())
        return QPoint(left, top - self.MENU_GAP - menu.sizeHint().height())

    # a click on the picture shows the bar and keeps it; the next click there hides it (83A) ---------------------------------------
    def toggle_on_click(self, widget) -> None:
        """A plain click on ``widget`` (a picture view) pins the bar, or unpins and hides it. A drag (panning) and a double click
        (fit) are not clicks. The events still reach the view."""
        target = widget.viewport() if hasattr(widget, "viewport") else widget
        self._click_targets.add(target)
        target.installEventFilter(self)

    def toggle_pinned(self) -> None:
        if not self.enabled:
            return
        if self.pinned:
            self.pinned = False
            for widget in self._widgets():
                self._fade(widget, 0.0)
            return
        self.pinned = True
        self._idle.stop()
        self.show_fully()

    # 82A: the bar takes clicks only once it is fully shown -------------------------------------------------------------------------
    def fully_shown(self) -> bool:
        effect = self._effects.get(self.bar)
        return not self.bar.isHidden() and effect is not None and effect.opacity() >= 0.999

    def show_fully(self) -> None:
        """Bring the bar (and caption and slider) in at once, without a fade."""
        for widget in self._widgets():
            fade = self._fades.pop(widget, None)
            if fade is not None:
                fade.stop()
            self._effects[widget].setOpacity(1.0)
            widget.show()
        self.place()
        if not self.pinned:
            self._idle.start()

    # 84A: the slider above the bar -------------------------------------------------------------------------------------------------
    def add_slider(self, count: Callable[[], int], index: Callable[[], int], name: Callable[[int], str], go: Callable[[int], None],
                   wanted: Callable[[], bool] = lambda: True) -> "GlassSlider":
        """A thin glass strip above the bar for long lists: dragging shows "331 / 870 · name" and only where it is let go is shown
        (``go``); a click on the strip jumps there. Shown with the bar, only when ``wanted()`` and there is more than one item."""
        self.slider = GlassSlider(self.host, self, count, index, name, go)
        self.slider.installEventFilter(self)
        effect = QGraphicsOpacityEffect(self.slider)
        self.slider.setGraphicsEffect(effect)
        self._effects[self.slider] = effect
        self._slider_wanted = wanted
        self.slider.hide()
        self.place()
        return self.slider

    def _slider_shown(self) -> bool:
        return self.slider is not None and not self.slider.isHidden()

    def _slider_fits(self) -> bool:
        return self.slider is not None and self._slider_wanted() and self.slider.count() > 1

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
        out = (self.bar, self.caption) if self.captioned else (self.bar,)
        if getattr(self, "slider", None) is not None:
            if self._slider_fits():
                out += (self.slider,)
            else:
                self.slider.hide()                                          # one picture, or not a picture: no slider
        return out

    # showing and hiding ----------------------------------------------------------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        """Off while something other than a picture is shown: the bar is hidden and stays hidden."""
        self.enabled = on
        if on:
            self.poke()
            return
        self._idle.stop()
        self.pinned = False
        for widget in (self.bar, self.caption, self.slider):
            if widget is not None:
                widget.hide()

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
        if self.slider is not None:                                         # nearly the area's width, just above the bar
            width = max(self.bar.width(), int(area.width() * 0.76))
            self.slider.setGeometry(area.x() + (area.width() - width) // 2, self.bar.y() - SLIDER_GAP - GlassSlider.HEIGHT,
                                    width, GlassSlider.HEIGHT)
            self.slider.raise_()
            self.slider.update()

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
        if not self.pinned:
            self._idle.start()

    def fade_out(self) -> None:
        if self.pinned:
            return                                                          # a click put it there: the next click takes it away
        if self.bar.underMouse() or (self.slider is not None and (self.slider.underMouse() or self.slider.dragging)):
            self._idle.start()                                              # the mouse is on the bar: leave it
            return
        for widget in self._widgets():
            self._fade(widget, 0.0)

    _CLICKS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if obj in self.buttons.values() or (self.slider is not None and obj is self.slider):
            if kind in self._CLICKS and not self.fully_shown():             # 82A: a click on a bar still fading in only shows it
                if kind == QEvent.Type.MouseButtonPress:
                    self.show_fully()
                return True
            if kind == QEvent.Type.MouseMove:
                self.poke()
            return False                                                    # their own resizes must not place the bar again
        if obj in self._click_targets and kind in self._CLICKS:
            self._watch_click(event)
            return False
        if kind == QEvent.Type.MouseMove:
            self.poke()
        elif kind == QEvent.Type.Resize:
            self.place()
        return False

    def _watch_click(self, event) -> None:
        """A press and release of the left button within a few pixels is a click; a double click cancels it (that fits the picture)."""
        kind = event.type()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        where = event.position().toPoint()
        if kind == QEvent.Type.MouseButtonPress:
            self._press = (where, self._click.isActive())
        elif kind == QEvent.Type.MouseButtonDblClick:
            self._click.stop()
            self._press = None
        elif kind == QEvent.Type.MouseButtonRelease and self._press is not None:
            start, _waiting = self._press
            self._press = None
            if (where - start).manhattanLength() <= CLICK_SLOP:
                self._click.start(QApplication.doubleClickInterval())


class GlassSlider(QWidget):
    """The strip above the bar (84A): a rounded glass track, the part up to the current item in gold, a round handle. Dragging shows
    "331 / 870 · name" above the handle and moves nothing until the button is let go; a click jumps to that place."""

    HEIGHT = 22

    def __init__(self, host: QWidget, bar: "FloatingBar", count: Callable[[], int], index: Callable[[], int],
                 name: Callable[[int], str], go: Callable[[int], None]) -> None:
        super().__init__(host)
        self.floating = bar
        self.count, self.index, self.name, self.go = count, index, name, go
        self.dragging = False
        self.target: Optional[int] = None                     # the item under the handle while dragging
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Drag to go through the pictures; a click jumps there")
        fg = QColor(theme.current()["fg"])
        self.tip = QLabel(host)
        self.tip.setStyleSheet(f"background: rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38); color: {fg.name()};"
                               f" border-radius: 10px; padding: 3px 12px;")
        self.tip.hide()

    def _index_at(self, x: float) -> int:
        n = self.count()
        usable = max(1, self.width() - self.HEIGHT)
        share = min(1.0, max(0.0, (x - self.HEIGHT / 2) / usable))
        return round(share * (n - 1)) if n > 1 else 0

    def _x_of(self, i: int) -> float:
        n = self.count()
        share = i / (n - 1) if n > 1 else 0.0
        return self.HEIGHT / 2 + share * max(1, self.width() - self.HEIGHT)

    def shown_index(self) -> int:
        return self.target if self.dragging and self.target is not None else self.index()

    def paintEvent(self, event) -> None:
        t = theme.current()
        fg, gold = QColor(t["fg"]), QColor(t["accent"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = self.HEIGHT / 2
        track = QColor(t["card"])
        track.setAlpha(BACKDROP_ALPHA)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.HEIGHT), r, r)
        x = self._x_of(self.shown_index())
        gold.setAlpha(115)
        p.setBrush(gold)
        p.drawRoundedRect(QRectF(0, 0, x + r, self.HEIGHT), r, r)
        p.setBrush(fg)
        p.drawEllipse(QRectF(x - r + 2, 2, self.HEIGHT - 4, self.HEIGHT - 4))

    def _follow(self, x: float) -> None:
        self.target = self._index_at(x)
        self.tip.setText(f"{self.target + 1} / {self.count()} · {self.name(self.target)}")
        self.tip.adjustSize()
        centre = self.mapTo(self.tip.parentWidget(), QPoint(int(self._x_of(self.target)), 0))
        left = min(max(0, centre.x() - self.tip.width() // 2), self.tip.parentWidget().width() - self.tip.width())
        self.tip.move(left, centre.y() - self.tip.height() - 6)
        self.tip.show()
        self.tip.raise_()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.count() < 2:
            return
        self.dragging = True
        self._follow(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        self.floating.poke()
        if self.dragging:
            self._follow(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        if not self.dragging:
            return
        self.dragging = False
        self.tip.hide()
        target, self.target = self.target, None
        if target is not None and target != self.index():
            self.go(target)                                   # only the picture let go on is read
        self.update()

    def hideEvent(self, event) -> None:
        self.tip.hide()
        super().hideEvent(event)


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
        self.setStyleSheet(f"background: {backdrop()}; color: {fg.name()}; border-radius: 10px; padding: 3px 12px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)                     # a long message wraps inside the window instead of being cut at both ends
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
        room = max(120, self.host.width() - 40)
        self.setMaximumWidth(room)
        margins = self.contentsMargins()
        natural = self.fontMetrics().horizontalAdvance(text) + margins.left() + margins.right() + 26   # 26: the 12 px padding twice
        width = min(natural, room)                 # one line when it fits; wrapped (Qt alone would wrap it narrow) when it does not
        self.resize(width, self.heightForWidth(width))
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
