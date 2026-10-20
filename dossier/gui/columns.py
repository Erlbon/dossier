"""Which columns the folder listings show and in which order: Settings > Columns..., and a right-click on a column header.

The dialog and the header menu are the shared ones of redactor_common (the same ones the Redactor apps use); this file only
keeps the choice. It is stored by column NAME in the settings, one choice for both panels. Name and Type cannot be hidden.
"""
from __future__ import annotations

from redactor_common.core.table_settings import is_column_visible, sanitize_hidden_fields
from redactor_common.gui.column_menu import show_column_header_context_menu
from redactor_common.gui.column_settings_dialog import ColumnSettingsDialog

from ..core.columns import DEFAULT_HIDDEN, DEFAULT_ORDER, KEYS, LABELS, PROTECTED

HIDDEN_KEY = "view/columns_hidden"
ORDER_KEY = "view/columns_order"


class ColumnsMixin:
    """Part of ``MainWindow``."""

    def _read_names(self, key: str, default) -> list:
        value = self.settings.value(key, None)
        if value is None:
            return list(default)
        text = ",".join(value) if isinstance(value, list) else str(value)
        return [n for n in (p.strip() for p in text.split(",")) if n in KEYS]

    def column_choice(self) -> tuple:
        """``(hidden names, order of names)`` as the user left them (the defaults at first)."""
        hidden = sanitize_hidden_fields(set(self._read_names(HIDDEN_KEY, DEFAULT_HIDDEN)), PROTECTED)
        order = self._read_names(ORDER_KEY, DEFAULT_ORDER)
        order += [k for k in DEFAULT_ORDER if k not in order]                 # a column added in a later version
        return hidden, order

    def _store_columns(self, hidden: set, order: list) -> None:
        self.settings.setValue(HIDDEN_KEY, ",".join(k for k in KEYS if k in hidden) or "-")
        self.settings.setValue(ORDER_KEY, ",".join(order))

    def apply_columns_everywhere(self) -> None:
        hidden, order = self.column_choice()
        for panel in (self.left, self.right):
            panel.set_column_layout(hidden, order)

    def _column_toggled(self, key: str, visible: bool) -> None:
        hidden, order = self.column_choice()
        (hidden.discard if visible else hidden.add)(key)
        self._store_columns(sanitize_hidden_fields(hidden, PROTECTED), order)
        self.apply_columns_everywhere()

    def _columns_dragged(self, panel) -> None:
        hidden, _old = self.column_choice()
        order = panel.column_keys_in_order()
        self._store_columns(hidden, order)
        self.apply_columns_everywhere()                        # the other panel follows

    HOME_NOTE = ("The Home page has its own three columns (Name, Type, Details). Your column choice applies to the folders you open; "
                 "it is kept.")

    def show_column_menu(self, panel, pos) -> None:
        if panel.is_home:
            self._say(self.HOME_NOTE)
            return
        hidden, order = self.column_choice()
        show_column_header_context_menu(
            self, panel.table, pos, column_order=order, label_lookup=LABELS, protected_columns=PROTECTED,
            hidden_fields=hidden, is_visible=lambda k, h: is_column_visible(k, h, PROTECTED),
            on_toggle=self._column_toggled, open_column_settings_dialog=self.open_column_settings)

    def open_column_settings(self) -> None:
        hidden, order = self.column_choice()
        dlg = ColumnSettingsDialog([(k, LABELS[k]) for k in order], hidden, PROTECTED, self)
        self._run_column_dialog(dlg)
        self._store_columns(sanitize_hidden_fields(dlg.hidden_fields(), PROTECTED), dlg.column_order())
        self.apply_columns_everywhere()
        if self.active.is_home:
            self._say(self.HOME_NOTE)

    def _run_column_dialog(self, dlg) -> None:                 # a seam for tests
        dlg.exec()

    def reset_columns(self) -> None:
        self._store_columns(set(DEFAULT_HIDDEN), list(DEFAULT_ORDER))
        self.apply_columns_everywhere()
        self._say("Columns are back to the defaults")
