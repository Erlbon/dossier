"""Batch rename through the shared dialogs of redactor_common, fed with the marked files."""
import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("redactor_common")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QDialog  # noqa: E402

from redactor_common.gui.auto_numbering_dialog import AutoNumberingDialog  # noqa: E402
from redactor_common.gui.case_conversion_dialog import CaseConversionDialog  # noqa: E402
from redactor_common.gui.rename_pattern_dialog import RenamePatternDialog  # noqa: E402
from redactor_common.gui.search_replace_dialog import SearchReplaceDialog  # noqa: E402

from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401

ACCEPTED = QDialog.DialogCode.Accepted


def answer(monkeypatch, cls, fill, result=ACCEPTED):
    """Make ``cls.exec`` fill the dialog in and 'press' OK (or Cancel), recording the dialog."""
    shown = []

    def fake(self):
        shown.append(self)
        fill(self)
        return result

    monkeypatch.setattr(cls, "exec", fake)
    return shown


def mark_all(win, left, files):
    for n in files:
        (left / n).write_text(n)
    win.left.refresh()
    win.select_all()


def listing(path):
    return sorted(os.listdir(path))


def test_rename_by_pattern_numbers_the_files_in_the_order_of_the_list_and_keeps_the_extension(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["b.txt", "a.txt", "c.jpg"])
    win.left.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)               # the list shows c, b, a
    shown = answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("%counter% - %name%"))
    win.rename_by_pattern()
    wait_planned(win)
    pump(win, lambda: not win.busy)
    assert listing(left) == ["1 - c.jpg", "2 - b.txt", "3 - a.txt"]             # counted in the order shown, extension kept
    assert shown and shown[0].pattern_edit.text() == "%counter% - %name%"


def test_the_counter_can_be_zero_padded_and_dates_come_from_the_file(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt", "b.txt"])
    os.utime(left / "a.txt", (1_700_000_000, 1_700_000_000))                       # 14 Nov 2023
    os.utime(left / "b.txt", (1_700_000_000, 1_700_000_000))
    win.left.refresh()
    win.select_all()

    def fill(d):
        d.pattern_edit.setText("%year%-%month%-%day% %counter%")
        d.zero_pad_cb.setChecked(True)
        d.zero_pad_width_combo.setCurrentIndex(d.zero_pad_width_combo.findData(3))

    answer(monkeypatch, RenamePatternDialog, fill)
    win.rename_by_pattern()
    pump(win, lambda: not win.busy)
    result = listing(left)
    assert len(result) == 2 and all(n.startswith("2023-11-1") and n.endswith(".txt") for n in result)
    assert [n.split(" ")[1].split(".")[0] for n in result] == ["001", "002"]


def test_only_files_are_renamed_by_pattern_and_the_folders_are_named_as_left_out(world, monkeypatch):
    win, _d, left, *_ = world
    (left / "folder.v1").mkdir()
    mark_all(win, left, ["a.txt"])
    win.select_all()
    answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("new_%name%"))
    win.rename_by_pattern()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["folder.v1", "new_a.txt"]
    win.select_all()
    assert [e.name for e in win._entries_to_rename(files_only=True)] == ["new_a.txt"]
    assert "1 folder left out" in win.status.text()


def test_nothing_marked_says_what_to_do_and_a_cancel_changes_nothing(world, monkeypatch):
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    shown = answer(monkeypatch, RenamePatternDialog, lambda d: None)
    win.rename_by_pattern()
    assert not shown and "Mark the files" in win.status.text()
    win.select_all()
    answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("zzz"), result=QDialog.DialogCode.Rejected)
    win.rename_by_pattern()
    assert listing(left) == ["a.txt"]


