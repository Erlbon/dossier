"""Card 58B: F2 and New Folder work in the list. The Name cell becomes a text field; the rename and the folders are made by the same
plans as the boxes (checks, conflicts, undo). The shared ``world`` fixture turns the in-place editing off, so these tests turn it on."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

from dossier.gui.panel import InlineNameEdit  # noqa: E402


def listed(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def cursor_on(panel, name):
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


def editor_of(win):
    return win.left._name_delegate.editor if win.left.inline_editing() else None


def finish(win, text):
    """Type ``text`` over the name in the open editor and press Enter."""
    editor = editor_of(win)
    assert editor is not None
    editor.setText(text)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()


@pytest.fixture
def inplace(world):
    world[0].edit_in_place = True
    return world


def test_f2_opens_the_name_with_the_name_before_the_extension_selected(inplace):
    win, dialogs, left, *_ = inplace
    (left / "report.txt").write_text("a")
    (left / "folder.v2").mkdir()
    listed(win, win.left, 3)
    cursor_on(win.left, "report.txt")
    key(win, Qt.Key.Key_F2)
    editor = editor_of(win)
    assert isinstance(editor, InlineNameEdit) and editor.text() == "report.txt" and editor.selectedText() == "report"
    assert not dialogs.names_asked if hasattr(dialogs, "names_asked") else True        # no box
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    cursor_on(win.left, "folder.v2")
    key(win, Qt.Key.Key_F2)
    assert editor_of(win).selectedText() == "folder.v2"                                 # a folder: all of it
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)


def test_enter_and_esc_in_the_editor_do_not_reach_the_list_behind(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    listed(win, win.left, 3)
    win.selection.add([str(left / "b.txt")])
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F2)
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)              # Esc in the list would clear the marks
    QApplication.processEvents()
    assert win.selection.paths() == [str(left / "b.txt")]
    key(win, Qt.Key.Key_F2)
    QTest.keyClick(editor_of(win), Qt.Key.Key_Return)              # Enter in the list would open the file
    pump(win)
    assert not win.editors and not getattr(win, "viewers", [])


def test_enter_renames_and_ctrl_z_undoes_it(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F2)
    finish(win, "b.txt")
    pump(win, lambda: (left / "b.txt").exists())
    assert not (left / "a.txt").exists() and editor_of(win) is None and not dialogs.infos
    pump(win, lambda: win.left.current_name() == "b.txt")
    key(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump(win, lambda: (left / "a.txt").exists())
    assert not (left / "b.txt").exists()


def test_esc_and_an_unchanged_name_leave_the_file_alone(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F2)
    editor_of(win).setText("zzz.txt")
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert editor_of(win) is None and (left / "a.txt").exists() and not (left / "zzz.txt").exists()
    key(win, Qt.Key.Key_F2)
    finish(win, "a.txt")
    pump(win)
    assert (left / "a.txt").exists() and not dialogs.infos and len(win.undo_log) == 0


def test_a_taken_or_bad_name_is_refused_as_the_box_refuses_it(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    listed(win, win.left, 3)
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F2)
    finish(win, "b.txt")
    pump(win, lambda: dialogs.infos)
    assert "already exists" in dialogs.infos[-1][1] and (left / "a.txt").read_text() == "a" and (left / "b.txt").read_text() == "b"
    dialogs.infos.clear()
    cursor_on(win.left, "a.txt")
    key(win, Qt.Key.Key_F2)
    finish(win, "x|y" if os.name == "nt" else "..")
    pump(win, lambda: dialogs.infos)
    assert (left / "a.txt").exists()


def test_the_rename_command_edits_the_real_name_of_a_file(inplace):
    win, _d, left, *_ = inplace
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    win.rename()                                                   # the menu command, not the key
    assert editor_of(win).text() == "a.txt"
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)


def test_the_thumbnails_view_still_asks_in_the_box(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    win.left.set_view_mode("icons", 64)
    cursor_on(win.left, "a.txt")
    dialogs.texts = ["b.txt"]
    win.rename()
    assert editor_of(win) is None
    pump(win, lambda: (left / "b.txt").exists())


def test_new_folder_is_made_in_place_and_left_open_for_typing(inplace):
    win, dialogs, left, *_ = inplace
    listed(win, win.left, 1)
    key(win, Qt.Key.Key_F7)
    pump(win, lambda: editor_of(win) is not None)
    assert (left / "New Folder").is_dir() and editor_of(win).text() == "New Folder" and editor_of(win).selectedText() == "New Folder"
    assert not dialogs.texts and not dialogs.infos
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)              # Esc keeps "New Folder"
    QApplication.processEvents()
    assert (left / "New Folder").is_dir() and win.left.current_name() == "New Folder"
    key(win, Qt.Key.Key_F7)
    pump(win, lambda: editor_of(win) is not None)
    assert (left / "New Folder 2").is_dir() and editor_of(win).text() == "New Folder 2"
    QTest.keyClick(editor_of(win), Qt.Key.Key_Escape)


def test_typing_a_name_over_new_folder_renames_it(inplace):
    win, dialogs, left, *_ = inplace
    listed(win, win.left, 1)
    key(win, Qt.Key.Key_F7)
    pump(win, lambda: editor_of(win) is not None)
    finish(win, "projects")
    pump(win, lambda: (left / "projects").is_dir() and not (left / "New Folder").exists())
    assert not dialogs.infos


def test_a_b_c_typed_over_new_folder_makes_the_nested_folders(inplace):
    win, dialogs, left, *_ = inplace
    (left / "a").mkdir()                                           # a is there: only b and c are made
    listed(win, win.left, 2)
    key(win, Qt.Key.Key_F7)
    pump(win, lambda: editor_of(win) is not None)
    finish(win, "a/b/c")
    pump(win, lambda: (left / "a" / "b" / "c").is_dir() and not (left / "New Folder").exists() and len(win.undo_log) == 2)
    assert not dialogs.infos, dialogs.infos
    assert [s.a for s in win.undo_log._actions[-1].steps] == [str(left / "a" / "b"), str(left / "a" / "b" / "c")]


def test_a_bad_nested_name_keeps_new_folder(inplace):
    win, dialogs, left, *_ = inplace
    listed(win, win.left, 1)
    key(win, Qt.Key.Key_F7)
    pump(win, lambda: editor_of(win) is not None)
    finish(win, "ok/bad|name" if os.name == "nt" else "ok/..")
    pump(win, lambda: dialogs.infos)
    assert (left / "New Folder").is_dir() and not (left / "ok").exists()


def test_keys_typed_in_the_editor_stay_in_the_editor(inplace):
    win, dialogs, left, *_ = inplace
    (left / "abcd").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "abcd")
    key(win, Qt.Key.Key_F2)
    editor = editor_of(win)
    editor.setText("abcd")
    editor.setCursorPosition(1)
    QTest.keyClick(editor, Qt.Key.Key_Delete)                      # Delete would delete the file
    assert editor.text() == "acd"
    QTest.keyClick(editor, Qt.Key.Key_Space)                       # Space would mark it
    QTest.keyClick(editor, Qt.Key.Key_Plus)                        # + would open Mark by Pattern
    QTest.keyClick(editor, Qt.Key.Key_Minus)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)                   # Backspace would go up a folder
    QTest.keyClick(editor, Qt.Key.Key_Left)
    QTest.keyClick(editor, Qt.Key.Key_Home)
    QTest.keyClick(editor, Qt.Key.Key_End)
    QTest.keyClick(editor, Qt.Key.Key_Z)
    QApplication.processEvents()
    assert editor.text() == "a +cdz"
    assert editor_of(win) is editor and (left / "abcd").exists()
    assert len(win.selection) == 0 and not dialogs.confirms and not dialogs.infos and win.left.path == str(left)
    QTest.keyClick(editor, Qt.Key.Key_Escape)
