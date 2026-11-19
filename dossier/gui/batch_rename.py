"""Batch rename: the shared dialogs of the Redactor apps (``redactor_common``), fed with the files marked in the panel.

Dossier writes no rename logic of its own. The pattern dialog (``%placeholders%``, optional groups, zero padding,
ASCII-safe names, a preview of every new name), the search and replace dialog, the case dialog and the numbering dialog are
the ones the Redactors use; this module only says what the items are, which values they have, and what to do with the
answers: the new names go through Dossier's own rename plan (conflicts are never overwritten, the renames can be undone
with Ctrl+Z, marks follow the files).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from typing import Optional

from PyQt6.QtWidgets import QDialog

from ..core import rename_text, stage
from ..core.ops import plan_rename_many
from ..core.rename_text import plan_text_renames
from .background import run_in_background

# What a file can offer a pattern: facts about the file itself, then the tags Dossier already reads (TAG_PLACEHOLDERS), which are
# empty for a file that has no such tag.
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
TAG_PLACEHOLDERS = [
    ("artist", "Artist (music tags)"),
    ("album", "Album (music tags)"),
    ("title", "Title (music, comic or video tags)"),
    ("track", "Track number (music tags)"),
    ("tagyear", "Year in the tags"),
    ("series", "Series (comic tags)"),
    ("number", "Issue number (comic tags)"),
    ("taken", "Date a photo was taken (EXIF), 2019-05-17"),
]
PLACEHOLDERS += TAG_PLACEHOLDERS
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp", ".heic")
ALWAYS_PAD = {"month": 2, "day": 2, "hour": 2, "minute": 2, "second": 2}
HISTORY_KEY = "rename/pattern_history"
TEXT_HEADER_KEY = "rename/text_header"


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


def has_tags(path: str) -> bool:
    """Whether a file can carry tags these placeholders read (music, comic, video, photo)."""
    from ..core.properties import kind_of
    return bool(kind_of(path)) or path.lower().endswith(PHOTO_EXTENSIONS)


def tag_values(path: str) -> dict:
    """The tag placeholders of one file (all empty when it has none). Opens the file: called on a thread."""
    from ..core.exif import read_exif
    from ..core.filetimes import parse_exif_date
    from ..core.metacolumns import read_values
    from ..core.properties import kind_of
    out = {key: "" for key, _label in TAG_PLACEHOLDERS}
    kind = kind_of(path)
    if kind:
        v = read_values(path, {kind})
        out.update(artist=v.get("m_artist", ""), album=v.get("m_album", ""), title=v.get("m_title", ""),
                   track=v.get("m_track", ""), tagyear=v.get("m_year", ""), series=v.get("m_series", ""),
                   number=v.get("m_number", ""))
    elif path.lower().endswith(PHOTO_EXTENSIONS):
        exif = read_exif(path)
        when = parse_exif_date(exif.get("Date taken") or exif.get("Date digitized"))
        if when is not None:
            out["taken"] = time.strftime("%Y-%m-%d", time.localtime(when))
    return {k: v.replace("/", "-").replace(chr(92), "-") for k, v in out.items()}       # a tag never makes a folder


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
        if panel.target_override is not None:                       # started from the right-click menu: the items it was on
            wanted = set(panel.target_override)
            entries = [e for e in (panel.model.entry_at(r) for r in range(panel.model.entry_count()))
                       if e is not None and e.path in wanted and e.name != ".."]
        skipped = 0
        if files_only:
            skipped = sum(1 for e in entries if e.is_dir)
            entries = [e for e in entries if not e.is_dir]
        if not entries:
            self._say("Mark the files to rename first (Space, or + for a pattern)")
            return None
        if skipped:
            self._say(f"{skipped} folder{'s' if skipped != 1 else ''} left out: this renames files")
        return entries

    def _apply_renames(self, pairs: list, planner=None) -> None:
        """Rename ``(path, new_name)`` pairs through the normal rename plan (so Ctrl+Z puts them back)."""
        pairs = [(old, new) for old, new in pairs if new and new != os.path.basename(old)]
        if not pairs:
            self._say("Nothing to rename: every name stays as it is")
            return

        def go(plan) -> None:                                    # two looks at the disk per name: made on a thread, shown here
            if plan.blocking:
                self.dialogs.info("Batch Rename", chr(10).join(plan.blocking[:8]))
                return
            if plan.conflicts:
                names = [self.fs.basename(plan.ops[i].dst) for i in plan.conflicts[:8]]
                self.dialogs.info("Batch Rename", f"{len(plan.conflicts)} new names are taken or repeat:{chr(10)}" + chr(10).join(names))
                return
            self._run(plan)
        self._plan_in_background("Preparing the renames", lambda watch: (planner or plan_rename_many)(self.fs, pairs), go)

    # ---------------------------------------------------------------------------------------------------------
    def rename_by_pattern(self) -> None:
        entries = self._entries_to_rename(files_only=True)
        if entries is None:
            return
        tagged = [e.path for e in entries if has_tags(e.path) and not e.path.startswith(("zip:", "sftp:", "scp:", "webdav:", "ftp:"))]
        if not tagged:
            self._rename_by_pattern_with(entries, {})
            return

        def work(progress, cancel):                              # the tags are read before the dialog opens, so its preview has them
            out = {}
            for i, path in enumerate(tagged):
                cancel.check()
                progress(i, len(tagged))
                out[path] = tag_values(path)
            return out
        run_in_background(self, self.cmd_runner, "Reading the tags", work, on_result=lambda tags: self._rename_by_pattern_with(entries, tags),
                          tracked=self._size_jobs, failed_title="Batch Rename")

    def _rename_by_pattern_with(self, entries: list, tags: dict) -> None:
        from redactor_common.core.pattern_history import dedupe_and_trim, decode_history, encode_history
        from redactor_common.gui.rename_pattern_dialog import RenamePatternDialog
        empty = {key: "" for key, _label in TAG_PLACEHOLDERS}
        values = {e.path: {**file_values(e, e.path, i), **tags.get(e.path, empty)} for i, e in enumerate(entries)}
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

    # Edit the names as text (card 63) -----------------------------------------------------------------------
    def text_rename_header(self) -> bool:
        return str(self.settings.value(TEXT_HEADER_KEY, "true")).lower() != "false"

    def set_text_rename_header(self, on: bool) -> None:
        self.settings.setValue(TEXT_HEADER_KEY, "true" if on else "false")

    def _text_waits(self) -> dict:
        """Name lists open in the notepad: normalised path -> what to do when that window closes (see ``_edit_prepared``)."""
        return self.__dict__.setdefault("_text_rename_waits", {})

    def rename_as_text(self) -> None:
        """Write the names of the marked items to a temporary text file, one per line, open it in the F4 editor, and rename what the
        user changed once the editing is over. For the notepad that is when its window closes; for another program Dossier cannot see
        it end, so a box says "Done editing"."""
        entries = self._entries_to_rename()
        if entries is None:
            return
        paths = [e.path for e in entries]
        header = self.text_rename_header()

        def work(progress, cancel):                                  # reads the folder and writes the file: on a thread
            snap = rename_text.snapshot(self.fs, paths)
            os.makedirs(stage.stage_root(), exist_ok=True)
            folder = tempfile.mkdtemp(dir=stage.stage_root())
            file = os.path.join(folder, "names.txt")
            with open(file, "w", encoding="utf-8", newline="") as f:
                f.write(rename_text.render(snap, header))
            return snap, file

        run_in_background(self, self.cmd_runner, "Writing the names", self._catching(work), on_result=self._text_started,
                          tracked=self._size_jobs, indeterminate=True, failed_title="Batch Rename")

    @staticmethod
    def _catching(work):
        """Turn a ``RenameTextError`` raised on the thread into a message handed back (``("error", text)``), so it is shown plainly."""
        def wrapped(progress, cancel):
            try:
                return work(progress, cancel)
            except rename_text.RenameTextError as e:
                return "error", str(e)
        return wrapped

    def _text_started(self, result) -> None:
        if result[0] == "error":
            self.dialogs.info("Edit the Names as Text", result[1])
        else:
            self._open_name_list(*result)

    def _open_name_list(self, snap, file: str) -> None:
        done = {"yes": False}

        def finish() -> None:
            if not done["yes"]:
                done["yes"] = True
                self._text_waits().pop(os.path.normcase(file), None)
                self._read_name_list(snap, file)

        def abandon() -> None:
            done["yes"] = True
            self._text_waits().pop(os.path.normcase(file), None)
            self._remove_name_list(file)

        if self.editor_program():
            self.edit_in_program(file)
            if self.dialogs.confirm("Edit the Names as Text",
                                    "Edit the names in the program that was just opened, one per line. Save the file, then press "
                                    "Done editing. Do not add, remove or reorder lines.", "Done editing"):
                finish()
            else:
                abandon()
            return
        self._text_waits()[os.path.normcase(file)] = finish           # the notepad's window calls this when it closes
        self._say("Edit the names, save, and close the notepad to rename")
        self.edit_file(file)

    def _remove_name_list(self, file: str) -> None:
        threading.Thread(target=lambda: shutil.rmtree(os.path.dirname(file), ignore_errors=True), daemon=True).start()

    def _read_name_list(self, snap, file: str) -> None:
        def build(watch):                                            # reading, checking and planning: on a thread
            try:
                try:
                    with open(file, "rb") as f:
                        raw = f.read()
                finally:
                    shutil.rmtree(os.path.dirname(file), ignore_errors=True)
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("cp1252", errors="replace")
                names = rename_text.parse(text, snap)
                rename_text.check_unchanged(self.fs, snap)
                pairs = rename_text.pairs_from(snap, names)
            except rename_text.RenameTextError as e:
                return "error", str(e)
            except OSError as e:
                return "error", f"The list of names could not be read: {e.strerror or e}. Nothing was renamed."
            return "pairs", pairs

        def then(result) -> None:
            if result[0] == "error":
                self.dialogs.info("Edit the Names as Text", result[1])
                return
            pairs = result[1]
            if not pairs:
                self._say("Nothing to rename: every name stays as it is")
                return
            shown = [f"{os.path.basename(old)}  ->  {new}" for old, new in pairs[:10]]
            more = [f"... and {len(pairs) - 10} more"] if len(pairs) > 10 else []
            if self.dialogs.confirm("Edit the Names as Text", f"Rename {len(pairs)} item{'s' if len(pairs) != 1 else ''}?{chr(10)}{chr(10)}"
                                    + chr(10).join(shown + more), "Rename"):
                self._apply_renames(pairs, plan_text_renames)
        self._plan_in_background("Reading the names", build, then)

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
