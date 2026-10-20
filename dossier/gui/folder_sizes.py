"""The Folder Sizes command: add up whole folder trees for the Size column."""
from __future__ import annotations

from ..core.foldersize import folder_sizes
from .background import run_in_background
from .models import human_size


class FolderSizesMixin:
    """Part of ``MainWindow``."""

    def calculate_folder_sizes(self, panel=None) -> None:
        """Add up whole folder trees for the Size column: the marked folders of the panel, else every folder in
        its list. In the background with a box that shows the total growing and a Cancel."""
        panel = panel or self.active
        if panel.is_home:
            self._say("The Home page has no folders to add up")
            return
        model = panel.model
        folders = [model.entry_at(r) for r in range(model.entry_count())
                   if model.entry_at(r) is not None and model.entry_at(r).is_dir and not model.is_up_row(r)]
        marked = set(panel.marked_here())
        wanted = [e.path for e in folders if e.path in marked] or [e.path for e in folders]
        if not wanted:
            self._say("There are no folders in this list")
            return
        at = panel.path
        current = {"text": ""}

        def work(progress, cancel):
            def report(done: int, total: int, bytes_so_far: int, name: str) -> None:
                if name:
                    current["text"] = f"{name}  ({done + 1} of {total})   {human_size(bytes_so_far)} so far"
                progress(done, total)
            return folder_sizes(self.fs, wanted, cancel, report)

        def finished(results: dict) -> None:
            results = results or {}
            if panel.path == at:                          # the panel may have moved on while it worked
                panel.model.set_tree_sizes({p: r.size for p, r in results.items()})
            self._sizes.update({p: r.size for p, r in results.items()})
            self._update_status()                         # the line above counts folder sizes into the marked total
            total = sum(r.size for r in results.values())
            files = sum(r.files for r in results.values())
            unread = sum(r.unreadable for r in results.values())
            text = f"{len(results)} folder{'s' if len(results) != 1 else ''}: {human_size(total)} in {files:,} files"
            if unread:
                text += f"; {unread} folder{'s' if unread != 1 else ''} could not be read"
            if len(results) < len(wanted):
                text += f"; stopped after {len(results)} of {len(wanted)}"
            self._say(text)

        run_in_background(self, self.cmd_runner, "Folder sizes", work, on_result=finished, tracked=self._size_jobs,
                          detail=lambda: current["text"], partial_on_cancel=True)
