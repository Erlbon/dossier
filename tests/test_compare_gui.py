"""Compare Folders and Synchronize in the window: the options, the list of differences with their actions, and the hand-over to the queue."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core import compare as cmp  # noqa: E402
from dossier.gui.compare_folders import CompareOptionsDialog, CompareResultDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

T0 = 1_700_000_000


def put(path, data, mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def example(left, right):
    put(left / "only_l.txt", b"L")
    put(left / "new_l.txt", b"newer on the left", T0 + 600)
    put(right / "new_l.txt", b"old", T0)
    put(right / "only_r.txt", b"R")
    put(left / "sub" / "deep.txt", b"deep")


def ready(win, *panels):
    for p in panels or (win.left, win.right):
        p.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 1 and win.right.model.entry_count() >= 1)


def answer(monkeypatch, win, result=None, options=True):
    monkeypatch.setattr(type(win), "_ask_compare_options", lambda self, dlg: options)
    seen = []

    def on_result(self, dlg):
        seen.append(dlg)
        return result(dlg) if result else False
    monkeypatch.setattr(type(win), "_ask_compare_result", on_result)
    return seen


def test_the_options_dialog_returns_the_choices_and_they_are_remembered(world, monkeypatch):
    win, d, left, right, tmp = world
    dlg = CompareOptionsDialog(win, str(left), str(right), win.compare_options())
    assert dlg.values() == {"recursive": True, "by": "size_time", "tolerance": 2.0, "ignore_hour": True, "include_same": False}
    example(left, right)
    ready(win)
    def pick(dlg2):
        return False
    seen = answer(monkeypatch, win, result=pick)
    monkeypatch.setattr(type(win), "_ask_compare_options", lambda self, dlg: (dlg.by.setCurrentIndex(2), dlg.same.setChecked(True), True)[2])
    win.compare_folders()
    pump(win, lambda: seen)
    assert win.compare_options()["by"] == "content" and win.compare_options()["include_same"] is True


def test_synchronizing_to_the_right_copies_what_is_new_and_leaves_the_rest(world, monkeypatch):
    win, d, left, right, tmp = world
    example(left, right)
    ready(win)

    def run(dlg):
        assert {r.rel: r.status for r in dlg.result.rows} == {"new_l.txt": "left_newer", "only_l.txt": "only_left", "only_r.txt": "only_right",
                                                              "sub": "only_left"}
        assert dlg.current_mode() == "update_right" and dlg.sync_button.isEnabled()
        assert "copy 3 to the right" in dlg.what.text().lower()
        dlg._finish("sync")
        return True
    answer(monkeypatch, win, result=run)
    win.compare_folders()
    pump(win, lambda: d.confirms)
    pump(win, lambda: (right / "only_l.txt").exists() and (right / "sub" / "deep.txt").exists()
         and (right / "new_l.txt").read_bytes() == b"newer on the left")
    assert (right / "only_r.txt").exists() and "Synchronize" in d.confirms[-1][0] and "3 to the right" in d.confirms[-1][1]


def test_mirroring_deletes_the_extras_to_the_bin_after_saying_so(world, monkeypatch):
    win, d, left, right, tmp = world
    example(left, right)
    ready(win)

    def mirror(dlg):
        dlg.mode.setCurrentIndex(dlg.mode.findData("mirror_right"))
        assert "delete 1 on the right" in dlg.what.text()
        dlg._finish("sync")
        return True
    answer(monkeypatch, win, result=mirror)
    win.compare_folders()
    pump(win, lambda: d.confirms)
    pump(win, lambda: not (right / "only_r.txt").exists() and (right / "only_l.txt").exists())
    assert any(n.endswith("only_r.txt") for n in os.listdir(tmp / "bin"))                          # to the bin, not for good
    assert "recycle bin" in d.confirms[-1][1] or "trash" in d.confirms[-1][1]


def test_rows_that_are_unchecked_are_left_alone_and_a_refused_confirmation_does_nothing(world, monkeypatch):
    win, d, left, right, tmp = world
    example(left, right)
    ready(win)

    def one_only(dlg):
        for item, row in dlg.items:
            item.setCheckState(0, Qt.CheckState.Checked if row.rel == "only_l.txt" else Qt.CheckState.Unchecked)
        assert "copy 1 to the right" in dlg.what.text().lower()
        dlg._finish("sync")
        return True
    answer(monkeypatch, win, result=one_only)
    win.compare_folders()
    pump(win, lambda: (right / "only_l.txt").exists())
    assert not (right / "sub").exists() and (right / "new_l.txt").read_bytes() == b"old"
    d.confirm_answer = False
    answer(monkeypatch, win, result=lambda dlg: (dlg._finish("sync"), True)[1])
    win.compare_folders()
    pump(win, lambda: len(d.confirms) >= 2)
    pump(win)
    assert not (right / "sub").exists()


def test_marking_the_differences_marks_each_side_in_its_own_panel(world, monkeypatch):
    win, d, left, right, tmp = world
    example(left, right)
    ready(win)
    answer(monkeypatch, win, result=lambda dlg: (dlg._finish("mark"), True)[1])
    win.compare_folders()
    pump(win, lambda: str(left / "only_l.txt") in win.selection)
    assert str(right / "only_r.txt") in win.selection and str(left / "new_l.txt") in win.selection
    assert str(right / "new_l.txt") not in win.selection                       # the older copy is not a difference to act on
    assert (left / "only_l.txt").exists()


def test_alike_folders_the_same_folder_and_the_home_page_are_said_not_asked(world, monkeypatch):
    win, d, left, right, tmp = world
    put(left / "a.txt", b"a")
    put(right / "a.txt", b"a")
    ready(win)
    answer(monkeypatch, win)
    win.compare_folders()
    pump(win, lambda: d.infos)
    assert "alike" in d.infos[-1][1]
    win.right.set_folder(str(left))
    pump(win, lambda: win.right.path == str(left))
    win.compare_folders()
    assert "same folder" in win.status.text()
    win.right.set_folder("home://")
    pump(win, lambda: win.right.is_home)
    win.compare_folders()
    assert "Both panels must show a folder" in win.status.text()


def test_the_result_dialog_filters_rows_and_greys_out_rows_without_an_action(world):
    win, d, left, right, tmp = world
    example(left, right)
    result = cmp.compare_trees(win.fs, str(left), str(right))
    dlg = CompareResultDialog(win, result, "update_right")
    only_right = next(item for item, row in dlg.items if row.status == "only_right")
    assert not bool(only_right.flags() & Qt.ItemFlag.ItemIsUserCheckable) and only_right.text(4) == ""
    dlg.filters["only_right"].setChecked(False)
    assert only_right.isHidden()
    dlg.mode.setCurrentIndex(dlg.mode.findData("both"))
    assert bool(only_right.flags() & Qt.ItemFlag.ItemIsUserCheckable) and "Copy to the left" in only_right.text(4)
    dlg.mode.setCurrentIndex(dlg.mode.findData("mirror_left"))
    newer = next(item for item, row in dlg.items if row.rel == "new_l.txt")
    assert "replaces a newer file" in newer.text(4)


def test_two_files_are_compared_byte_by_byte_and_the_first_difference_is_said(world):
    win, d, left, right, tmp = world
    put(left / "f.bin", b"0123456789")
    put(right / "g.bin", b"0123X56789")
    ready(win)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("f.bin"), 0))
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("g.bin"), 0))
    win._set_active(win.left)
    win.compare_files()
    pump(win, lambda: d.infos)
    assert "differ" in d.infos[-1][1] and "byte 4" in d.infos[-1][1] and "0x4" in d.infos[-1][1]
    put(right / "g.bin", b"0123456789")
    ready(win, win.right)
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("g.bin"), 0))
    win.compare_files()
    pump(win, lambda: len(d.infos) >= 2)
    assert "identical" in d.infos[-1][1]


def test_the_cursor_must_be_on_a_file_in_each_panel(world):
    win, d, left, right, tmp = world
    put(left / "f.bin", b"1")
    ready(win)
    win.compare_files()
    assert "cursor on a file in each panel" in win.status.text()


def test_the_context_menu_of_empty_space_offers_it(world):
    win, d, left, right, tmp = world
    put(left / "f.bin", b"1")
    ready(win)
    texts = [a.text().split("\t")[0] for a in win.build_context_menu(win.left, -1).actions() if not a.isSeparator()]
    assert "Compare with the Other Panel..." in texts
