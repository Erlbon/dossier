"""Planned operations (core/planned.py, gui/planned_ops.py): Shift+F5/F6 add to a list kept on disk, Ctrl+F3 shows it, entries are planned
again when they run (the intention, not a frozen file list), kept ones stay and rerun as "missing or changed" with no questions. The
owner's decisions: CLAUDE.md, "Planned operations" (2026-11-11)."""
import json
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QItemSelectionModel, Qt  # noqa: E402

from dossier.core.planned import PlannedEntry, PlannedList, default_name  # noqa: E402
from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


# the list on disk -------------------------------------------------------------------------------------------------------------------
def test_the_list_keeps_order_updates_in_place_and_survives_a_damaged_file(tmp_path):
    lst = PlannedList(str(tmp_path / "planned.json"))
    a = PlannedEntry("copy", ("C:/a",), "D:/x")
    b = PlannedEntry("move", ("C:/b", "C:/c"), "D:/y")
    lst.add(a)
    lst.add(b)
    assert [e.id for e in lst.load()] == [a.id, b.id]
    lst.move(b.id, -1)
    assert [e.id for e in lst.load()] == [b.id, a.id]
    kept = a.kept(True)
    lst.update(kept)
    got = lst.get(a.id)
    assert got.keep and got.skip_same and got.name == default_name(a) == "a to x"          # a kept copy: missing or changed
    assert got.rerun_rule() == "missing or changed" and b.kept(True).skip_same is False     # a move has no rerun rule
    lst.remove(b.id)
    assert [e.id for e in lst.load()] == [a.id]
    lst.clear()
    assert lst.load() == [] and not os.path.exists(lst.path)
    (tmp_path / "planned.json").write_text("{not json")
    assert lst.load() == []
    (tmp_path / "planned.json").write_text(json.dumps([{"kind": "erase", "sources": ["x"], "dest": "y"}, {"kind": "copy"}]))
    assert lst.load() == []


# Shift+F5 and running --------------------------------------------------------------------------------------------------------------
def cursor_on(panel, name):
    panel.refresh()
    pump(panel.window(), lambda: panel.model.row_of(name) is not None)
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


def test_shift_f5_adds_to_the_list_and_copies_nothing_until_it_runs(world):
    win, dialogs, left, right, tmp = world
    (left / "a.txt").write_text("A")
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F5, Qt.KeyboardModifier.ShiftModifier)
    pump(win)
    entries = win.planned_list().load()
    assert len(entries) == 1 and entries[0].kind == "copy" and entries[0].dest == str(right)
    assert not (right / "a.txt").exists() and not dialogs.confirms                          # nothing asked, nothing copied
    assert os.path.exists(tmp / "planned.json")                                            # kept on disk
    win.run_planned([entries[0].id])
    pump(win, lambda: (right / "a.txt").exists())
    pump(win)
    assert (right / "a.txt").read_text() == "A" and win.planned_list().load() == []        # a one-off leaves the list


def test_plans_from_several_folders_run_in_order_and_see_what_is_on_disk_then(world):
    win, dialogs, left, right, tmp = world
    (left / "photos").mkdir()
    (left / "photos" / "one.jpg").write_text("1")
    (left / "notes.txt").write_text("N")
    cursor_on(win.left, "photos")
    win.plan_copy()
    cursor_on(win.left, "notes.txt")
    win.plan_move()
    (left / "photos" / "two.jpg").write_text("2")                                          # added after planning: comes along
    win.run_planned([e.id for e in win.planned_list().load()])
    pump(win, lambda: (right / "notes.txt").exists(), timeout=10)
    pump(win)
    assert (right / "photos" / "one.jpg").exists() and (right / "photos" / "two.jpg").exists()
    assert (right / "notes.txt").read_text() == "N" and not (left / "notes.txt").exists()
    assert win.planned_list().load() == []


