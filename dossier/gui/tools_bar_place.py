"""Moving the bars: the programs bar, the function key bar (F2 ... F8) and the command line.

Drag the dots at the left end of a bar, or use the View menu. The programs bar can sit in the menu bar's row, under the menu bar or at the
bottom; the function key bar and the command line sit above the panels or under them. Each bar's place is remembered. While a bar is
dragged an accent-coloured strip shows where it will land.

The window's column is: the bars above the panels, the panels, the bars under the panels, the status line. ``_arrange_column`` puts the
bars in that order after every move.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QFrame

from ..core import barplace
from . import theme

SETTING = {"tools": "view/tools_bar_place", "fkeys": "view/fkeys_place", "command": "view/command_place"}
TITLE = {"tools": "Programs Bar", "fkeys": "Function Key Bar (F2 ... F8)", "command": "Command Line"}
NAME = {"fkeys": "Function Keys", "command": "Command Line"}
ORDER = ("tools", "command", "fkeys")            # the order of the bars inside a group
ABOVE = ("below_menu", "top")


class ToolsBarPlaceMixin:
    """Part of ``MainWindow``."""

    # places ---------------------------------------------------------------------------------------------------------------------
    def bar_widget(self, name: str):
        return {"tools": self.tools_bar, "command": self.command_row, "fkeys": self.fkeys}[name]

    def bar_place(self, name: str) -> str:
        stored = str(self.settings.value(SETTING[name], barplace.DEFAULT if name == "tools" else barplace.FKEY_DEFAULT))
        return barplace.clean(stored) if name == "tools" else barplace.fkey_clean(stored)

    def tools_bar_place(self) -> str:
        return self.bar_place("tools")

    def set_tools_bar_place(self, place: str, save: bool = True) -> None:
        self.set_bar_place("tools", place, save)

    def set_bar_place(self, name: str, place: str, save: bool = True) -> None:
        place = barplace.clean(place) if name == "tools" else barplace.fkey_clean(place)
        self._places = getattr(self, "_places", {})
        self._places[name] = place
        self._arrange_column()
        if name == "tools":
            self.tools_bar.set_place(place)
            self._fit_tools_bar()
        actions = getattr(self, "bar_place_actions", {}).get(name, {})
        if place in actions:
            actions[place].setChecked(True)
        if save:
            self.settings.setValue(SETTING[name], place)

    def _arrange_column(self) -> None:
        """Take the three movable bars out of the window's column and put them back in the order the places say."""
        column = self.centralWidget().layout()
        places = {name: getattr(self, "_places", {}).get(name) or self.bar_place(name) for name in ORDER}
        self.menuBar().setCornerWidget(None, Qt.Corner.TopRightCorner)
        for name in ORDER:
            column.removeWidget(self.bar_widget(name))
            self.bar_widget(name).setParent(None)
        for name in ORDER:
            if places[name] == "menu_row":
                self.menuBar().setCornerWidget(self.bar_widget(name), Qt.Corner.TopRightCorner)
            elif places[name] in ABOVE:
                column.insertWidget(column.indexOf(self.split), self.bar_widget(name))
        for name in ORDER:
            if places[name] == "bottom":
                column.insertWidget(column.count() - 1, self.bar_widget(name))      # the last item is the status line
        for name in ("command", "fkeys"):
            self.bar_widget(name).show()                                             # parentless for a moment: show again
        self.tools_bar.setVisible(str(self.settings.value("view/tools_bar", "true")).lower() == "true")

    def build_bar_place_menus(self, parent_menu) -> None:
        """View > Bar Positions: one submenu with a group for each movable bar."""
        menu = parent_menu.addMenu("Bar Positions")
        self.bar_place_actions = {}
        for name in ("tools", "fkeys", "command"):
            menu.addSection(TITLE[name])
            group = QActionGroup(self)
            group.setExclusive(True)
            self.bar_place_actions[name] = {}
            for key, label in (barplace.PLACES if name == "tools" else barplace.FKEY_PLACES):
                text = label if name == "tools" else f"{NAME[name]} {label[0].lower()}{label[1:]}"     # "Command Line at the Bottom"
                act = QAction(text, self)
                act.setCheckable(True)
                act.setChecked(self.bar_place(name) == key)
                act.triggered.connect(lambda _c=False, n=name, k=key: self.set_bar_place(n, k))
                group.addAction(act)
                menu.addAction(act)
                self.bar_place_actions[name][key] = act
        menu.addSeparator()
        menu.addAction("Or drag the dots at the left end of a bar").setEnabled(False)
        self.tools_bar_place_actions = self.bar_place_actions["tools"]

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
        menus.resize(menus.size())                              # the menu bar lays its corner widget out again

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        bar = getattr(self, "tools_bar", None)
        if bar is not None and bar.place == "menu_row":
            self._fit_tools_bar()

    # dragging ------------------------------------------------------------------------------------------------------------------
    def _bar_dragging(self, name: str, global_pos) -> None:
        place = self._place_under(name, global_pos)
        strip = self._drop_strip()
        strip.setGeometry(self._strip_rect(place))
        strip.show()
        strip.raise_()
        self._drop_place = place

    def _bar_dropped(self, name: str, global_pos) -> None:
        place = self._place_under(name, global_pos)
        self._drop_strip().hide()
        if place != getattr(self, "_places", {}).get(name, self.bar_place(name)):
            self.set_bar_place(name, place)

    def _tools_bar_dragging(self, global_pos) -> None:
        self._bar_dragging("tools", global_pos)

    def _tools_bar_dropped(self, global_pos) -> None:
        self._bar_dropped("tools", global_pos)

    def _place_under(self, name: str, global_pos) -> str:
        y = self.mapFromGlobal(global_pos).y()
        top = self.split.mapTo(self, QPoint(0, 0)).y()
        if name == "tools":
            return barplace.place_at(y, self.menuBar().geometry().bottom() + 1, top, top + self.split.height())
        return barplace.half_place_at(y, top, top + self.split.height())

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
        if place in ABOVE:
            return QRect(0, max(top - 3, 0), self.width(), 4)
        return QRect(0, top + self.split.height() - 1, self.width(), 4)
