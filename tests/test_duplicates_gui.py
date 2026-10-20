"""Find Duplicate Files in the window: the options, the groups with check boxes, and removing the extra copies the safe way."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core import duplicates as dup  # noqa: E402
from dossier.gui.duplicates import DuplicatesOptionsDialog, DuplicatesResultDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def put(path, data, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def make(left):
    """Two groups (3 and 2 copies) and a file that is alone."""
    paths = {n: put(left / n, b"A" * 4000, 100 + i) for i, n in enumerate(("a1.dat", "a2.dat", "a3.dat"))}
    paths.update({n: put(left / "sub" / n, b"B" * 7000, 500 + i) for i, n in enumerate(("b1.dat", "b2.dat"))})
    paths["alone"] = put(left / "alone.dat", b"C" * 123, 900)
    return paths


def refresh(win):
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)


def answer(monkeypatch, win, options=True, result=None):
    """Answer the two dialogs: ``result(dlg)`` works on the result dialog and returns whether it was accepted."""
    monkeypatch.setattr(type(win), "_ask_duplicates_options", lambda self, dlg: options)
    seen = []

    def on_result(self, dlg):
        seen.append(dlg)
        return result(dlg) if result else False
    monkeypatch.setattr(type(win), "_ask_duplicates_result", on_result)
    return seen


def test_the_options_dialog_collects_folders_size_and_name(world):
    win, d, left, right, tmp = world
    dlg = DuplicatesOptionsDialog(win, str(left), str(right), 5)
    assert dlg.roots() == [str(left)] and dlg.min_size() == 5 * 1024 and dlg.name() == ""
    dlg.other.setChecked(True)
    dlg.pattern.setText(" *.jpg ")
    assert dlg.roots() == [str(left), str(right)] and dlg.name() == "*.jpg"
    dlg.here.setChecked(False)
    dlg.other.setChecked(False)
    dlg._accept()
    assert "at least one folder" in dlg.problem.text() and dlg.result() == 0
    solo = DuplicatesOptionsDialog(win, str(left), "", 1)
    assert not solo.other.isEnabled() and solo.roots() == [str(left)]
    same = DuplicatesOptionsDialog(win, str(left), str(left), 1)
    same.other.setChecked(True)
    assert same.roots() == [str(left)]                                            # one folder is not looked at twice


def test_finding_and_deleting_the_extra_copies_keeps_the_oldest_of_each_group(world, monkeypatch):
    win, d, left, right, tmp = world
    paths = make(left)
    refresh(win)

    def delete_extras(dlg):
        assert len(dlg.result.groups) == 2 and dlg.result.wasted == 8000 + 7000
        dlg.policy.setCurrentIndex(0)                                              # keep the oldest
        dlg.check_extras()
        assert dlg.delete_button.isEnabled() and "3 checked" in dlg.counts.text()
        dlg._finish("delete")
        return True
    answer(monkeypatch, win, result=delete_extras)
    win.find_duplicate_files()
    pump(win, lambda: d.confirms)
    pump(win, lambda: not os.path.exists(paths["a2.dat"]) and not os.path.exists(paths["a3.dat"]) and not os.path.exists(paths["b2.dat"]))
    assert os.path.exists(paths["a1.dat"]) and os.path.exists(paths["b1.dat"]) and os.path.exists(paths["alone"])
    assert "3 item" in d.confirms[-1][1]                                           # the ordinary delete confirmation, for the 3 extras


def test_a_group_can_never_be_emptied(world, monkeypatch):
    win, d, left, right, tmp = world
    paths = make(left)
    refresh(win)
    holder = []

    def everything(dlg):
        holder.append(dlg)
        top = dlg._tops[0][0]
        for c in dlg._children(top):
            c.setCheckState(0, Qt.CheckState.Checked)                              # every copy of one group
        assert not dlg.delete_button.isEnabled() and "leave at least one" in dlg.counts.text()
        dlg._finish("delete")                                                      # the button is greyed out, but be sure
        return True
    answer(monkeypatch, win, result=everything)
    win.find_duplicate_files()
    pump(win, lambda: holder)
    pump(win)
    assert all(os.path.exists(p) for p in paths.values()) and any("At least one copy" in t for _title, t in d.infos)


def test_the_checked_copies_can_be_marked_in_the_panels(world, monkeypatch):
    win, d, left, right, tmp = world
    paths = make(left)
    refresh(win)

    def mark(dlg):
        dlg.policy.setCurrentIndex(1)                                              # keep the newest
        dlg.check_extras()
        dlg._finish("mark")
        return True
    answer(monkeypatch, win, result=mark)
    win.find_duplicate_files()
    pump(win, lambda: any(p in win.selection for p in paths.values()))
    marked = {p for p in paths.values() if p in win.selection}
    assert marked == {paths["a1.dat"], paths["a2.dat"], paths["b1.dat"]}           # a3 and b2 are the newest
    assert os.path.exists(paths["a1.dat"])                                         # marking deletes nothing


def test_all_the_copies_can_be_shown_in_a_tab(world, monkeypatch):
    win, d, left, right, tmp = world
    make(left)
    refresh(win)
    answer(monkeypatch, win, result=lambda dlg: (dlg._finish("tab"), True)[1])
    win.find_duplicate_files()
    pump(win, lambda: win.left.path.startswith("found://") and win.left.model.entry_count() >= 5)
    names = sorted(win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())
                   if not win.left.model.is_up_row(r))
    assert names == ["a1.dat", "a2.dat", "a3.dat", "b1.dat", "b2.dat"]


def test_no_duplicates_says_so_and_a_cancelled_dialog_does_nothing(world, monkeypatch):
    win, d, left, right, tmp = world
    put(left / "x", b"1", 1)
    put(left / "y", b"22", 1)
    refresh(win)
    answer(monkeypatch, win)
    win.find_duplicate_files()
    pump(win, lambda: d.infos)
    assert "No duplicates" in d.infos[-1][1]
    answer(monkeypatch, win, options=False)
    d.infos.clear()
    win.find_duplicate_files()
    pump(win)
    assert d.infos == []


def test_the_home_page_has_no_folder_to_look_in(world):
    win, d, left, right, tmp = world
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    win.find_duplicate_files()
    assert "Open a folder first" in win.status.text()


def test_the_result_dialog_keep_rules_check_the_others_and_uncheck_all(world):
    win, d, left, right, tmp = world
    make(left)
    result = dup.find_duplicates(win.fs, [str(left)])
    dlg = DuplicatesResultDialog(win, result)
    assert dlg.checked_paths() == [] and not dlg.delete_button.isEnabled() and not dlg.mark_button.isEnabled()
    dlg.policy.setCurrentIndex(2)
    dlg.check_extras()
    assert len(dlg.checked_paths()) == 3 and dlg.delete_button.isEnabled() and dlg.mark_button.isEnabled()
    dlg.uncheck_all()
    assert dlg.checked_paths() == [] and "0 checked" in dlg.counts.text()


def test_the_context_menu_offers_it_for_folders_and_empty_space(world):
    win, d, left, right, tmp = world
    (left / "folder").mkdir()
    (left / "f.txt").write_text("x")
    refresh(win)
    texts = lambda m: [a.text().split("\t")[0] for a in m.actions() if not a.isSeparator()]       # noqa: E731
    assert "Find Duplicate Files in This Folder..." in texts(win.build_context_menu(win.left, win.left.model.row_of("folder")))
    assert "Find Duplicate Files in This Folder..." not in texts(win.build_context_menu(win.left, win.left.model.row_of("f.txt")))
    assert "Find Duplicate Files..." in texts(win.build_context_menu(win.left, -1))