def test_the_copy_and_move_modes_of_the_shared_dialog_are_not_offered(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt"])
    shown = answer(monkeypatch, RenamePatternDialog, lambda d: None, result=QDialog.DialogCode.Rejected)
    win.rename_by_pattern()
    d = shown[0]
    assert d.rename_radio.isChecked() and not d.export_radio.isVisibleTo(d) and not d.move_radio.isVisibleTo(d)


def test_the_pattern_is_remembered_for_next_time(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt"])
    answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("kept_%name%"))
    win.rename_by_pattern()
    pump(win, lambda: not win.busy)
    (left / "x.txt").write_text("x")
    win.left.refresh()
    win.select_all()
    shown = answer(monkeypatch, RenamePatternDialog, lambda d: None, result=QDialog.DialogCode.Rejected)
    win.rename_by_pattern()
    assert shown[-1].pattern_edit.text() == "kept_%name%"


def test_a_rename_is_one_undo_and_the_marks_follow_the_files(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt", "b.txt"])
    answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("new_%name%"))
    win.rename_by_pattern()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["new_a.txt", "new_b.txt"]
    assert sorted(os.path.basename(p) for p in win.selection.paths()) == ["new_a.txt", "new_b.txt"]
    win.undo()
    assert listing(left) == ["a.txt", "b.txt"]


def test_names_that_would_collide_get_a_number_instead_of_overwriting(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt", "b.txt", "c.txt"])
    answer(monkeypatch, RenamePatternDialog, lambda d: d.pattern_edit.setText("same"))
    win.rename_by_pattern()
    pump(win, lambda: not win.busy)
    result = listing(left)
    assert len(result) == 3 and len(set(result)) == 3 and all(n.startswith("same") for n in result)


def test_search_and_replace_changes_the_whole_name_including_the_extension(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["IMG_1.jpeg", "IMG_2.jpeg", "notes.txt"])

    def fill(d):
        d.search_edit.setText("IMG")
        d.replace_edit.setText("Holiday")

    answer(monkeypatch, SearchReplaceDialog, fill)
    win.rename_search_replace()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["Holiday_1.jpeg", "Holiday_2.jpeg", "notes.txt"]


def test_search_and_replace_with_a_regex_and_a_bad_regex_changes_nothing(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["file 01.txt", "file 02.txt"])

    def fill(d):
        d.search_edit.setText(r"file (\d+)")
        d.replace_edit.setText(r"\1-file")
        d.regex_cb.setChecked(True)

    answer(monkeypatch, SearchReplaceDialog, fill)
    win.rename_search_replace()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["01-file.txt", "02-file.txt"]


def test_case_conversion_changes_the_name_and_keeps_the_extension(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["my file.TXT", "other.md"])

    def fill(d):
        d.mode_combo.setCurrentIndex(d.mode_combo.findText("UPPERCASE"))

    answer(monkeypatch, CaseConversionDialog, fill)
    win.rename_case()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["MY FILE.TXT", "OTHER.md"]                        # the stem changes, the extension is as it was
    answer(monkeypatch, CaseConversionDialog, lambda d: d.mode_combo.setCurrentIndex(d.mode_combo.findText("Title Case")))
    win.select_all()
    win.rename_case()
    pump(win, lambda: not win.busy)
    assert listing(left) == ["My File.TXT", "Other.md"]


def test_numbering_puts_a_number_in_front_of_the_name_in_list_order(world, monkeypatch):
    win, _d, left, *_ = world
    mark_all(win, left, ["a.txt", "b.txt", "c.txt"])
    answer(monkeypatch, AutoNumberingDialog, lambda d: None)
    win.rename_number()
    pump(win, lambda: not win.busy)
    result = listing(left)
    assert len(result) == 3 and all(n[:2].isdigit() for n in result)
    assert [n.split(" - ")[-1] for n in result] == ["a.txt", "b.txt", "c.txt"]


def test_the_menu_has_the_four_commands(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    sub = [a for a in menus["Tools"].actions() if a.text() == "Batch Rename"][0].menu()
    assert [a.text() for a in sub.actions()] == ["By Pattern...", "Search and Replace in Names...", "Change Case...",
                                                 "Number the Files..."]
