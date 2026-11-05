"""F4 on a file on a server, or inside a zip: edit a private copy and write it back on save.

The file is copied to Dossier's temporary folder (``zipfs.local_copy``) and opened in the notepad or in the editor program of
Settings > Opening Files. Each save writes it back: uploaded to the server, or put into the zip by one ``zipwrite.rewrite``. Before
writing, the original is looked at again; when it changed since it was copied (its size or time differ), nothing is written and the
owner is told, so another person's change is never overwritten. A server whose read-only switch is on is never written to, and
only zip and zip-based archives can be changed (7z and RAR stay read-only). The local copy is kept until the program ends, so an
edit that could not be written back is not lost.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PyQt6.QtCore import QFileSystemWatcher, QTimer

from ..core import zipfs, zipwrite
from ..core.drives import no_recycle_bin
from ..core.ops import default_trash
from .background import run_in_background
from .zip_edit import zip_parts

WRITE_BACK_DELAY_MS = 600            # an editor program may write a file in several steps: write back once it is still


@dataclass
class RemoteEdit:
    origin: str                      # the server path, or the zip:// path of the member
    local: str                       # the private copy that is edited
    stamp: tuple                     # (size, whole seconds) of the original (of the archive, for a zip) when it was copied
    archive: str = ""
    inside: str = ""


def _stamp_of_archive(archive: str) -> tuple:
    st = os.stat(archive)
    return st.st_size, int(st.st_mtime)


class RemoteEditMixin:
    """Part of ``MainWindow``."""

    def _remote_edits(self) -> dict:
        return self.__dict__.setdefault("_remote_edit_map", {})

    def remote_edit_of(self, local: str):
        return self._remote_edits().get(os.path.normcase(local))

    def local_copy_of(self, origin: str) -> str:
        """The private copy an edit of ``origin`` already has ("" when none)."""
        return next((r.local for r in self._remote_edits().values() if r.origin == origin), "")

    def prepare_remote_edit(self, path: str) -> tuple:
        """``(RemoteEdit, problem)``: the original is checked and copied. Opens files: called on a thread."""
        parts = zip_parts(path)
        if parts is not None or path.startswith("zip://"):
            archive, inside = parts if parts is not None else ("", "")
            reason = zipwrite.why_not_editable(archive) if archive else "this is not inside a zip"
            if reason:
                return None, f"Items inside this archive cannot be changed: {reason}. Copy the file out to edit it."
            stamp = _stamp_of_archive(archive)
        else:
            e = self.fs.stat(path)                               # first: a server that is not connected says so itself
            if not self.fs.is_writable(path):
                return None, ("This server is set to read-only. To change files there, edit the server on the Home page and switch "
                              "read-only off.")
            stamp, archive, inside = (e.size, int(e.mtime)), "", ""
        local = zipfs.local_copy(self.fs, path)
        return RemoteEdit(path, local, stamp, archive, inside), ""

    def register_remote_edit(self, edit: RemoteEdit) -> None:
        self._remote_edits()[os.path.normcase(edit.local)] = edit

    def watch_remote_edit(self, edit: RemoteEdit) -> None:
        """For an editor program: write back whenever the copy changes (and is still for a moment)."""
        watcher = self.__dict__.get("_remote_edit_watcher")
        if watcher is None:
            watcher = self._remote_edit_watcher = QFileSystemWatcher(self)
            self._remote_edit_timers = {}
            watcher.fileChanged.connect(self._remote_copy_changed)
        watcher.addPath(edit.local)

    def _remote_copy_changed(self, local: str) -> None:
        if os.path.exists(local) and local not in self._remote_edit_watcher.files():
            self._remote_edit_watcher.addPath(local)      # an editor that saves by replacing the file: watch the new one
        timer = self._remote_edit_timers.get(local)
        if timer is None:
            timer = self._remote_edit_timers[local] = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=local: self.write_back(p))
        timer.start(WRITE_BACK_DELAY_MS)

    def write_back(self, local: str) -> None:
        """Put the saved copy back where it came from, unless the original changed since it was copied."""
        edit = self.remote_edit_of(local)
        if edit is None:
            return
        trasher = (os.remove if no_recycle_bin(edit.archive) else (self.trasher or default_trash)) if edit.archive else None

        def work(progress, cancel):
            now = _stamp_of_archive(edit.archive) if edit.archive else (lambda e: (e.size, int(e.mtime)))(self.fs.stat(edit.origin))
            if now != edit.stamp:
                return None
            if edit.archive:
                zipwrite.rewrite(edit.archive, add=[(edit.inside, local)], cancel=cancel, progress=progress, trasher=trasher)
                return _stamp_of_archive(edit.archive)
            with open(local, "rb") as src, self.fs.open_write(edit.origin) as dst:
                while True:
                    cancel.check()
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            e = self.fs.stat(edit.origin)
            return e.size, int(e.mtime)

        def done(stamp) -> None:
            name = os.path.basename(local)
            if stamp is None:
                self.dialogs.info("Edit", f"{edit.origin} was changed by someone else after you opened it, so your version was not "
                                          f"written back. It is kept here: {local}")
                return
            edit.stamp = stamp
            for panel in (self.left, self.right):
                if not panel.is_home and (panel.path == self.fs.dirname(edit.origin) or edit.archive):
                    panel.refresh()
            self._say(f"Wrote {name} back to {'the zip' if edit.archive else 'the server'}")

        run_in_background(self, self.cmd_runner, "Writing the file back", work, on_result=done, tracked=self._size_jobs,
                          failed_title="Edit")
