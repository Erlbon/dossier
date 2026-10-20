"""Changing a zip or zip-based file from the file lists: copy and move into an open zip, delete, rename and make folders inside it.

The panel shows an open archive as ``zip://<archive>!/<inside>``. Every change here is one ``zipwrite.rewrite``: a new archive is
written beside the old one and swapped in at the end, the old one going to the recycle bin (a network drive has none: it is
deleted there, and the confirmation says so). A failure or a cancel leaves the original untouched. Only zip and zip-based files can
be changed; for 7z, RAR and the others the reason is shown and Convert Archive to Zip is the way out.
"""
from __future__ import annotations

import os
import zipfile

from ..core import zipwrite
from ..core.drives import is_network_path
from ..core.ops import check_name, default_trash, plan_delete
from ..core.platform import has_scheme
from .background import run_in_background

PREFIX = "zip://"


def zip_parts(path: str):
    """``(archive, inside)`` of a ``zip://archive!/inside`` path, from the text alone (no disk), or None for any other path."""
    if not path.startswith(PREFIX):
        return None
    rest = path[len(PREFIX):]
    at = rest.find("!/")
    if at < 0:
        return (rest[:-1], "") if rest.endswith("!") else None
    return rest[:at], rest[at + 2:].strip("/")


def _size_text(n: int) -> str:
    return f"{n / 1048576:,.1f} MB" if n >= 1048576 else f"{n:,} bytes"


