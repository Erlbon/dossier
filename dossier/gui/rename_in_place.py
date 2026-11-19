"""F2 and New Folder rename in the list (card 58B): the rename and the folder-making that both the list editor and the boxes use."""
from __future__ import annotations

from typing import Optional

from ..core.ops import Plan, check_name, plan_rename
from ..core.undo_log import Step, UndoAction
from ..core.vfs import stat_or_none
from .background import run_in_background
from .zip_edit import zip_parts


class RenameInPlaceMixin:
    """Part of ``MainWindow``."""

    edit_in_place = True       # F2 and New Folder rename in the list (card 58B); off: the boxes of before (tests set it off)

    def rename(self) -> None:
        if self._home_blocked("Rename"):
            return
        entry = self.active.current_entry()
        if entry is None or self.busy:
            return
        if zip_parts(entry.path) is not None:
            self._rename_in_zip(entry)
            return
        old = self.fs.basename(entry.path)
        path = entry.path
        if self.edit_in_place and self.active.start_inline_edit(self.active.table.currentIndex().row(), old, entry.is_dir,
                                                                 lambda new: self._rename_to(path, old, new)):
            return                                               # F2 renames in the list; Enter calls _rename_to
        new = self.dialogs.ask_name("Rename", "New name:", old, entry.is_dir)   # the thumbnails view, and tests: the box
        self._rename_to(path, old, new)

    def _rename_to(self, path: str, old: str, new: Optional[str]) -> None:
        """Rename ``path`` (now called ``old``) to ``new``: the plan, its checks and its undo, the same from the box and the list."""
        if not new or new == old:
            return

        def go(plan: Plan) -> None:                              # the plan looks at the disk: made on a thread, settled here
            if plan.conflicts:
                self.dialogs.info("Rename", f"An item named {new} already exists here.")
                return
            plan = self._settle(plan)
            if plan is not None:
                self._run(plan, select=new)
        self._plan_in_background("Preparing the rename", lambda watch: plan_rename(self.fs, path, new), go)

    def new_folder(self) -> None:
        if self.active.is_home:
            self.add_network_share()                 # on the Home page F7 adds an entry instead of a folder
            return
        if self._no_folder_yet("New Folder"):
            return
        if zip_parts(self.active.path) is not None:
            self._new_folder_in_zip()
            return
        if not self.fs.is_writable(self.active.path):
            self.dialogs.info("New Folder", "This folder is read-only here (an archive, a search result or a list of "
                                            "all files cannot be added to).")
            return
        if self.edit_in_place and self.active.can_edit_in_place():
            self._make_folders("", in_list=True)                 # "New Folder" is made, and its name is open in the list
            return
        answer = self.dialogs.ask_text("New Folder", "Folder name (a\\b\\c makes folders inside each other):")
        if not answer:
            return
        self._make_folders(answer)

    NEW_FOLDER_NAME = "New Folder"

    def _make_folders(self, answer: str, *, in_list: bool = False, panel=None, folder: str = "", replacing: str = "") -> None:
        """Make the folders ``answer`` names (a\\b\\c: one in the other) in ``folder`` of ``panel`` (the active panel). ``in_list``: make
        "New Folder" (or "New Folder 2" and so on) and leave its name open for typing in the list. ``replacing``: the empty
        "New Folder" that was made a moment ago and is now being given the nested names, so it goes first."""
        panel = panel or self.active
        folder = folder or panel.path
        parts = [self.NEW_FOLDER_NAME] if in_list else [p for p in answer.replace("\\", "/").split("/") if p.strip()]
        why = check_name(parts[0]) if parts else "the name is empty"
        for part in parts[1:]:
            why = why or check_name(part)
        if why:
            self.dialogs.info("New Folder", why[0].upper() + why[1:] + ".")
            return

        def work(progress, cancel):                              # on a server or a slow share these are round trips: on a thread
            made_now = []
            if replacing and stat_or_none(self.fs, replacing) is not None:
                try:
                    self.fs.remove(replacing)                    # only while it is still empty
                except OSError:
                    return made_now, f"{self.fs.basename(replacing)} is not empty any more, so it was left as it is.", ""
            names = list(parts)
            if in_list:                                          # a free name: New Folder, New Folder 2, ...
                n = 2
                while stat_or_none(self.fs, self.fs.join(folder, names[0])) is not None:
                    names[0] = f"{self.NEW_FOLDER_NAME} {n}"
                    n += 1
            paths = []
            for part in names:
                paths.append(self.fs.join(paths[-1] if paths else folder, part))
            for path in paths:
                st = stat_or_none(self.fs, path)
                if st is not None:
                    if not st.is_dir:
                        return made_now, f"{path} is a file, not a folder.", names[0]
                    continue                                     # a\b where a is there already: only b is made
                try:
                    self.fs.mkdir(path)
                except OSError as e:
                    return made_now, f"Could not create the folder {path}: {e.strerror or e}", names[0]
                made_now.append(path)
            return made_now, "" if made_now else f"An item named {answer.strip()} already exists here.", names[0]

        def made(result) -> None:
            made_now, problem, name = result
            if made_now:                                         # undo removes the folders it made, innermost first
                self.undo_log.push(UndoAction("New folder", [Step("created_dir", p) for p in made_now]))
            if problem:
                self.dialogs.info("New Folder", problem)
                if not made_now and not replacing:
                    return
            if in_list and made_now and panel.path == folder:
                panel.edit_when_listed(name, True, lambda text, n=name: self._finish_new_folder(panel, folder, n, text))
            if panel.path == folder:
                panel.set_folder(folder, select=name)
            for other in (self.left, self.right):
                if other is not panel and other.path == folder:
                    other.refresh()
        run_in_background(self, self.cmd_runner, "New Folder", work, on_result=made, tracked=self._size_jobs, indeterminate=True,
                          failed_title="New Folder")

    def _finish_new_folder(self, panel, folder: str, name: str, text: str) -> None:
        """What was typed over "New Folder" in the list. Nothing or the same name: it stays. One name: a rename, as F2 does. Several
        (a/b/c): the nested folders, as the New Folder box makes them."""
        if not text.strip() or text == name:
            return
        parts = [p for p in text.replace("\\", "/").split("/") if p.strip()]
        if len(parts) > 1:
            self._make_folders(text, panel=panel, folder=folder, replacing=self.fs.join(folder, name))
        else:
            self._rename_to(self.fs.join(folder, name), name, text)