def test_a_kept_copy_reruns_as_missing_or_changed_without_questions(world):
    win, dialogs, left, right, tmp = world
    (left / "docs").mkdir()
    (left / "docs" / "same.txt").write_text("same")
    (left / "docs" / "edit.txt").write_text("old")
    cursor_on(win.left, "docs")
    win.plan_copy()
    entry = win.planned_list().load()[0]
    win.planned_list().update(entry.kept(True, "Docs backup"))
    win.run_planned([entry.id])
    pump(win, lambda: (right / "docs" / "edit.txt").exists(), timeout=10)
    pump(win)
    after_first = win.planned_list().get(entry.id)
    assert after_first.keep and after_first.last_result == "done" and after_first.last_run > 0      # kept: it stays
    same_time = os.path.getmtime(right / "docs" / "same.txt")
    time.sleep(1.1)
    (left / "docs" / "edit.txt").write_text("new and longer")
    (left / "docs" / "added.txt").write_text("+")
    dialogs.confirms.clear()
    dialogs.conflict_answer = None                                                           # a conflict question would cancel
    win.run_planned([entry.id])
    pump(win, lambda: (right / "docs" / "added.txt").exists(), timeout=10)
    pump(win)
    assert (right / "docs" / "edit.txt").read_text() == "new and longer"                   # changed: replaced
    assert os.path.getmtime(right / "docs" / "same.txt") == same_time                      # the same: left alone
    assert win.planned_list().get(entry.id).last_result == "done"


def test_an_entry_whose_items_are_gone_stays_with_a_note(world):
    win, dialogs, left, right, tmp = world
    (left / "gone.txt").write_text("x")
    cursor_on(win.left, "gone.txt")
    win.plan_copy()
    (left / "gone.txt").unlink()
    entry = win.planned_list().load()[0]
    win.run_planned([entry.id])
    pump(win, lambda: bool(dialogs.infos))
    pump(win)
    assert "gone" in dialogs.infos[-1][1] and win.planned_list().get(entry.id).last_result == "not run"


def test_edit_opens_the_box_with_the_entrys_choices_and_saves_the_answer(world):
    win, dialogs, left, right, tmp = world
    (left / "a.txt").write_text("A")
    cursor_on(win.left, "a.txt")
    win.plan_copy()
    entry = win.planned_list().load()[0].kept(True, "A copy")
    win.planned_list().update(entry)
    dialogs.transfer_answer = {"dest": str(tmp / "elsewhere"), "newer": True, "skip_same": False}
    changed = win.edit_planned(entry)
    assert dialogs.transfer_offered_options == {"only": "", "flatten": False, "newer": False, "skip_same": True}
    saved = win.planned_list().get(entry.id)
    assert changed == saved and saved.dest == str(tmp / "elsewhere") and saved.rerun_rule() == "newer only"


def test_the_window_lists_the_entries_and_keep_asks_for_a_name(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    monkeypatch.setattr(win, "_show_planned_window", lambda w: None)                        # no window on screen in a test
    (left / "a.txt").write_text("A")
    cursor_on(win.left, "a.txt")
    win.plan_copy()
    win.show_planned()
    window = win._planned_window
    assert window.table.rowCount() == 1 and window.table.item(0, 0).text() == "Copy" and window.table.item(0, 2).text() == str(right)
    # selectRow reads the keyboard's modifiers, which an earlier test's Shift+F5 can leave behind: select through the model instead
    window.table.selectionModel().select(window.table.model().index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                                         | QItemSelectionModel.SelectionFlag.Rows)
    assert window.selected()
    dialogs.texts = ["Nightly"]
    window.toggle_keep()
    assert window.table.item(0, 4).text() == "★ Nightly" and window.table.item(0, 5).text() == "Missing or changed"
    assert window.buttons["edit"].isEnabled() and window.buttons["run_all"].isEnabled()
    pump(win, lambda: window.facts.text().startswith("Counted"))
    assert "1 file" in window.facts.text()
    window.close()
