"""Batch rename: the shared dialogs of the Redactor apps (``redactor_common``), fed with the files marked in the panel.

Dossier writes no rename logic of its own. The pattern dialog (``%placeholders%``, optional groups, zero padding,
ASCII-safe names, a preview of every new name), the search and replace dialog, the case dialog and the numbering dialog are
the ones the Redactors use; this module only says what the items are, which values they have, and what to do with the
answers: the new names go through Dossier's own rename plan (conflicts are never overwritten, the renames can be undone
with Ctrl+Z, marks follow the files).
"""
from __future__ import annotations

import os
import time
from typing import Optional

from PyQt6.QtWidgets import QDialog

from ..core.ops import plan_rename_many

# What a file can offer a pattern. Everything here is a fact about the file itself; the metadata of a file's content
# (title, artist, ...) belongs to the metadata work and will add its own placeholders.
PLACEHOLDERS = [
    ("name", "File name (without extension)"),
    ("folder", "Name of the folder it is in"),
    ("counter", "Counter (1, 2, 3 ... in the order of the list)"),
    ("year", "Year modified"),
    ("month", "Month modified"),
    ("day", "Day modified"),
    ("hour", "Hour modified"),
    ("minute", "Minute modified"),
    ("second", "Second modified"),
]
ALWAYS_PAD = {"month": 2, "day": 2, "hour": 2, "minute": 2, "second": 2}
HISTORY_KEY = "rename/pattern_history"


def file_values(entry, path: str, index: int) -> dict:
    """The placeholder values of one file. ``entry.mtime`` is local time of the modification."""
    stem = os.path.splitext(os.path.basename(path))[0]
    when = time.localtime(entry.mtime) if entry.mtime else None
    return {
        "name": stem,
        "folder": os.path.basename(os.path.dirname(path)),
        "counter": str(index + 1),
        "year": str(when.tm_year) if when else "",
        "month": str(when.tm_mon) if when else "",
        "day": str(when.tm_mday) if when else "",
        "hour": str(when.tm_hour) if when else "",
        "minute": str(when.tm_min) if when else "",
        "second": str(when.tm_sec) if when else "",
    }


def split_name(entry) -> tuple:
    """(stem, extension with its dot) of an entry; a folder has no extension."""
    name = os.path.basename(entry.path)
    return (name, "") if entry.is_dir else os.path.splitext(name)


