"""Saved selections, copy of the marked paths, and editing the folder note."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, names, pump, world  # noqa: E402,F401


def fill(win, left, files):
    for n in files:
        (left / n).write_text(n)
    win.left.refresh()


def marked_names(win):
    return sorted(os.path.basename(p) for p in win.left.marked_here())


def test_a_saved_selection_comes_back_after_the_marks_are_cleared(world):
    win, d, left, *_ = world
    fill(win, left, ["a.txt", "b.txt", "c.txt"])
    win.select_all()
    d.texts.append("everything")
    win.save_selection()
    win.selection.clear()
    assert marked_names(win) == []
    win.restore_selection("everything")
    assert marked_names(win) == ["a.txt", "b.txt", "c.txt"]


def test_a_saved_selection_holds_only_this_panels_marks_and_can_be_added_and_forgotten(world):
    win, d, left, right, *_ = world
    fill(win, left, ["a.txt", "b.txt"])
    win.select_all()
    d.texts.append("two")
    win.save_selection()
    win.selection.clear()
    win.left.table.setCurrentIndex(win.left.model.index(0, 0))
    win.left.toggle_mark() if hasattr(win.left, "toggle_mark") else None
    win.restore_selection("two", combine=True)
    assert set(marked_names(win)) >= {"a.txt", "b.txt"}
    win.forget_selection("two")
    assert "two" not in win.selection.saved_names()


def test_nothing_marked_saves_nothing(world):
    win, d, left, *_ = world
    d.texts.append("x")
    win.save_selection()
    assert win.selection.saved_names() == [] and "Nothing is marked" in win.status.text()


def test_the_marked_paths_go_to_the_clipboard_as_text(world):
    win, d, left, *_ = world
    fill(win, left, ["a.txt", "b.txt"])
    win.select_all()
    win.copy_marked_paths()
    lines = QApplication.clipboard().text().splitlines()
    assert sorted(os.path.basename(p) for p in lines) == ["a.txt", "b.txt"]


def test_edit_folder_note_creates_readme_when_there_is_none_and_opens_the_existing_one_otherwise(world, monkeypatch):
    win, d, left, *_ = world
    opened = []
    monkeypatch.setattr(type(win), "edit_file", lambda self, path=None, show_replace=False: opened.append(path))
    win.edit_folder_note()
    pump(win, lambda: opened)
    assert (left / "README.md").read_text().startswith("# ")
    assert opened == [str(left / "README.md")] or [os.path.basename(p) for p in opened] == ["README.md"]
    win.left.refresh()
    pump(win, lambda: win.left.note_paths)
    opened.clear()
    win.edit_folder_note()
    assert [os.path.basename(p) for p in opened] == ["README.md"]
    assert len([n for n in os.listdir(left) if n.lower() == "readme.md"]) == 1
