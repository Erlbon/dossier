"""Moving the tools bar: drag its grip to the menu bar's row, to the row under the menu bar, or to the bottom (View > Tools Bar Position
does the same without the mouse). The place is remembered.

While the grip is dragged an accent-coloured strip shows where the bar will land.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QFrame

from ..core import barplace
from . import theme


class ToolsBarPlaceMixin:
    """Part of ``MainWindow``."""

    def tools_bar_place(self) -> str:
        return barplace.clean(str(self.settings.value("view/tools_bar_place", barplace.DEFAULT)))

    def build_tools_bar_place_menu(self, parent_menu) -> None:
        menu = parent_menu.addMenu("Tools Bar Position")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tools_bar_place_actions = {}
        for key, label in barplace.PLACES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.tools_bar_place() == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_tools_bar_place(k))
            group.addAction(act)
            menu.addAction(act)
            self.tools_bar_place_actions[key] = act
        menu.addSeparator()
        menu.addAction("Drag the dots at the left end of the bar to move it").setEnabled(False)

    def set_tools_bar_place(self, place: str, save: bool = True) -> None:
        """Put the bar in ``place``: take it out of where it is (the menu bar's corner or the window's column) and put it in again."""
        place = barplace.clean(place)
        bar = self.tools_bar
        self.menuBar().setCornerWidget(None, Qt.Corner.TopRightCorner)
        self.centralWidget().layout().removeWidget(bar)
        bar.setParent(None)
        column = self.centralWidget().layout()
        if place == "menu_row":
            self.menuBar().setCornerWidget(bar, Qt.Corner.TopRightCorner)
        elif place == "bottom":
            column.insertWidget(column.indexOf(self.split) + 1, bar)
        else:
            column.insertWidget(0, bar)
        bar.set_place(place)
        bar.setVisible(str(self.settings.value("view/tools_bar", "true")).lower() == "true")
        self._fit_tools_bar()
        if hasattr(self, "tools_bar_place_actions") and place in self.tools_bar_place_actions:
            self.tools_bar_place_actions[place].setChecked(True)
        if save:
            self.settings.setValue("view/tools_bar_place", place)

    def _fit_tools_bar(self) -> None:
        """In the menu bar's row the bar takes the room the menus leave, so its buttons start right after the menus."""
        bar = self.tools_bar
        menus = self.menuBar()
        if bar.place != "menu_row":
            bar.wanted_width = 0
            return
        actions = menus.actions()
        used = menus.actionGeometry(actions[-1]).right() + 12 if actions else 0
        bar.wanted_width = max(self.width() - used, 0)          # the menu bar is as wide as the window
        bar.updateGeometry()
        menus.updateGeometry()
        menus.resize(menus.size())                     # the menu bar lays its corner widget out again

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        bar = getattr(self, "tools_bar", None)
        if bar is not None and bar.place == "menu_row":
            self._fit_tools_bar()

    # dragging ------------------------------------------------------------------------------------------------------------------
    def _tools_bar_dragging(self, global_pos) -> None:
        place = self._place_under(global_pos)
        strip = self._drop_strip()
        strip.setGeometry(self._strip_rect(place))
        strip.show()
        strip.raise_()
        self._drop_place = place

    def _tools_bar_dropped(self, global_pos) -> None:
        place = self._place_under(global_pos)
        self._drop_strip().hide()
        if place != self.tools_bar.place:
            self.set_tools_bar_place(place)

    def _place_under(self, global_pos) -> str:
        y = self.mapFromGlobal(global_pos).y()
        menu_bottom = self.menuBar().geometry().bottom() + 1
        top = self.split.mapTo(self, QPoint(0, 0)).y()
        return barplace.place_at(y, menu_bottom, top, top + self.split.height())

    def _drop_strip(self) -> QFrame:
        strip = getattr(self, "_strip", None)
        if strip is None:
            strip = self._strip = QFrame(self)
            strip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            strip.hide()
        strip.setStyleSheet(f"background:{theme.current()['accent']};")
        return strip

    def _strip_rect(self, place: str) -> QRect:
        menus = self.menuBar()
        if place == "menu_row":
            actions = menus.actions()
            left = menus.actionGeometry(actions[-1]).right() + 12 if actions else 0
            return QRect(left, 0, max(self.width() - left, 40), menus.height())
        top = self.split.mapTo(self, QPoint(0, 0)).y()
        if place == "below_menu":
            return QRect(0, max(top - 3, 0), self.width(), 4)
        return QRect(0, top + self.split.height() - 1, self.width(), 4)
