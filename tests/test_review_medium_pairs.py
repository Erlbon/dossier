"""The functionality review of 2026-11-05, cards 2 + 3 (an editor program for F4, Open With) and 6 + 15 (mark by size, date and
attributes; search skips folders), each sharing its code with the other of the pair."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

from dossier.core import search as S, tools  # noqa: E402
from dossier.core.vfs import Entry, LocalFileSystem  # noqa: E402


def listed(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def cursor_on(panel, name):
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


# 2 -----------------------------------------------------------------------------------------------------------------------------
def test_f4_opens_the_chosen_editor_program(world):
    win, dialogs, left, *_ = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    dialogs.program_answer = r"C:\Tools\code.exe"
    win.act_editor_program.trigger()
    assert win.editor_program() == r"C:\Tools\code.exe" and "code.exe" in win.act_editor_program.text()
    cursor_on(win.left, "a.txt")
    win.edit_file()
    pump(win, lambda: started)
    assert started == [(r"C:\Tools\code.exe", [str(left / "a.txt")])] and not win.editors
    win.act_editor_notepad.trigger()
    assert win.editor_program() == ""


def test_cancelling_the_program_choice_keeps_the_notepad(world):
    win, dialogs, *_ = world
    dialogs.program_answer = None
    win.act_editor_program.trigger()
    assert win.editor_program() == "" and win.act_editor_notepad.isChecked()


# 3 -----------------------------------------------------------------------------------------------------------------------------
def test_open_with_offers_the_tools_bars_programs_and_runs_them_on_the_clicked_items(world):
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    listed(win, win.left, 3)
    win.set_tools([tools.Tool("Notepad++", r"C:\npp.exe", "{files}"),
                   tools.Folder("Images", [tools.Tool("GIMP", r"C:\gimp.exe", "{file}")])])
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    menu = win.build_context_menu(win.left, win.left.model.row_of("b.txt"))
    open_with = next(a.menu() for a in menu.actions() if a.text() == "Open With")
    texts = [a.text() for a in open_with.actions() if not a.isSeparator()]
    assert texts[:2] == ["Notepad++", "Images"]
    assert ("Choose Another Program..." in texts) == (os.name == "nt")
    next(a for a in open_with.actions() if a.text() == "Notepad++").trigger()
    assert started == [(r"C:\npp.exe", [str(left / "b.txt")])]


def test_no_open_with_when_there_is_nothing_to_offer(world, monkeypatch):
    from dossier.gui import context_menu
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    win.set_tools([])
    monkeypatch.setattr(context_menu, "open_with_command", lambda path: None)
    menu = win.build_context_menu(win.left, win.left.model.row_of("a.txt"))
    assert "Open With" not in [a.text() for a in menu.actions()]


# 6 -----------------------------------------------------------------------------------------------------------------------------
def test_fits_tests_size_date_and_attributes():
    now = time.time()
    big = Entry("big.iso", "x/big.iso", False, size=2 << 30, mtime=now, attrs=0x20)
    old = Entry("old.txt", "x/old.txt", False, size=10, mtime=now - 400 * 86400, attrs=0x2 | 0x1)
    assert S.fits(big, S.Criteria(root="", min_size=1 << 30)) and not S.fits(old, S.Criteria(root="", min_size=1 << 30))
    assert S.fits(old, S.Criteria(root="", older_than=now - 86400)) and not S.fits(big, S.Criteria(root="", older_than=now - 86400))
    if os.name == "nt":
        assert S.fits(old, S.Criteria(root="", attributes="HR")) and not S.fits(big, S.Criteria(root="", attributes="H"))
    with pytest.raises(S.BadCriteria):
        S.validate(S.Criteria(root="", attributes="X"))


def test_mark_by_pattern_can_mark_by_size(world):
    win, dialogs, left, *_ = world
    (left / "small.bin").write_bytes(b"x" * 10)
    (left / "large.bin").write_bytes(b"x" * 50_000)
    listed(win, win.left, 3)
    dialogs.mark_answer = ("*.bin", S.Criteria(root="", min_size=10_000))
    win.mark_by_pattern()
    assert str(left / "large.bin") in win.selection and str(left / "small.bin") not in win.selection


def test_an_empty_pattern_marks_every_name_that_passes_the_other_tests(world):
    win, dialogs, left, *_ = world
    (left / "a.txt").write_bytes(b"x" * 50_000)
    (left / "b.log").write_bytes(b"x" * 50_000)
    (left / "c.log").write_bytes(b"x")
    listed(win, win.left, 4)
    dialogs.mark_answer = ("", S.Criteria(root="", min_size=10_000))
    win.mark_by_pattern()
    assert {p for p in (str(left / n) for n in ("a.txt", "b.log", "c.log")) if p in win.selection} == {str(left / "a.txt"),
                                                                                                   str(left / "b.log")}


# 15 ----------------------------------------------------------------------------------------------------------------------------
def test_search_skips_the_named_folders(tmp_path):
    for folder in ("src", "node_modules/pkg", ".git/objects", "build-1", "rebuild"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "index.js").write_text("x")
    c = S.Criteria(root=str(tmp_path), name="index.js", skip_folders="node_modules;.git;build*")
    found = sorted(os.path.dirname(e.name) for e in S.search(LocalFileSystem(), c).entries)
    assert found == ["rebuild", "src"]                      # "build*" is a pattern; a plain name must be the whole name


def test_the_search_dialog_keeps_the_skip_list(world):
    from dossier.gui.search_dialog import SearchDialog
    win, *_ = world
    dlg = SearchDialog(win, "C:/x", S.Criteria(root="C:/x", skip_folders=".git", attributes="H"))
    c = dlg.criteria()
    assert c.skip_folders == ".git" and c.attributes == "H"
    dlg.close()


def test_dossier_find_has_skip(tmp_path, capsys):
    from dossier.cli import main
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    assert main(["find", str(tmp_path), "--name", "*.txt", "--skip", "node_modules"]) == 0
    out = capsys.readouterr().out
    assert "b.txt" in out and "node_modules" not in out
