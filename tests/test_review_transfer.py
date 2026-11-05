"""The functionality review of 2026-11-05, cards 22 and 23: F5 / F6 to any folder, copy with a new name, and the copy options (only
files named, flatten, newer only)."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

from dossier.core.ops import plan_copy  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402


def listed(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def cursor_on(panel, name):
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


def copy_with(win, dialogs, **answer):
    dialogs.transfer_answer = answer
    win.copy()


# 22 ----------------------------------------------------------------------------------------------------------------------------
def test_f5_into_a_folder_below_the_other_panel_makes_it(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    copy_with(win, dialogs, dest="backup" + os.sep)
    pump(win, lambda: (right / "backup" / "a.txt").exists())


def test_f5_with_a_new_name_copies_as(world):
    win, dialogs, left, right, _t = world
    (left / "report.pdf").write_text("r")
    listed(win, win.left, 2)
    cursor_on(win.left, "report.pdf")
    copy_with(win, dialogs, dest=str(right / "report-old.pdf"))
    pump(win, lambda: (right / "report-old.pdf").exists())
    assert not (right / "report.pdf").exists()


def test_a_copy_into_its_own_folder_is_a_duplicate(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    copy_with(win, dialogs, dest=str(left))
    pump(win, lambda: (left / "a (2).txt").exists())
    assert (left / "a.txt").read_text() == "a"


def test_f6_with_a_new_name_moves_as(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    dialogs.transfer_answer = {"dest": str(right / "b.txt")}
    win.move()
    pump(win, lambda: (right / "b.txt").exists() and not (left / "a.txt").exists())


def test_several_items_into_a_file_are_refused(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    (right / "x.txt").write_text("x")
    listed(win, win.left, 3)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    copy_with(win, dialogs, dest=str(right / "x.txt"))
    pump(win, lambda: dialogs.infos)
    assert "is a file" in dialogs.infos[-1][1]


def test_an_unchanged_destination_runs_the_plan_already_made(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    win.copy()
    pump(win, lambda: (right / "a.txt").exists())


# 23 ----------------------------------------------------------------------------------------------------------------------------
def test_only_matching_files_and_no_empty_folders(tmp_path):
    src = tmp_path / "src"
    (src / "photos").mkdir(parents=True)
    (src / "docs").mkdir()
    (src / "photos" / "a.jpg").write_text("a")
    (src / "docs" / "b.txt").write_text("b")
    dest = tmp_path / "dest"
    dest.mkdir()
    plan = plan_copy(LocalFileSystem(), [str(src)], str(dest), only="*.jpg")
    dsts = sorted(os.path.relpath(op.dst, dest) for op in plan.ops)
    assert dsts == ["src", os.path.join("src", "photos"), os.path.join("src", "photos", "a.jpg")]


def test_the_options_flatten_and_filter_from_the_box(world):
    win, dialogs, left, right, _t = world
    (left / "tree" / "deep").mkdir(parents=True)
    (left / "tree" / "deep" / "a.jpg").write_text("a")
    (left / "tree" / "b.txt").write_text("b")
    listed(win, win.left, 2)
    cursor_on(win.left, "tree")
    copy_with(win, dialogs, only="*.jpg", flatten=True)
    pump(win, lambda: (right / "a.jpg").exists())
    assert not (right / "b.txt").exists() and not (right / "tree").exists()


def test_newer_only_keeps_a_newer_file_and_replaces_an_older_one(world):
    win, dialogs, left, right, _t = world
    now = time.time()
    for name, src_age, dst_age in (("keep.txt", 100, 10), ("replace.txt", 10, 100)):
        (left / name).write_text("new " + name)
        (right / name).write_text("old " + name)
        os.utime(left / name, (now - src_age, now - src_age))
        os.utime(right / name, (now - dst_age, now - dst_age))
    listed(win, win.left, 3)
    win.selection.add([str(left / "keep.txt"), str(left / "replace.txt")])
    copy_with(win, dialogs, newer=True)
    pump(win, lambda: (right / "replace.txt").read_text() == "new replace.txt")
    assert (right / "keep.txt").read_text() == "old keep.txt"


def test_the_real_box_hands_back_what_was_typed(world):
    from dossier.gui.transfer_dialog import TransferDialog
    win, *_ = world
    dlg = TransferDialog(win, "Copy", "3 items", "Copy", "C:/x", True, move=False, local_completion=False)
    dlg.dest.setText("backup/")
    dlg.only.setText("*.jpg")
    a = dlg.answer()
    assert (a.dest, a.verify, a.only, a.flatten, a.newer) == ("backup/", True, "*.jpg", False, False)
    dlg.close()
    move = TransferDialog(win, "Move", "1 item", "Move", "C:/x", False, move=True, local_completion=False)
    assert move.only.isHidden() and move.flatten.isHidden()
    move.close()
