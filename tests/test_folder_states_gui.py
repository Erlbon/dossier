"""Tools > Compare > Remember This Folder's State and What Changed Since... in the window (card 65)."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core import folder_states as fstates  # noqa: E402
from dossier.gui.folder_states import ChangesDialog, StatePickerDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def refresh(win):
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 1)


def states_of(win, left):
    return fstates.list_states(win._folder_states_dir(), str(left))


def test_the_compare_menu_has_both_commands(world):
    win, d, left, right, tmp = world
    tools = [a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Tools"][0]
    compare = [a.menu() for a in tools.actions() if a.menu() and a.text() == "Compare"][0]
    texts = [a.text() for a in compare.actions() if a.text()]
    assert "Remember This Folder's State" in texts and "What Changed Since..." in texts


def test_remembering_keeps_a_state_in_dossiers_folder_and_nothing_in_the_users(world):
    win, d, left, right, tmp = world
    put(left / "a.txt", b"one")
    put(left / "sub" / "b.txt", b"two")
    refresh(win)
    before = sorted(os.listdir(str(left)))
    win.remember_folder_state()
    pump(win, lambda: states_of(win, left))
    (state,) = states_of(win, left)
    assert state.files == 2 and os.path.normpath(os.path.dirname(state.csv_path)) == str(tmp / "folder-states")
    assert sorted(os.listdir(str(left))) == before                                   # nothing was written into the user's folder


def test_what_changed_lists_added_changed_moved_and_removed_and_marks_the_checked(world, monkeypatch):
    win, d, left, right, tmp = world
    a = put(left / "a.txt", b"one")
    put(left / "edit.txt", b"before")
    put(left / "gone.txt", b"bye")
    put(left / "old" / "m.txt", b"moving")
    refresh(win)
    win.remember_folder_state()
    pump(win, lambda: states_of(win, left))
    put(left / "edit.txt", b"after, longer")
    os.remove(str(left / "gone.txt"))
    os.makedirs(str(left / "new"), exist_ok=True)
    os.replace(str(left / "old" / "m.txt"), str(left / "new" / "m.txt"))
    added = put(left / "added.txt", b"fresh")
    seen = {}

    def pick(self, dlg):
        assert isinstance(dlg, StatePickerDialog) and dlg.list.count() == 1
        dlg._go()
        return True

    def result(self, dlg):
        assert isinstance(dlg, ChangesDialog)
        seen["counts"] = {k: dlg.changes.count(k) for k in fstates.STATUSES}
        gone = [item for item, row in dlg.items if row.status == fstates.REMOVED][0]
        assert not (gone.flags() & Qt.ItemFlag.ItemIsUserCheckable)                   # removed: nothing to act on, no check box
        for item, row in dlg.items:
            if row.status == fstates.ADDED:
                item.setCheckState(0, Qt.CheckState.Checked)
        assert dlg.mark_button.isEnabled() and "1 checked" in dlg.counts.text()
        dlg._finish("mark")
        return True
    monkeypatch.setattr(type(win), "_ask_state_picker", pick)
    monkeypatch.setattr(type(win), "_ask_changes_result", result)
    win.what_changed_since()
    pump(win, lambda: "counts" in seen)
    pump(win, lambda: added in win.selection)
    assert seen["counts"] == {fstates.ADDED: 1, fstates.CHANGED: 1, fstates.MOVED: 1, fstates.REMOVED: 1}
    assert a not in win.selection and os.path.exists(added)                          # marking changes nothing


def test_forgetting_a_state_from_the_picker_deletes_it(world, monkeypatch):
    win, d, left, right, tmp = world
    put(left / "a.txt", b"one")
    refresh(win)
    win.remember_folder_state()
    pump(win, lambda: states_of(win, left))
    csv_path = states_of(win, left)[0].csv_path

    def pick(self, dlg):
        dlg.forget.click()
        assert dlg.list.count() == 0 and not dlg.go.isEnabled()
        return False
    monkeypatch.setattr(type(win), "_ask_state_picker", pick)
    win.what_changed_since()
    pump(win, lambda: not os.path.exists(csv_path))
    assert states_of(win, left) == [] and d.confirms and "Forget" in d.confirms[-1][0]


def test_with_no_state_remembered_it_says_so(world):
    win, d, left, right, tmp = world
    win.what_changed_since()
    pump(win, lambda: d.infos)
    assert "No state of this folder" in d.infos[-1][1]


def test_nothing_changed_says_so(world, monkeypatch):
    win, d, left, right, tmp = world
    put(left / "a.txt", b"one")
    refresh(win)
    win.remember_folder_state()
    pump(win, lambda: states_of(win, left))
    monkeypatch.setattr(type(win), "_ask_state_picker", lambda self, dlg: dlg._go() or True)
    win.what_changed_since()
    pump(win, lambda: d.infos)
    assert "Nothing has changed" in d.infos[-1][1]
