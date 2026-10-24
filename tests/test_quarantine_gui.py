"""The quarantine in the window: the settings, moving a file in, undoing it, and putting it back. Real moves use the one-folder mode in tmp_path."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import quarantine  # noqa: E402
from dossier.gui import quarantine_ui as ui  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def wait(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def use_folder(win, tmp):
    ui.write_settings(win.settings, quarantine.Settings(quarantine.FOLDER, str(tmp / "Q")))
    return win.quarantine_settings()


def show(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def point_at(win, panel, name):
    row = next(r for r in range(panel.model.entry_count()) if panel.model.entry_at(r).name == name)
    panel.table.setCurrentIndex(panel.table.model().index(row, 0))


# settings ---------------------------------------------------------------------------------------------------------------------------------
def test_the_default_is_a_quarantine_on_each_drive(world):
    win, d, left, right, tmp = world
    assert win.quarantine_settings() == quarantine.Settings(quarantine.DRIVE, "")


def test_the_settings_dialog_shows_where_a_file_would_go_and_saves(world, monkeypatch):
    win, d, left, right, tmp = world
    (left / "a.txt").write_text("a")
    show(win, win.left, 2)
    point_at(win, win.left, "a.txt")
    seen = {}

    def drive(dialog):
        seen["default"] = (dialog.on_drive.isChecked(), dialog.folder.isEnabled(), dialog.shown.text())
        dialog.one_folder.setChecked(True)
        dialog.folder.setText(str(tmp / "Elsewhere"))
        seen["custom"] = (dialog.folder.isEnabled(), dialog.shown.text())
        dialog.accept()
    monkeypatch.setattr(win, "_show_quarantine_dialog", drive)
    win.open_quarantine_settings()
    assert seen["default"][0] and not seen["default"][1] and "Temp" in seen["default"][2] and "Quarantine" in seen["default"][2]
    assert seen["custom"][0] and str(tmp / "Elsewhere") in seen["custom"][1]
    assert win.quarantine_settings() == quarantine.Settings(quarantine.FOLDER, os.path.normpath(str(tmp / "Elsewhere")))
    assert "all in" in win.status.text()


def test_a_cancelled_dialog_and_back_to_the_default(world, monkeypatch):
    win, d, left, right, tmp = world
    use_folder(win, tmp)
    monkeypatch.setattr(win, "_show_quarantine_dialog", lambda dialog: dialog.reject())
    win.open_quarantine_settings()
    assert win.quarantine_settings().mode == quarantine.FOLDER                # nothing was saved
    seen = {}

    def drive(dialog):
        seen["before"] = dialog.one_folder.isChecked()
        dialog.defaults.click()
        dialog.accept()
    monkeypatch.setattr(win, "_show_quarantine_dialog", drive)
    win.open_quarantine_settings()
    assert seen["before"] and win.quarantine_settings() == quarantine.Settings(quarantine.DRIVE, "")


def test_a_folder_mode_without_a_folder_says_to_choose_one(world):
    win, d, left, right, tmp = world
    dialog = ui.QuarantineDialog(win, quarantine.Settings(), str(left / "a.txt"))
    dialog.one_folder.setChecked(True)
    assert "Choose the folder" in dialog.shown.text() and dialog.values().mode == quarantine.DRIVE


# moving ----------------------------------------------------------------------------------------------------------------------------------
def test_a_marked_file_is_moved_to_the_quarantine_after_one_confirmation_and_can_be_undone(world):
    win, d, left, right, tmp = world
    s = use_folder(win, tmp)
    (left / "bad.zip").write_text("broken")
    show(win, win.left, 2)
    win.selection.add([str(left / "bad.zip")])
    win.move_to_quarantine()
    wait(lambda: d.confirms)
    title, text = d.confirms[-1]
    assert title == "Move to Quarantine" and str(tmp / "Q") in text and "nothing is deleted" in text
    pump(win, lambda: not (left / "bad.zip").exists())
    assert open(quarantine.destination(str(left / "bad.zip"), s)).read() == "broken"
    win.undo()                                                       # one drive: an ordinary move, so it can be undone
    pump(win, lambda: (left / "bad.zip").exists())


def test_declining_the_confirmation_moves_nothing(world):
    win, d, left, right, tmp = world
    use_folder(win, tmp)
    (left / "keep.txt").write_text("k")
    show(win, win.left, 2)
    win.selection.add([str(left / "keep.txt")])
    d.confirm_answer = False
    win.move_to_quarantine()
    wait(lambda: d.confirms)
    for _ in range(20):
        QApplication.processEvents()
    assert (left / "keep.txt").exists() and not (tmp / "Q").exists()


def test_nothing_chosen_and_what_is_already_quarantined(world):
    win, d, left, right, tmp = world
    s = use_folder(win, tmp)
    win.selection.clear()
    win.move_to_quarantine()
    assert "mark items" in win.status.text()
    (left / "x.txt").write_text("x")
    show(win, win.left, 2)
    win.selection.add([str(left / "x.txt")])
    win.move_to_quarantine()
    wait(lambda: d.confirms)
    pump(win, lambda: not (left / "x.txt").exists())
    win.left.set_folder(os.path.dirname(quarantine.destination(str(left / "x.txt"), s)))
    pump(win, lambda: win.left.path == os.path.dirname(quarantine.destination(str(left / "x.txt"), s)) and not win.left.loading)
    d.infos.clear()
    win.selection.add([quarantine.destination(str(left / "x.txt"), s)])
    win.move_to_quarantine()
    wait(lambda: d.infos)
    assert "already in the quarantine" in d.infos[-1][1]


# putting back ----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.name != "nt", reason="the one-folder quarantine knows a file's drive only through the drive letter")
def test_a_file_is_put_back_where_it_came_from_and_never_over_another(world):
    win, d, left, right, tmp = world
    s = use_folder(win, tmp)
    (left / "doc.txt").write_text("original")
    show(win, win.left, 2)
    win.selection.add([str(left / "doc.txt")])
    win.move_to_quarantine()
    wait(lambda: d.confirms)
    pump(win, lambda: not (left / "doc.txt").exists())
    kept = quarantine.destination(str(left / "doc.txt"), s)
    folder = os.path.dirname(kept)
    win.left.set_folder(folder)
    pump(win, lambda: win.left.path == folder and win.left.model.row_of("doc.txt") >= 0)
    (left / "doc.txt").write_text("a new file with the same name")        # something took its place meanwhile
    win.selection.clear()
    point_at(win, win.left, "doc.txt")
    d.conflict_answer = None                                                # the conflict dialog is cancelled
    win.put_back_from_quarantine()
    wait(lambda: hasattr(d, "conflict_rows_seen"))
    assert (left / "doc.txt").read_text() == "a new file with the same name" and os.path.exists(kept)
    d.conflict_answer = __import__("dossier.core.ops", fromlist=["Resolution"]).Resolution.KEEP_BOTH
    win.put_back_from_quarantine()
    pump(win, lambda: not os.path.exists(kept))
    assert sorted(p.name for p in left.iterdir()) == ["doc (2).txt", "doc.txt"]
    assert (left / "doc (2).txt").read_text() == "original"


def test_put_back_of_something_that_is_not_in_the_quarantine_says_so(world):
    win, d, left, right, tmp = world
    use_folder(win, tmp)
    (left / "plain.txt").write_text("p")
    show(win, win.left, 2)
    win.selection.add([str(left / "plain.txt")])
    win.put_back_from_quarantine()
    wait(lambda: d.infos)
    assert "not in the quarantine" in d.infos[-1][1] and (left / "plain.txt").exists()


# going there ------------------------------------------------------------------------------------------------------------------------------
def test_the_quarantine_folder_opens_only_when_it_exists(world):
    win, d, left, right, tmp = world
    s = use_folder(win, tmp)
    win.show_quarantine_folder()
    wait(lambda: "Nothing has been quarantined" in win.status.text())
    (tmp / "Q").mkdir()
    win.show_quarantine_folder()
    pump(win, lambda: win.left.path == str(tmp / "Q"))


def test_the_commands_are_in_the_menus(world):
    win, d, left, right, tmp = world
    texts = {a.text() for a in win.findChildren(type(win.menuBar().actions()[0])) if a.text()}
    assert {"Move to Quarantine...", "Put Back from Quarantine", "Quarantine...", "Quarantine Folder"} <= texts
