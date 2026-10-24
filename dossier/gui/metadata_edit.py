"""Saving the tags inside files from the Properties dialog (the Metadata tab): plan on a thread, one confirmation that says what changes and
what cannot, then write on a thread with progress and Cancel. ``core/metawrite.py`` does the work: a file is never changed in place, the old
one goes to the recycle bin once the new one is read back and in place, and a failure leaves the original as it was.
"""
from __future__ import annotations

import os

from ..core import metawrite
from ..core.drives import is_network_path
from ..core.ops import default_trash
from .background import run_in_background

MAX_LISTED = 6


class MetadataEditMixin:
    """Part of ``MainWindow``."""

    def _change_metadata(self, paths: list, edits: dict, kind: str) -> None:
        self._plan_in_background("Reading the files", lambda watch: metawrite.plan(paths, edits),
                                 lambda items: self._metadata_planned(items, kind))

    def _metadata_planned(self, items: list, kind: str) -> None:
        writable = [i for i in items if i.writable]
        problems = [i for i in items if i.problem]
        lines = [f"{os.path.basename(i.path)}: {i.problem}" for i in problems[:MAX_LISTED]]
        if len(problems) > MAX_LISTED:
            lines.append(f"and {len(problems) - MAX_LISTED} more")
        if not writable:
            self.dialogs.info("Save Metadata", chr(10).join(["Nothing needs to be written."] + lines))
            return
        fields = sorted({c.label for i in writable for c in i.changes})
        text = (f"Change {', '.join(fields)} in {len(writable):,} file{'s' if len(writable) != 1 else ''}?{chr(10)}{chr(10)}"
                "The new version of each file is made beside it and checked before it takes the old one's place; the old file goes to the "
                "recycle bin. Everything else in the file (cover art, lyrics, other tags) stays as it is.")
        if lines:
            text += f"{chr(10)}{chr(10)}Left out:{chr(10)}" + chr(10).join(lines)
        if self.dialogs.confirm("Save Metadata", text, "Save"):
            self._write_metadata(items)

    def _write_metadata(self, items: list) -> None:
        first = next((i.path for i in items if i.writable), "")
        trasher = os.remove if is_network_path(first) else (self.trasher or default_trash)     # a network drive has no recycle bin

        def work(progress, cancel):
            return metawrite.apply(items, cancel, progress, trasher)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            if result is None:
                self._say("Stopped: what was already saved stays saved")
                return
            self._say(f"Saved the metadata of {result.done:,} file{'s' if result.done != 1 else ''}"
                      + (f"; {len(result.failed)} could not be changed" if result.failed else ""))
            if result.failed:
                lines = [f"{os.path.basename(p)}: {why}" for p, why in result.failed[:MAX_LISTED]]
                self.dialogs.info("Save Metadata", chr(10).join(lines + ([f"and {len(result.failed) - MAX_LISTED} more"] if len(result.failed) > MAX_LISTED else [])))

        run_in_background(self, self.cmd_runner, "Saving metadata", work, on_result=finished, tracked=self._size_jobs,
                          partial_on_cancel=True, failed_title="Save Metadata")
