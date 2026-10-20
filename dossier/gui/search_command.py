"""Search and the flat view: both end as a list of real files in a tab of their own.

A search runs on a thread with a box (how many were looked at, how many found) and a Cancel; its result is stored under a
number and opened in a NEW tab of the active panel, so the folder it started from stays where it was and closing the tab
brings it back. "All files below this folder" is the same thing without criteria. The ``..`` row of either goes to the real
folder the list was made from.
"""
from __future__ import annotations

import os
import time

from ..core.listings import FOUND_PREFIX, FLAT_PREFIX, ResultSet
from ..core.search import BadCriteria, Criteria, search
from .background import run_in_background


class SearchCommandMixin:
    """Part of ``MainWindow``."""

    def _search_root_ok(self, panel) -> bool:
        if panel.is_home:
            self._say("Open a folder first: a search looks inside a folder")
            return False
        return True

    def show_all_files_below(self, panel=None) -> None:
        """Ctrl+Shift+B: every file below the folder, however deep, as one list in a new tab."""
        panel = panel or self.active
        if not self._search_root_ok(panel):
            return
        root = panel.real_folder() if panel.path.startswith(("found:", "flat:")) else panel.path
        panel.new_tab(FLAT_PREFIX + root)
        self._say(f"All files below {root}: the way up goes back to the folder; close the tab when you are done")

    def start_search(self, criteria: Criteria, panel=None) -> None:
        """Run a search and open its result in a new tab."""
        panel = panel or self.active
        try:
            from ..core.search import validate
            validate(criteria)
        except BadCriteria as e:
            self.dialogs.info("Search", str(e))
            return
        counts = {"scanned": 0, "found": 0}
        started = time.monotonic()

        def work(progress, cancel):
            def report(scanned: int, found: int) -> None:
                counts["scanned"], counts["found"] = scanned, found
                progress(scanned, 0)
            return search(self.fs, criteria, cancel, report)

        def finished(result) -> None:
            what = criteria.describe()
            title = f"Search: {what} in {os.path.basename(criteria.root.rstrip(chr(92) + '/')) or criteria.root}" \
                    f" ({len(result.entries):,} found)"
            path = self.fs.found.store.add(ResultSet(title, criteria.root, result.entries, criteria))
            panel.new_tab(path)
            note = f"{len(result.entries):,} found among {result.scanned:,} looked at"
            if result.truncated:
                note += f"; stopped at the limit of {criteria.max_results:,} results"
            if result.unreadable:
                note += f"; {result.unreadable} folder{'s' if result.unreadable != 1 else ''} could not be read"
            self._say(note + f" ({time.monotonic() - started:.1f} s)")

        run_in_background(self, self.cmd_runner, "Searching", work, on_result=finished, tracked=self._size_jobs,
                          detail=lambda: f"{counts['scanned']:,} looked at, {counts['found']:,} found so far",
                          indeterminate=True, failed_title="Search")
