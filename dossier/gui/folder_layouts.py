"""Folder layouts in the window: columns, view mode, thumbnail size and sort order that belong to a folder (View > Folder Layout).

``core/layouts.py`` holds the rules and decides which one is in force for a folder. This file applies it when a folder is shown and
sends the owner's changes the right way: while a folder has a rule, changing its columns, view or sort changes *that rule*; with no
rule the change is the ordinary default, as before. Leaving a folder with a rule puts the panel back to the default. Nothing is
stored for folders the owner did not set; "Forget All Folder Layouts" empties the list.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from ..core.columns import DEFAULT_HIDDEN, DEFAULT_ORDER
from ..core.layouts import Layout, LayoutStore, Rule, has_rules_for

RULES_KEY = "layouts/rules"
SCOPE_WORDS = {"only": "this folder only", "tree": "this folder and its subfolders"}


class FolderLayoutsMixin:
    """Part of ``MainWindow``."""

    # the store ------------------------------------------------------------------------------------------------------------------
    def layout_store(self) -> LayoutStore:
        store = getattr(self, "_layout_store", None)
        if store is None:
            store = self._layout_store = LayoutStore.from_json(self.settings.value(RULES_KEY, ""))
        return store

    def _save_layouts(self) -> None:
        if len(self.layout_store()):
            self.settings.setValue(RULES_KEY, self.layout_store().to_json())
        else:
            self.settings.remove(RULES_KEY)

    def rule_for(self, panel) -> Optional[Rule]:
        """The rule in force for the folder this panel shows (None on the Home page, in archives and where nothing is set)."""
        if panel is None or panel.is_home or not has_rules_for(panel.path):
            return None
        return self.layout_store().find(panel.path)

    # reading and applying a layout ------------------------------------------------------------------------------------------------
    def live_layout(self, panel) -> Layout:
        """What the panel shows now, as a layout."""
        hidden = getattr(panel, "_col_hidden", set(DEFAULT_HIDDEN))
        order = getattr(panel, "_col_order", list(DEFAULT_ORDER))
        sort, desc = panel.current_sort()
        return Layout(sorted(hidden), list(order), panel.view_mode, panel.icon_px, sort, desc).cleaned()

    def default_view(self, panel) -> tuple:
        """The mode and size the owner chose as the ordinary view of this panel (the settings keep them while a rule is on)."""
        name = "left" if panel is self.left else "right"
        mode = str(self.settings.value(f"view/mode_{name}", "details"))
        try:
            px = int(self.settings.value(f"view/size_{name}", 128))
        except (TypeError, ValueError):
            px = 128
        return mode, px

    def apply_layout(self, panel, layout: Layout) -> None:
        panel._applying_layout = True
        try:
            panel.set_column_layout(set(layout.hidden), list(layout.order))
            panel.set_view_mode(layout.mode, layout.size)
            panel.set_sort(layout.sort, layout.desc)
        finally:
            panel._applying_layout = False

    def _back_to_default(self, panel) -> None:
        hidden, order = self.column_choice()
        panel._applying_layout = True
        try:
            panel.set_column_layout(hidden, order)
            mode, px = self.default_view(panel)
            panel.set_view_mode(mode, px)
        finally:
            panel._applying_layout = False
        if panel.sort_before_rule is not None:
            panel.set_sort(*panel.sort_before_rule)
        panel.sort_before_rule = None

    def _layout_for_folder(self, panel) -> None:
        """A panel showed a folder: apply the rule for it, or put the panel back to the default if the folder before had one."""
        rule = self.rule_for(panel)
        if rule is None:
            if panel.layout_rule_path:
                panel.layout_rule_path = ""
                self._back_to_default(panel)
        else:
            if not panel.layout_rule_path:
                panel.sort_before_rule = panel.current_sort()
            if self.live_layout(panel) != rule.layout.cleaned():
                self.apply_layout(panel, rule.layout)
            panel.layout_rule_path = rule.path
        self.update_layout_label()

    def update_layout_label(self) -> None:
        label = getattr(self, "layout_label", None)
        if label is None:
            return
        rule = self.rule_for(self.active) if hasattr(self, "active") else None
        label.setVisible(rule is not None)
        if rule is not None:
            label.setToolTip(f"This folder uses the layout saved for {rule.path} ({SCOPE_WORDS[rule.scope]}). Changes to the columns, "
                             "the view or the sorting here change that layout. View > Folder Layout goes back to the default.")

    # what the owner changes while a rule is in force -----------------------------------------------------------------------------
    def _sort_changed(self, panel) -> None:
        rule = self.rule_for(panel)
        if rule is not None:
            rule.layout.sort, rule.layout.desc = panel.current_sort()
            self._save_layouts()

    def _mode_changed_in_rule(self, panel) -> bool:
        """True when the mode or size the panel now shows belongs to its folder rule (and was kept there)."""
        rule = self.rule_for(panel)
        if rule is None:
            return False
        rule.layout.mode, rule.layout.size = panel.view_mode, panel.icon_px
        self._save_layouts()
        return True

    def build_layouts(self) -> None:
        for panel in (self.left, self.right):
            panel.folder_changed.connect(self._layout_for_folder)
            panel.sort_changed.connect(self._sort_changed)

    # View > Folder Layout ----------------------------------------------------------------------------------------------------------
    def add_layout_actions(self, view_menu) -> None:
        menu = view_menu.addMenu("Folder Layout")
        self.act_layout_only = QAction("Keep This Layout for This Folder Only", self)
        self.act_layout_only.triggered.connect(lambda: self.remember_layout("only"))
        self.act_layout_tree = QAction("Keep This Layout for This Folder and Its Subfolders", self)
        self.act_layout_tree.triggered.connect(lambda: self.remember_layout("tree"))
        self.act_layout_back = QAction("Back to the Default for This Folder", self)
        self.act_layout_back.triggered.connect(self.forget_this_layout)
        self.act_layout_all = QAction("Forget All Folder Layouts...", self)
        self.act_layout_all.triggered.connect(self.forget_all_layouts)
        for act in (self.act_layout_only, self.act_layout_tree, self.act_layout_back):
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(self.act_layout_all)
        menu.aboutToShow.connect(self._sync_layout_actions)

    def _sync_layout_actions(self) -> None:
        panel = self.active
        can = not panel.is_home and has_rules_for(panel.path)
        self.act_layout_only.setEnabled(can)
        self.act_layout_tree.setEnabled(can)
        self.act_layout_back.setEnabled(can and self.layout_store().exact(panel.path) is not None)
        self.act_layout_all.setEnabled(len(self.layout_store()) > 0)

    def remember_layout(self, scope: str) -> None:
        panel = self.active
        if panel.is_home or not has_rules_for(panel.path):
            self._say("The Home page, archives and search results cannot have a layout of their own")
            return
        if not panel.layout_rule_path:
            panel.sort_before_rule = panel.current_sort()          # what the panel goes back to when it leaves this folder
        rule = self.layout_store().set(panel.path, scope, self.live_layout(panel))
        self._save_layouts()
        panel.layout_rule_path = rule.path
        self.update_layout_label()
        self._say(f"{rule.path} keeps this layout ({SCOPE_WORDS[scope]})")

    def forget_this_layout(self) -> None:
        panel = self.active
        if not has_rules_for(panel.path) or not self.layout_store().remove(panel.path):
            self._say("This folder has no layout of its own" + (f"; it uses the one of {self.rule_for(panel).path}"
                                                                if self.rule_for(panel) is not None else ""))
            return
        self._save_layouts()
        self._layout_for_folder(panel)
        self._say("This folder is back to the default layout" if self.rule_for(panel) is None
                  else f"This folder now uses the layout of {self.rule_for(panel).path}")

    def forget_all_layouts(self) -> None:
        count = len(self.layout_store())
        if not count:
            return
        if not self.dialogs.confirm("Forget All Folder Layouts", f"Forget the layouts of {count} folder{'s' if count != 1 else ''}? "
                                    "Every folder goes back to the default columns, view and sorting.", "Forget"):
            return
        self.layout_store().clear()
        self._save_layouts()
        for panel in (self.left, self.right):
            self._layout_for_folder(panel)
        self._say("All folder layouts were forgotten")