class ZipEditMixin:
    """Part of ``MainWindow``."""

    # the common part -------------------------------------------------------------------------------------------------------
    def _in_zip(self, panel=None) -> bool:
        return zip_parts((panel or self.active).path) is not None

    def _bin_note(self, archive: str) -> str:
        return ("The old file is deleted for good (a network drive has no recycle bin)." if is_network_path(archive)
                else "The old file goes to the recycle bin.")

    def _rewrite_zip(self, archive: str, title: str, what: str, **edit) -> None:
        """Run one rewrite on a thread: progress with Cancel, then refresh both panels and say what was done."""
        trasher = os.remove if is_network_path(archive) else (self.trasher or default_trash)

        def work(progress, cancel):
            return zipwrite.rewrite(archive, cancel=cancel, progress=progress, trasher=trasher, **edit)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            self._say(f"{what} in {os.path.basename(archive)}")

        run_in_background(self, self.cmd_runner, title, work, on_result=finished, tracked=self._size_jobs, failed_title=title)

    # copy and move into an open zip ----------------------------------------------------------------------------------------
    def _into_zip(self, sources: list, dest: str, move: bool) -> None:
        title = "Move into Zip" if move else "Copy into Zip"
        archive, inside = zip_parts(dest)
        if any(has_scheme(s) for s in sources):
            self.dialogs.info(title, "Only items on a drive of this computer can be put into a zip. Unpack the archive first "
                                     "(Alt+F9), or copy from a normal folder.")
            return

        def build(watch):
            reason = zipwrite.why_not_editable(archive)
            if reason:
                raise zipwrite.ZipWriteError(reason)
            add, files, size = [], 0, 0
            for source in sources:
                top = os.path.basename(source.rstrip("/" + chr(92)))
                for arc, path, is_dir in zipwrite._walk(source, (inside + "/" if inside else "") + top, [], None):
                    watch(len(add))
                    add.append((arc, None if is_dir else path))
                    if not is_dir:
                        files += 1
                        size += os.path.getsize(path)
            with zipfile.ZipFile(archive) as z:
                have = {n.rstrip("/") for n in z.namelist()}
            clash = sum(1 for arc, _p in add if arc in have)
            return add, files, size, clash

        def then(found) -> None:
            add, files, size, clash = found
            if not add:
                self._say("Nothing to put into the zip")
                return
            text = (f"{'Move' if move else 'Copy'} {files:,} file{'s' if files != 1 else ''} ({_size_text(size)}) into "
                    f"{os.path.basename(archive)}{' / ' + inside if inside else ''}?{chr(10) * 2}"
                    f"The zip is written again as a new file that replaces the old one. {self._bin_note(archive)}")
            if clash:
                text += f"{chr(10) * 2}{clash:,} entr{'ies' if clash != 1 else 'y'} with the same name will be replaced."
            if move:
                text += f"{chr(10)}The originals go to the {self._bin_name()} once the zip is written."
            if not self.dialogs.confirm(title, text, "Move" if move else "Copy"):
                return
            self._write_into_zip(archive, add, sources if move else [], title)

        self._plan_in_background("Reading the items", build, then)

    def _bin_name(self) -> str:
        return "recycle bin"

    def _write_into_zip(self, archive: str, add: list, to_delete: list, title: str) -> None:
        trasher = os.remove if is_network_path(archive) else (self.trasher or default_trash)

        def work(progress, cancel):
            return zipwrite.rewrite(archive, add=add, cancel=cancel, progress=progress, trasher=trasher)

        def finished(result) -> None:
            for panel in (self.left, self.right):
                panel.refresh()
            self._say(f"Put {result.files:,} entries into {os.path.basename(archive)}" if not to_delete else
                      f"Moved into {os.path.basename(archive)}; the originals are being deleted")
            if to_delete:
                plan = plan_delete(self.fs, to_delete, to_trash=True)
                if plan.ops and not plan.blocking:
                    self._run(plan, unmark=to_delete)

        run_in_background(self, self.cmd_runner, "Writing the zip", work, on_result=finished, tracked=self._size_jobs,
                          failed_title=title)

    # delete, rename and new folder inside an open zip ------------------------------------------------------------------------
    def _delete_in_zip(self, sources: list) -> None:
        parts = [zip_parts(s) for s in sources]
        if not parts or any(p is None for p in parts):
            return
        archive = parts[0][0]
        inside = [p[1] for p in parts if p[1]]
        if not inside:
            self.dialogs.info("Delete", "Select the entries inside the archive to delete them.")
            return
        names = chr(10).join(os.path.basename(n) for n in inside[:6])
        more = "" if len(inside) <= 6 else f"{chr(10)}and {len(inside) - 6} more"
        if not self.dialogs.confirm("Delete from Zip", f"Delete {len(inside)} item{'s' if len(inside) != 1 else ''} from "
                                    f"{os.path.basename(archive)}? The zip is written again without "
                                    f"{'them' if len(inside) != 1 else 'it'}. {self._bin_note(archive)}{chr(10) * 2}{names}{more}",
                                    "Delete"):
            return
        self.selection.remove(sources)
        self._rewrite_zip(archive, "Delete from Zip", f"Deleted {len(inside)} item{'s' if len(inside) != 1 else ''}", remove=inside)

    def _rename_in_zip(self, entry) -> None:
        parts = zip_parts(entry.path)
        if parts is None or not parts[1]:
            return
        archive, inside = parts
        old = os.path.basename(inside)
        new = self.dialogs.ask_text("Rename", "New name:", old)
        if not new or new == old:
            return
        why = check_name(new)
        if why:
            self.dialogs.info("Rename", why[0].upper() + why[1:] + ".")
            return
        parent = inside.rsplit("/", 1)[0] + "/" if "/" in inside else ""
        self._rewrite_zip(archive, "Rename in Zip", f"Renamed {old} to {new}", rename={inside: parent + new})

    def _new_folder_in_zip(self) -> None:
        archive, inside = zip_parts(self.active.path)
        name = self.dialogs.ask_text("New Folder", "Folder name:")
        if not name:
            return
        why = check_name(name)
        if why:
            self.dialogs.info("New Folder", why[0].upper() + why[1:] + ".")
            return
        self._rewrite_zip(archive, "New Folder in Zip", f"Made the folder {name}",
                          add=[((inside + "/" if inside else "") + name, None)])
