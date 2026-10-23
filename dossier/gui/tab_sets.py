"""View > Tabs > Save Tab Set As..., Open Tab Set, Add Tab Set, Forget Tab Set: named lists of a panel's tab folders (``core/tabsets.py``).

Opening a set replaces the active panel's tabs (like the saved session does); adding opens its folders as more tabs next to the ones
there. The two submenus and Forget list the saved names each time the menu opens, as the saved selections of the Mark menu do.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMenu

from ..core.tabsets import TabSetStore

SETS_KEY = "tabsets/sets"


class TabSetsMixin:
    """Part of ``MainWindow``."""

    def tab_set_store(self) -> TabSetStore:
        store = getattr(self, "_tab_set_store", None)
        if store is None:
            store = self._tab_set_store = TabSetStore.from_json(self.settings.value(SETS_KEY, ""))
        return store

    def _save_tab_sets(self) -> None:
        if len(self.tab_set_store()):
            self.settings.setValue(SETS_KEY, self.tab_set_store().to_json())
        else:
            self.settings.remove(SETS_KEY)

    def save_tab_set(self) -> None:
        panel = self.active
        paths = panel.tab_paths()
        name = self.dialogs.ask_text("Save Tab Set", f"A name for these {len(paths)} tab{'s' if len(paths) != 1 else ''}:",
                                     f"tabs {len(self.tab_set_store()) + 1}")
        if not name or not name.strip():
            return
        saved = self.tab_set_store().save(name.strip(), paths, panel.tabs.currentIndex())
        if saved is None:
            self._say("Nothing to save")
            return
        self._save_tab_sets()
        self._say(f"Saved {len(saved.paths)} tab{'s' if len(saved.paths) != 1 else ''} as {saved.name}")

    def open_tab_set(self, name: str, add: bool = False) -> None:
        tab_set = self.tab_set_store().get(name)
        if tab_set is None:
            self._say(f"No saved tab set named {name}")
            return
        panel = self.active
        if add:
            first = panel.tabs.count()
            for path in tab_set.paths:
                panel.append_tab(path)
            panel.tabs.setCurrentIndex(first + tab_set.active)
            self._say(f"Added the {len(tab_set.paths)} tab{'s' if len(tab_set.paths) != 1 else ''} of {name}")
        else:
            panel.restore_tabs(tab_set.paths, tab_set.active)
            self._say(f"Opened the {len(tab_set.paths)} tab{'s' if len(tab_set.paths) != 1 else ''} of {name}")

    def forget_tab_set(self, name: str) -> None:
        if self.tab_set_store().forget(name):
            self._save_tab_sets()
            self._say(f"Forgot the tab set {name}")

    def build_tab_set_menus(self, open_menu: QMenu, add_menu: QMenu, forget_menu: QMenu) -> None:
        """Fill the three submenus with the saved names (called each time the Tabs menu opens)."""
        names = self.tab_set_store().names()
        for menu, handler in ((open_menu, lambda n: self.open_tab_set(n)), (add_menu, lambda n: self.open_tab_set(n, True)),
                              (forget_menu, self.forget_tab_set)):
            menu.clear()
            if not names:
                menu.addAction("Nothing saved yet").setEnabled(False)
            for n in names:
                menu.addAction(n.replace("&", "&&")).triggered.connect(lambda _c=False, n=n, h=handler: h(n))
