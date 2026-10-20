"""Small commands on the marks (saved selections, the list of marked paths) and on the folder note (edit it, create it)."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMenu

from ..core.notes import BOTTOM_NAMES
from ..core.platform import has_scheme
from .background import run_in_background


class MarksAndNotesMixin:
    """Part of ``MainWindow``."""

    # saved selections ------------------------------------------------------------------------------------------
    def save_selection(self) -> None:
        """Remember what is marked in this panel under a name, for this session."""
        here = self.active.marked_here()
        if not here:
            self._say("Nothing is marked here to save")
            return
        name = self.dialogs.ask_text("Save Selection", f"A name for these {len(here)} marked item(s):",
                                     f"selection {len(self.selection.saved_names()) + 1}")
        if not name or not name.strip():
            return
        self.selection.save(name.strip(), here)
        self._say(f"Saved {len(here)} marked item(s) as {name.strip()}")

    def restore_selection(self, name: str, combine: bool = False) -> None:
        try:
            self.selection.recall(name, combine=combine)
        except KeyError:
            self._say(f"No saved selection named {name}")
            return
        self._say(f"{len(self.active.marked_here())} marked here after "
                  f"{'adding' if combine else 'restoring'} {name}")

    def forget_selection(self, name: str) -> None:
        self.selection.forget(name)
        self._say(f"Forgot the saved selection {name}")

    def build_selection_menus(self, restore: QMenu, add: QMenu, forget: QMenu) -> None:
        """Fill the three submenus with the saved names (called each time the Mark menu opens)."""
        names = self.selection.saved_names()
        for menu, handler in ((restore, lambda n: self.restore_selection(n)), (add, lambda n: self.restore_selection(n, True)),
                              (forget, self.forget_selection)):
            menu.clear()
            if not names:
                menu.addAction("Nothing saved yet").setEnabled(False)
            for n in names:
                menu.addAction(n.replace("&", "&&")).triggered.connect(lambda _c=False, n=n, h=handler: h(n))

    def copy_marked_paths(self) -> None:
        """The full paths of the marked items (or the item under the cursor), one per line, as text on the clipboard."""
        paths = self.active.targets()
        if not paths:
            self._say("Nothing to copy: mark items or put the cursor on one")
            return
        QApplication.clipboard().setText(chr(10).join(paths))
        self._say(f"Copied {len(paths)} path{'s' if len(paths) != 1 else ''} as text")

    # the folder note ---------------------------------------------------------------------------------------------
    def edit_folder_note(self) -> None:
        """Open the note of this folder in the editor (the one shown under the list); with none, create README.md with a
        heading. Nothing here touches the disk on the window's thread: the note files were found with the listing and the
        new file is written on a thread."""
        panel = self.active
        folder = panel.real_folder() if panel.path.startswith(("found:", "flat:")) else panel.path
        if panel.is_home or has_scheme(folder):
            self._say("A note belongs to a folder on a disk: open the folder first")
            return
        notes = [p for p in panel.note_paths if self.fs.basename(p) in BOTTOM_NAMES] or panel.note_paths
        if notes:
            self.edit_file(notes[0])
            return
        path = self.fs.join(folder, "README.md")
        title = self.fs.basename(folder.rstrip(chr(92) + "/")) or folder

        def work(progress, cancel):
            with self.fs.open_write(path, exclusive=True) as f:
                f.write((f"# {title}" + chr(10) * 2).encode("utf-8"))
            return path

        def made(created) -> None:
            self._say(f"Created README.md in {folder}")
            self.edit_file(created)

        run_in_background(self, self.cmd_runner, "Folder Note", work, on_result=made, tracked=self._size_jobs,
                          failed_title="Folder Note")