class BatchRenameMixin:
    """Part of ``MainWindow``: Commands > Batch Rename."""

    def _entries_to_rename(self, files_only: bool = False) -> Optional[list]:
        """The marked items of the active panel in the order of its list (the order a counter counts in)."""
        panel = self.active
        if panel.is_home:
            return None
        entries = panel.marked_in_view_order()
        skipped = 0
        if files_only:
            skipped = sum(1 for e in entries if e.is_dir)
            entries = [e for e in entries if not e.is_dir]
        if not entries:
            self._say("Mark the files to rename first (Space, or Ctrl+F for a pattern)")
            return None
        if skipped:
            self._say(f"{skipped} folder{'s' if skipped != 1 else ''} left out: this renames files")
        return entries

    def _apply_renames(self, pairs: list) -> None:
        """Rename ``(path, new_name)`` pairs through the normal rename plan (so Ctrl+Z puts them back)."""
        pairs = [(old, new) for old, new in pairs if new and new != os.path.basename(old)]
        if not pairs:
            self._say("Nothing to rename: every name stays as it is")
            return
        plan = plan_rename_many(self.fs, pairs)
        if plan.blocking:
            self.dialogs.info("Batch Rename", chr(10).join(plan.blocking[:8]))
            return
        if plan.conflicts:
            names = [self.fs.basename(plan.ops[i].dst) for i in plan.conflicts[:8]]
            self.dialogs.info("Batch Rename", f"{len(plan.conflicts)} new names are taken or repeat:{chr(10)}" + chr(10).join(names))
            return
        self._run(plan)

    # ---------------------------------------------------------------------------------------------------------
    def rename_by_pattern(self) -> None:
        entries = self._entries_to_rename(files_only=True)
        if entries is None:
            return
        from redactor_common.core.pattern_history import dedupe_and_trim, decode_history, encode_history
        from redactor_common.gui.rename_pattern_dialog import RenamePatternDialog
        values = {e.path: file_values(e, e.path, i) for i, e in enumerate(entries)}
        history = decode_history(str(self.settings.value(HISTORY_KEY, "") or ""))
        pad = str(self.settings.value("rename/pad_counter", "false")).lower() == "true"
        width = int(self.settings.value("rename/pad_width", 2) or 2)
        dialog = RenamePatternDialog(
            entries, PLACEHOLDERS, lambda e: values[e.path], lambda e: e.path, history, "%name%",
            title="Batch Rename by Pattern", item_noun="file", zero_pad_field="counter", zero_pad_label="Zero-pad the counter to:",
            zero_pad_widths=(1, 2, 3, 4, 5), always_pad_fields=ALWAYS_PAD,
            ascii_only=str(self.settings.value("rename/ascii", "false")).lower() == "true",
            on_ascii_only_changed=lambda on: self.settings.setValue("rename/ascii", "true" if on else "false"),
            zero_pad_initial=(pad, width),
            on_zero_pad_changed=lambda on, w: (self.settings.setValue("rename/pad_counter", "true" if on else "false"),
                                              self.settings.setValue("rename/pad_width", w)),
            parent=self)
        for name in ("export_radio", "choose_folder_btn", "folder_label", "move_radio", "choose_root_btn", "root_label"):
            getattr(dialog, name).hide()                       # Dossier renames in place; copying and moving are its own commands
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.setValue(HISTORY_KEY, encode_history(dedupe_and_trim(history, dialog.pattern_edit.text())))
        self._apply_renames([(old, os.path.basename(new)) for _item, old, new in dialog.planned_renames()])

    def rename_search_replace(self) -> None:
        entries = self._entries_to_rename()
        if entries is None:
            return
        from redactor_common.gui.search_replace_dialog import SearchReplaceDialog
        dialog = SearchReplaceDialog(entries, [], lambda e, _key: os.path.basename(e.path), lambda e: os.path.basename(e.path),
                                     include_filename=True, item_noun="item", parent=self)
        dialog.setWindowTitle("Batch Rename: Search and Replace in Names")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_renames([(entries[i].path, new) for i, new in dialog.accepted_changes().items()])

    def rename_case(self) -> None:
        entries = self._entries_to_rename()
        if entries is None:
            return
        from redactor_common.gui.case_conversion_dialog import CaseConversionDialog
        dialog = CaseConversionDialog(entries, [("name", "File name (the extension is kept)")],
                                      lambda e, _key: split_name(e)[0], lambda e: os.path.basename(e.path),
                                      item_noun="item", parent=self)
        dialog.setWindowTitle("Batch Rename: Change Case")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_renames([(entries[i].path, new + split_name(entries[i])[1]) for i, new in dialog.accepted_changes().items()])

    def rename_number(self) -> None:
        entries = self._entries_to_rename()
        if entries is None:
            return
        from redactor_common.gui.auto_numbering_dialog import AutoNumberingDialog
        dialog = AutoNumberingDialog(
            entries, [("name", "File name (the extension is kept)", False)], lambda e, _key: split_name(e)[0],
            lambda e: os.path.basename(e.path), item_noun="item",
            padding=int(self.settings.value("rename/number_padding", 2) or 2),
            on_padding_changed=lambda w: self.settings.setValue("rename/number_padding", w), parent=self)
        dialog.setWindowTitle("Batch Rename: Number the Files")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_renames([(entries[i].path, new + split_name(entries[i])[1]) for i, new in dialog.accepted_changes().items()])
