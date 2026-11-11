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
    win.copy_with_box()


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
    win.move_with_box()
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
    win.copy_with_box()
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


# copy plan step 5: finish the job ------------------------------------------------------------------------------------------------
def test_skip_what_is_already_there_and_the_same(world):
    win, dialogs, left, right, _t = world
    when = time.time() - 1000
    for name, data in (("same.txt", b"one"), ("changed.txt", b"new!"), ("missing.txt", b"m")):
        (left / name).write_bytes(data)
        os.utime(left / name, (when, when))
    (right / "same.txt").write_bytes(b"one")
    os.utime(right / "same.txt", (when + 3600, when + 3600))                 # an hour off: a summer-time change, still the same
    (right / "changed.txt").write_bytes(b"old")
    os.utime(right / "changed.txt", (when - 500, when - 500))               # older than the one copied over it
    listed(win, win.left, 4)
    win.selection.add([str(left / n) for n in ("same.txt", "changed.txt", "missing.txt")])
    dialogs.conflict_answer = None                                           # no question may come: "same" is not asked about
    copy_with(win, dialogs, skip_same=True, newer=True)
    pump(win, lambda: (right / "missing.txt").exists() and (right / "changed.txt").read_bytes() == b"new!")
    assert (right / "same.txt").read_bytes() == b"one" and int(os.stat(right / "same.txt").st_mtime) == int(when + 3600)


def test_with_verify_the_same_means_the_same_bytes(tmp_path):
    from dossier.core.ops import plan_copy, skip_same
    from dossier.core.vfs import LocalFileSystem
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for side, data in (("a", b"abc"), ("b", b"abd")):                       # same size and time, other bytes
        (tmp_path / side / "f.txt").write_bytes(data)
        os.utime(tmp_path / side / "f.txt", (1_700_000_000, 1_700_000_000))
    fs = LocalFileSystem()
    plan = plan_copy(fs, [str(tmp_path / "a" / "f.txt")], str(tmp_path / "b"))
    assert not skip_same(plan, fs).ops                                       # by size and time: the same, left out
    assert len(skip_same(plan, fs, by_content=True).ops) == 1                # by content: different, copied


# the code review of 2026-11-05 ---------------------------------------------------------------------------------------------------
def _clash(tmp_path, src_time, dst_time, data=(b"abc", b"abc")):
    from dossier.core.ops import plan_copy
    from dossier.core.vfs import LocalFileSystem
    for side, d, t in (("a", data[0], src_time), ("b", data[1], dst_time)):
        (tmp_path / side).mkdir(exist_ok=True)
        (tmp_path / side / "f.txt").write_bytes(d)
        os.utime(tmp_path / side / "f.txt", (1_700_000_000 + t, 1_700_000_000 + t))
    fs = LocalFileSystem()
    return plan_copy(fs, [str(tmp_path / "a" / "f.txt")], str(tmp_path / "b")), fs


def test_skip_same_by_content_can_be_cancelled(tmp_path):
    from dossier.core.ops import skip_same
    from dossier.core.progress import Cancelled, CancelToken
    plan, fs = _clash(tmp_path, 0, 0)
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        skip_same(plan, fs, by_content=True, cancel=token)

    def watch(n):                                                            # the planning job's Cancel, as the window hands it over
        raise Cancelled()
    watch.cancel = None
    with pytest.raises(Cancelled):
        skip_same(plan, fs, by_content=True, watch=watch)


def test_the_window_hands_its_cancel_to_skip_same(world, monkeypatch):
    from dossier.core import ops
    from dossier.gui import transfer
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("a")
    (right / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    seen = {}

    def spy(plan, fs, by_content=False, cancel=None, watch=None):
        seen.update(cancel=cancel, watch=watch)
        return ops.skip_same(plan, fs, by_content, cancel, watch)
    monkeypatch.setattr(transfer, "skip_same", spy)
    copy_with(win, dialogs, skip_same=True, verify=True)
    pump(win, lambda: seen)
    assert seen["cancel"] is not None and seen["watch"] is not None


def test_unknown_times_are_never_the_same(tmp_path):
    from dataclasses import replace
    from dossier.core.ops import skip_same
    plan, fs = _clash(tmp_path, 0, 0, (b"abc", b"xyz"))
    unknown = replace(plan, ops=tuple(replace(op, src_mtime=0.0, dst_mtime=0.0) for op in plan.ops))
    assert len(skip_same(unknown, fs).ops) == 1                              # a server that gives no times: copied, not guessed


def test_the_conflict_box_and_skip_same_agree_on_the_summer_time_hour(tmp_path):
    from dossier.core.ops import looks_identical, skip_same
    plan, fs = _clash(tmp_path, 0, 3600)
    assert looks_identical(plan.ops[0]) and not skip_same(plan, fs).ops
