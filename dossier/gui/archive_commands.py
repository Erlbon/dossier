"""Pack to zip, unpack, and convert other archives to zip. Only zip is written (docs/code-review-2026-10-20.md, feature 10).

Every command runs its disk work on a thread with a progress box and a Cancel. Nothing is changed in an archive in place: a
new file is written and put in place at the end (see ``core/zipwrite.py``).
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from ..core import archives, zipwrite
from ..core.ops import plan_copy
from ..core.platform import has_scheme
from ..core.zipfs import archive_root
from .owned_dialog import OwnedDialog
from .background import run_in_background

LEVELS = (("Normal", "normal"), ("Fast", "fast"), ("Maximum", "maximum"), ("Store only (no compression)", "store"))


class PackDialog(OwnedDialog):
    def __init__(self, parent, folder: str, name: str, count: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pack to Zip")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Pack {count} item{'s' if count != 1 else ''} into a new zip file."))
        form = QFormLayout()
        self.folder = QLineEdit(folder)
        self.name = QLineEdit(name)
        self.level = QComboBox()
        for label, key in LEVELS:
            self.level.addItem(label, key)
        self.store_compressed = QCheckBox("Do not squeeze files that are already compressed (pictures, music, video)")
        self.store_compressed.setChecked(True)
        form.addRow("Save in", self.folder)
        form.addRow("Name", self.name)
        form.addRow("Compression", self.level)
        form.addRow("", self.store_compressed)
        layout.addLayout(form)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Pack", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus()
        self.name.setSelection(0, len(os.path.splitext(name)[0]))

    def target(self) -> str:
        name = self.name.text().strip()
        if name and not name.lower().endswith(".zip"):
            name += ".zip"
        return os.path.join(self.folder.text().strip(), name)

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name or any(c in name for c in '\\/:*?"<>|'):
            self.problem.setText("Give the zip a name without any of  \\ / : * ? \" < > |")
        elif not self.folder.text().strip():
            self.problem.setText("Say which folder to save it in.")
        else:
            self.accept()

    def values(self) -> tuple:
        return self.target(), self.level.currentData(), self.store_compressed.isChecked()


class ArchiveCommandsMixin:
    """Part of ``MainWindow``."""

    def _local_targets(self) -> list:
        panel = self.active
        if panel.is_home:
            return []
        return [p for p in panel.targets() if not has_scheme(p) and self.fs.basename(p) != ".."]

    def _folder_for_new_file(self) -> str:
        """Where a new archive or unpacked folder goes by default: the other panel's folder, else this one's."""
        other = self.other
        if not other.is_home and not has_scheme(other.path):
            return other.path
        return self.active.real_folder()

    # pack ----------------------------------------------------------------------------------------------------------------
    def pack_to_zip(self) -> None:
        """Alt+F5: pack the marked items (or the one under the cursor) into a new zip."""
        sources = self._local_targets()
        if not sources:
            self._say("Mark files or folders on a drive of this computer to pack them")
            return
        first = self.fs.basename(sources[0].rstrip("/" + chr(92)))
        stem = first if len(sources) == 1 and not os.path.splitext(first)[1] else (
            os.path.splitext(first)[0] if len(sources) == 1 else self.fs.basename(self.active.real_folder()) or "archive")
        dlg = PackDialog(self, self._folder_for_new_file(), stem + ".zip", len(sources))
        if not self._ask_pack(dlg):
            return
        target, level, store = dlg.values()

        def work(progress, cancel):
            if os.path.exists(target):
                raise FileExistsError(f"{os.path.basename(target)} already exists in that folder")
            return zipwrite.pack(sources, target, level=level, store_compressed=store, cancel=cancel, progress=progress)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            text = f"Packed {result.files:,} file{'s' if result.files != 1 else ''} into {os.path.basename(target)}"
            if result.skipped:
                text += f"; {len(result.skipped)} left out (links or unreadable)"
                self.dialogs.info("Pack to Zip", chr(10).join(f"{os.path.basename(p)}: {why}" for p, why in result.skipped[:10]))
            self._say(text)

        run_in_background(self, self.cmd_runner, "Packing", work, on_result=finished, tracked=self._size_jobs,
                          failed_title="Pack to Zip")

    def _ask_pack(self, dlg) -> bool:                       # a seam for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    # unpack --------------------------------------------------------------------------------------------------------------
    def unpack_archive(self) -> None:
        """Alt+F9: unpack the archive under the cursor into a folder named like the archive, beside the archive (the folder it stands
        in, not the other panel's: the folder can be changed in the question)."""
        targets = self._local_targets()
        if len(targets) != 1:
            self._say("Put the cursor on one archive to unpack it")
            return
        archive = targets[0]
        stem = os.path.splitext(self.fs.basename(archive))[0]
        default = self.fs.join(self.fs.parent(archive) or self.active.real_folder(), stem)
        dest = self.dialogs.ask_text("Unpack", f"Unpack {self.fs.basename(archive)} into this folder:", default)
        if not dest or not dest.strip():
            return
        dest = dest.strip()
        origin = self.active.real_folder()

        def build(watch):
            if archives.backend_for(archive) is None:
                raise archives.ArchiveError(archives.missing_reader(archive) or "this is not an archive Dossier can read")
            if os.path.isfile(dest):
                raise FileExistsError(f"{dest} is a file")
            os.makedirs(dest, exist_ok=True)
            members = [e.path for e in self.fs.list(archive_root(archive))]
            if not members:
                raise archives.ArchiveError("the archive is empty")
            return plan_copy(self.fs, members, dest, watch=watch)

        def then(plan) -> None:
            plan = self._settle(plan)
            if plan is not None:
                self._run(plan)

        self._plan_in_background("Reading the archive", build, then)

    # convert -------------------------------------------------------------------------------------------------------------
    def convert_archive_to_zip(self) -> None:
        """Write a zip with the contents of the 7z, RAR, tar or other archive under the cursor, beside it."""
        targets = self._local_targets()
        if len(targets) != 1:
            self._say("Put the cursor on one archive to convert it")
            return
        archive = targets[0]

        def work(progress, cancel):
            return zipwrite.convert_to_zip(archive, cancel=cancel, progress=progress)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            self._say(f"Converted to {os.path.basename(result.path)} ({result.files:,} files); the original is still there")

        run_in_background(self, self.cmd_runner, "Converting to zip", work, on_result=finished, tracked=self._size_jobs,
                          failed_title="Convert to Zip")
