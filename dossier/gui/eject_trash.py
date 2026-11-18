"""Eject a drive (card 47A) and the Trash as a place, with Put Back and Empty (card 46B): the window's side. The work is in
``core/eject.py`` and ``core/trash.py``."""
from __future__ import annotations

import subprocess
from typing import Optional

from ..core import eject as E
from ..core import trash as T
from ..core.drives import drive_of, list_drives
from ..core.home import HOME_URL
from ..core.platform import IS_MACOS
from ..core.sizefmt import human_size
from .background import run_in_background


class EjectTrashMixin:
    """Part of ``MainWindow``."""

    _pending_ejects: Optional[list] = None
    eject_runner = None                                       # tests put a fake subprocess.run here
    windows_ejector = None                                    # tests put a fake for the Windows steps here
    trash_opener = None                                       # tests put a fake for the Mac's "open the Trash in Finder" here

    # eject ------------------------------------------------------------------------------------------------------------------
    def queued_paths(self) -> list:
        """The sources and destinations of every operation that runs or waits."""
        out = []
        for job in list(getattr(self, "_jobs", [])):
            out += list(getattr(job, "paths", ()))
        return out

    def eject_drive(self, root: str, kind: str, title: str = "") -> None:
        """Eject (or unmount) the drive at ``root``. Dossier's own copies to it finish first; any panel showing it goes to the
        Home page, so Dossier itself holds nothing open there."""
        title = title or root
        if not E.can_eject(root, kind):
            self._say(f"{title} cannot be ejected")
            return
        if E.touches(root, self.queued_paths()):
            pending = self._pending_ejects if self._pending_ejects is not None else []
            if (root, kind, title) not in pending:
                pending.append((root, kind, title))
            self._pending_ejects = pending
            self._say(f"{title} is ejected when the operations on it are done")
            return
        for panel in (self.left, self.right):
            if not panel.is_home and E.touches(root, [panel.real_folder() or panel.path]):
                panel.set_folder(HOME_URL)

        def work(progress, cancel):
            progress(0, 0)
            return E.eject(root, kind, runner=self.eject_runner, windows_eject=self.windows_ejector)

        def done(result) -> None:
            if result.ok:
                self._say(f"Ejected {title}: it can be removed")
                for panel in (self.left, self.right):
                    if panel.is_home:
                        panel.refresh()
                    panel.drive_bar.reload()
            else:
                self.dialogs.show_output(f"Could not eject {title}", result.output)

        run_in_background(self, self.cmd_runner, f"Ejecting {title}", work, on_result=done, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Eject")

    def eject_pending(self) -> None:
        """Called when an operation ends: eject what waited for it."""
        if not self._pending_ejects:
            return
        busy = self.queued_paths()
        ready = [p for p in self._pending_ejects if not E.touches(p[0], busy)]
        self._pending_ejects = [p for p in self._pending_ejects if p not in ready]
        for root, kind, title in ready:
            self.eject_drive(root, kind, title)

    def eject_current_drive(self) -> None:
        """File > Eject: the drive of the item under the cursor on the Home page, else the drive of the active panel's folder."""
        panel = self.active
        entry = panel.current_entry() if hasattr(panel, "current_entry") else None
        if panel.is_home and entry is not None and E.can_eject(entry.path, entry.kind):
            self.eject_drive(entry.path, entry.kind, entry.name.split("  ")[0])
            return
        drive = drive_of(panel.real_folder() or panel.path, list_drives()) if not panel.is_home else None
        if drive is None or not E.can_eject(drive.path, drive.kind):
            self._say("Nothing here to eject: choose a removable drive or a share")
            return
        self.eject_drive(drive.path, drive.kind, drive.title)

    # the Trash ----------------------------------------------------------------------------------------------------------------
    def open_trash(self, panel=None, new_tab: bool = False) -> None:
        """The Trash place: a read-only folder on Windows and Linux; on the Mac, Finder's Trash (Put Back belongs to Finder there)."""
        if IS_MACOS:
            try:
                (self.trash_opener or (lambda argv: subprocess.Popen(argv)))(T.mac_open_command())
            except OSError as e:
                self.dialogs.info(T.TITLE, f"The Trash could not be opened in Finder: {e}")
            return
        panel = panel or self.active
        if new_tab:
            panel.new_tab(T.TRASH_URL)
        else:
            panel.set_folder(T.TRASH_URL)

    def _trash_items_of(self, paths: list) -> list:
        items = self.fs.trash.items()
        return [i for i in (T.item_of(p, items) for p in paths) if i is not None]

    def put_back(self) -> None:
        """Put the marked items (or the one under the cursor) back where they came from, as a plan."""
        if not T.is_trash(self.active.path):
            return
        items = self._trash_items_of(self.active.targets())
        if not items:
            return

        def then(plan) -> None:
            plan = self._settle(plan)
            if plan is None:
                return
            names = "\n".join(f"{i.name}  to  {i.original}" for i in items[:6])
            more = "" if len(items) <= 6 else f"\nand {len(items) - 6} more"
            if self.dialogs.confirm("Put Back", f"Put {len(items)} item(s) back where they came from?\n\n{names}{more}", "Put Back"):
                self._run(plan, on_done=lambda job: self._restored(items))

        self._plan_in_background("Preparing to put back", lambda watch: T.put_back_plan(self.fs, items), then)

    def _restored(self, items: list) -> None:
        T.forget_restored(items)
        for panel in (self.left, self.right):
            if T.is_trash(panel.path):
                panel.refresh()

    def empty_trash(self, items: Optional[list] = None) -> None:
        """Empty the Trash (or delete ``items`` from it): permanent, after one question with the count and size."""
        def work(progress, cancel):
            progress(0, 0)
            return items if items is not None else self.fs.trash.items(fresh=True)

        def ask(found) -> None:
            if not found:
                self._say(f"The {T.TITLE} is empty")
                return
            size = sum(i.size for i in found)
            what = "everything in the " + T.TITLE if items is None else f"{len(found)} item(s) from the {T.TITLE}"
            if not self.dialogs.confirm("Empty the " + T.TITLE if items is None else "Delete from the " + T.TITLE,
                                        f"Delete {what} for good: {len(found):,} item(s), {human_size(size)}.\n\n"
                                        "This cannot be undone.", "Delete permanently"):
                return

            def remove(progress, cancel):
                progress(0, 0)
                return T.remove_for_good(found, cancel.check)

            def removed(result) -> None:
                count, failed = result
                self._say(f"Deleted {count:,} item(s) from the {T.TITLE} for good")
                if failed:
                    self.dialogs.show_output("Some items could not be deleted",
                                             "\n".join(f"{name}: {why}" for name, why in failed[:50]))
                for panel in (self.left, self.right):
                    if T.is_trash(panel.path):
                        panel.refresh()

            run_in_background(self, self.cmd_runner, "Emptying the " + T.TITLE, remove, on_result=removed, tracked=self._size_jobs,
                              indeterminate=True, failed_title="Empty the " + T.TITLE)

        run_in_background(self, self.cmd_runner, "Reading the " + T.TITLE, work, on_result=ask, tracked=self._size_jobs,
                          indeterminate=True, failed_title=T.TITLE)

    def delete_in_trash(self) -> None:
        """F8 in the Trash: what is there can only go for good."""
        items = self._trash_items_of(self.active.targets())
        if items:
            self.empty_trash(items)
