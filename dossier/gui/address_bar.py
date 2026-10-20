"""The address field of a panel: the path as clickable parts, or as text to type into.

Normally the field shows ``C: > Temp > Export`` as parts; a click on a part goes to that folder (a middle click opens
it in a new tab). A click on the empty end of the field, a double click, or Ctrl+L turns it into a line of text to
edit; Enter goes there, Esc or leaving the field returns to the parts. When the path is too long for the field the
leftmost parts fold into a "..." button whose menu lists them.
"""
from __future__ import annotations

from . import look

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QSizePolicy, QStackedLayout, QToolButton, QWidget

from ..core import pathparts

SEPARATOR = chr(0x203A)          # a single right-pointing angle quote


class _Crumb(QToolButton):
    middle_clicked = pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middle_clicked.emit()
            return
        super().mouseReleaseEvent(event)


class _Blank(QWidget):
    """The empty end of the field: a click there means "let me type"."""
    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _Page(QWidget):
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()


class _Keys(QObject):
    """Esc and losing the focus end the editing."""

    def __init__(self, bar: "AddressBar") -> None:
        super().__init__(bar)
        self._bar = bar

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._bar.finish_edit()
            self._bar.escaped.emit()
            return True
        if event.type() == QEvent.Type.FocusOut:
            self._bar.finish_edit()
        return False


class AddressBar(QWidget):
    navigate = pyqtSignal(str)             # a part was clicked: go to this folder
    navigate_new_tab = pyqtSignal(str)     # a part was middle-clicked
    escaped = pyqtSignal()                 # Esc ended the editing

    def __init__(self, fs, parent=None) -> None:
        super().__init__(parent)
        self.fs = fs
        self.path = ""
        self._parts: list = []
        self.line = QLineEdit()
        self.line.setObjectName("pathbar")
        self.line.installEventFilter(_Keys(self))
        self._page = _Page()
        self._page.double_clicked.connect(self.start_edit)
        self._row = QHBoxLayout(self._page)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        self._blank = _Blank()
        self._blank.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._blank.clicked.connect(self.start_edit)
        self._blank.setToolTip("Click to type a path (Ctrl+L)")
        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addWidget(self._page)
        stack.addWidget(self.line)
        self._stack = stack
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(80)

    # what is shown -------------------------------------------------------------------------------------------
    @property
    def editing(self) -> bool:
        return self._stack.currentIndex() == 1

    def set_path(self, path: str) -> None:
        """Show ``path``. Typing in progress is left alone; the parts behind it are brought up to date."""
        self.path = path
        if not self.editing:
            self.line.setText(path)
        self._parts = pathparts.segments(self.fs, path)
        self._rebuild()

    def parts(self) -> list:
        """(label, path) of every part, for tests and tooltips."""
        return list(self._parts)

    def _clear(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._blank:
                widget.hide()                       # hidden first: a parentless widget would otherwise show up as a window
                widget.setParent(None)              # gone from the field at once, freed when the loop gets to it
                widget.deleteLater()
        self._blank.setParent(None)

    def _rebuild(self) -> None:
        self._clear()
        shown = list(self._parts)
        hidden: list = []
        bold = self.font()
        bold.setBold(look.bold_bars)
        metrics = QFontMetrics(bold)
        room = max(0, self.width() - 40)

        def width_of(parts) -> int:
            return sum(metrics.horizontalAdvance(label) + 24 for label, _p in parts)

        while len(shown) > 1 and width_of(shown) + (28 if hidden else 0) > room and self.width() > 0:
            hidden.append(shown.pop(0))
        if hidden:
            more = QToolButton()
            more.setObjectName("crumb")
            more.setText("...")
            more.setToolTip("The folders above")
            more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(more)
            for label, target in reversed(hidden):
                menu.addAction(label).triggered.connect(lambda _c=False, t=target: self.navigate.emit(t))
            more.setMenu(menu)
            self._row.addWidget(more)
            self._row.addWidget(self._separator())
        for i, (label, target) in enumerate(shown):
            button = _Crumb()
            button.setObjectName("crumb")
            button.setText(label)
            button.setToolTip(target)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoRaise(True)
            button.clicked.connect(lambda _c=False, t=target: self.navigate.emit(t))
            button.middle_clicked.connect(lambda t=target: self.navigate_new_tab.emit(t))
            self._row.addWidget(button)
            if i < len(shown) - 1:
                self._row.addWidget(self._separator())
        self._row.addWidget(self._blank, 1)

    @staticmethod
    def _separator() -> QLabel:
        label = QLabel(SEPARATOR)
        label.setObjectName("crumbsep")
        label.setContentsMargins(1, 0, 1, 0)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return label

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._parts:
            self._rebuild()

    # editing -------------------------------------------------------------------------------------------------
    def start_edit(self) -> None:
        self.line.setText(self.path)
        self._stack.setCurrentIndex(1)
        self.line.setFocus()
        self.line.selectAll()

    def finish_edit(self) -> None:
        if self.editing:
            self._stack.setCurrentIndex(0)
            self.line.setText(self.path)
