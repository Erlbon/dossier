"""The window's side of Eject (card 47A) and the Trash place (card 46B)."""
from __future__ import annotations

import subprocess
import time

import pytest

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, names, pump, world  # noqa: E402,F401

from dossier.core import trash  # noqa: E402
from dossier.core.platform import IS_MACOS  # noqa: E402


def _bin(tmp_path, original, content=b"x"):
    folder = tmp_path / "Trash"
    (folder / "files").mkdir(parents=True, exist_ok=True)
    (folder / "info").mkdir(parents=True, exist_ok=True)
    name = original.name
    (folder / "files" / name).write_bytes(content)
    (folder / "info" / (name + ".trashinfo")).write_text(trash.record_text(str(original), time.time()), encoding="utf-8")
    return folder


@pytest.mark.skipif(IS_MACOS, reason="the Mac opens Finder's Trash instead")
def test_the_trash_lists_items_by_their_old_place_and_puts_back(world):
    win, dialogs, left, right, tmp_path = world
    folder = _bin(tmp_path, left / "report.txt", b"report")
    win.fs.trash.bins = lambda: [trash.Bin(str(folder))]
    win.open_trash(win.left)
    pump(win, lambda: "report.txt" in names(win.left))
    entry = next(win.left.model.entry_at(r) for r in range(win.left.model.entry_count())
                 if win.left.model.entry_at(r).name == "report.txt")
    assert entry.detail == str(left)
    row = names(win.left).index("report.txt")
    win.left.table.setCurrentIndex(win.left.model.index(row, 0))
    win.put_back()
    pump(win, lambda: (left / "report.txt").exists())
    assert (left / "report.txt").read_bytes() == b"report"
    pump(win, lambda: not list((folder / "info").iterdir()))


@pytest.mark.skipif(IS_MACOS, reason="the Mac opens Finder's Trash instead")
def test_emptying_the_trash_asks_once_and_deletes_for_good(world):
    win, dialogs, left, right, tmp_path = world
    folder = _bin(tmp_path, left / "old.txt")
    win.fs.trash.bins = lambda: [trash.Bin(str(folder))]
    win.empty_trash()
    pump(win, lambda: not list((folder / "files").iterdir()))
    assert any("cannot be undone" in text for _t, text in dialogs.confirms)


def test_eject_waits_for_a_copy_to_the_drive_then_runs(world):
    win, dialogs, left, right, tmp_path = world
    seen = []
    win.eject_runner = lambda argv, **kw: (seen.append(argv), subprocess.CompletedProcess(argv, 0, "", ""))[1]
    win.windows_ejector = lambda root: seen.append(["windows", root])

    class Busy:
        paths = (str(right / "x.txt"),)

    win._jobs.append(Busy())
    win.eject_drive(str(right), "removable", "STICK")
    assert seen == [] and win._pending_ejects
    win._jobs.clear()
    win.eject_pending()
    pump(win, lambda: bool(seen))
    assert seen
