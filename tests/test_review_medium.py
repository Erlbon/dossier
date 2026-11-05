"""The functionality review of 2026-11-05, medium cards: 4 (unpack and convert many), 5 (tag placeholders), 7 (text diff),
9 (nested folders), 11 (hidden files), 13 (tab menu, reopen closed tab), 14 (Ctrl+F3..F6 sort), 16 (command palette)."""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

from dossier.core import textdiff  # noqa: E402
from dossier.core.vfs import Entry  # noqa: E402


def listed(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def cursor_on(panel, name):
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


# 4 -----------------------------------------------------------------------------------------------------------------------------
def test_unpack_many_puts_each_archive_in_its_own_folder_and_never_twice(world):
    win, dialogs, left, *_ = world
    make_zip(left / "a.zip", {"x.txt": "x"})
    make_zip(left / "b.zip", {"b/y.txt": "y"})                  # already one folder named like the archive: no b/b
    listed(win, win.left, 3)
    win.selection.add([str(left / "a.zip"), str(left / "b.zip")])
    win.unpack_archive()
    pump(win, lambda: (left / "a" / "x.txt").exists() and (left / "b" / "y.txt").exists(), timeout=10)
    assert not (left / "b" / "b").exists()


def test_unpack_many_all_into_this_folder(world):
    win, dialogs, left, *_ = world
    make_zip(left / "a.zip", {"x.txt": "x"})
    make_zip(left / "b.zip", {"y.txt": "y"})
    listed(win, win.left, 3)
    win.selection.add([str(left / "a.zip"), str(left / "b.zip")])
    dialogs.unpack_answer = "here"
    win.unpack_archive()
    pump(win, lambda: (left / "x.txt").exists() and (left / "y.txt").exists(), timeout=10)


def test_convert_leaves_out_what_it_cannot_convert_and_says_so(world):
    win, dialogs, left, *_ = world
    make_zip(left / "a.zip", {"x.txt": "x"})
    (left / "b.txt").write_text("b")
    listed(win, win.left, 3)
    win.selection.add([str(left / "a.zip"), str(left / "b.txt")])
    win.convert_archive_to_zip()
    pump(win, lambda: dialogs.infos)
    assert "Left out" in dialogs.infos[-1][1] and "a.zip" in dialogs.infos[-1][1]


# 5 -----------------------------------------------------------------------------------------------------------------------------
def test_batch_rename_reads_the_tags_first(world, monkeypatch):
    from dossier.gui import batch_rename
    win, _d, left, *_ = world
    (left / "song.mp3").write_bytes(b"ID3")
    (left / "note.txt").write_text("x")
    listed(win, win.left, 3)
    win.selection.add([str(left / "song.mp3"), str(left / "note.txt")])
    monkeypatch.setattr(batch_rename, "tag_values", lambda path: {"artist": "Low", "title": "Words"})
    seen = []
    monkeypatch.setattr(win, "_rename_by_pattern_with", lambda entries, tags: seen.append(tags))
    win.rename_by_pattern()
    pump(win, lambda: seen)
    assert seen == [{str(left / "song.mp3"): {"artist": "Low", "title": "Words"}}]
    assert ("artist", "Artist (music tags)") in batch_rename.PLACEHOLDERS


def test_tag_values_never_make_a_folder(monkeypatch):
    from dossier.core import metacolumns
    from dossier.gui import batch_rename
    monkeypatch.setattr(metacolumns, "read_values", lambda path, kinds: {"m_artist": "AC/DC", "m_track": "3"})
    v = batch_rename.tag_values("x.mp3")
    assert v["artist"] == "AC-DC" and v["track"] == "3" and v["taken"] == ""


# 7 -----------------------------------------------------------------------------------------------------------------------------
def test_side_by_side_pairs_changed_lines_and_marks_one_sided_ones():
    rows = textdiff.side_by_side(["a", "b", "c", "d"], ["a", "B", "c", "e", "f"])
    kinds = [(r.kind, r.left, r.right) for r in rows]
    assert kinds == [("same", "a", "a"), ("changed", "b", "B"), ("same", "c", "c"), ("changed", "d", "e"), ("right", "", "f")]
    assert textdiff.summary(rows) == "2 lines changed, 0 only on the left, 1 only on the right."


def test_compare_two_text_files_shows_them_side_by_side(world):
    win, dialogs, left, right, _t = world
    (left / "a.ini").write_text("x=1\ny=2\n")
    (right / "a.ini").write_text("x=1\ny=3\n")
    listed(win, win.left, 2)
    listed(win, win.right, 2)
    cursor_on(win.left, "a.ini")
    cursor_on(win.right, "a.ini")
    win.compare_files()
    pump(win, lambda: getattr(dialogs, "diffs", None))
    header, rows = dialogs.diffs[0]
    assert "1 line changed" in header and [r.kind for r in rows] == ["same", "changed"]


def test_binary_files_keep_the_byte_answer(world):
    win, dialogs, left, right, _t = world
    (left / "a.bin").write_bytes(b"\x00\x01\x02")
    (right / "a.bin").write_bytes(b"\x00\x01\x03")
    listed(win, win.left, 2)
    listed(win, win.right, 2)
    cursor_on(win.left, "a.bin")
    cursor_on(win.right, "a.bin")
    win.compare_files()
    pump(win, lambda: dialogs.infos)
    assert "first difference is at byte 2" in dialogs.infos[-1][1]


def test_the_diff_window_jumps_to_the_differences(world):
    from dossier.gui.text_diff import TextDiffWindow
    win, *_ = world
    rows = textdiff.side_by_side(["a", "b", "c", "d", "e"], ["a", "X", "c", "d", "Y"])
    w = TextDiffWindow(win, "t", "h", rows)
    try:
        assert w.table.currentRow() == 1
        assert w.next_difference() == 4
        assert w.next_difference() == 1
    finally:
        w.close()


# 9 -----------------------------------------------------------------------------------------------------------------------------
def test_f7_makes_nested_folders_and_one_undo_takes_them_away(world):
    win, dialogs, left, *_ = world
    (left / "a").mkdir()                                         # a is there: only b and c are made
    listed(win, win.left, 2)
    dialogs.texts = ["a" + os.sep + "b/c"]
    win.new_folder()
    pump(win, lambda: win.undo_log._actions or dialogs.infos)
    assert not dialogs.infos, dialogs.infos
    assert (left / "a" / "b" / "c").is_dir()
    assert [s.a for s in win.undo_log._actions[-1].steps] == [str(left / "a" / "b"), str(left / "a" / "b" / "c")]
    win.undo()
    pump(win, lambda: not (left / "a" / "b").exists() or dialogs.infos)
    assert not dialogs.infos, dialogs.infos
    assert (left / "a").is_dir()


def test_f7_refuses_a_bad_part(world):
    win, dialogs, left, *_ = world
    listed(win, win.left, 1)
    dialogs.texts = ["ok/bad|name" if os.name == "nt" else "ok/.."]
    win.new_folder()
    assert dialogs.infos and not (left / "ok").exists()


# 11 ----------------------------------------------------------------------------------------------------------------------------
def test_hidden_files_can_be_left_out(world):
    win, _d, left, *_ = world
    (left / "seen.txt").write_text("x")
    hidden = left / (".hidden" if os.name != "nt" else "hidden.txt")
    hidden.write_text("x")
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)
    listed(win, win.left, 3)
    names = lambda: [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]  # noqa: E731
    assert hidden.name in names()
    win.act_show_hidden.setChecked(False)
    assert hidden.name not in names() and "seen.txt" in names()
    assert win.left.counts.text().endswith("(1 of 2 shown)")
    win.act_show_hidden.setChecked(True)
    assert hidden.name in names()


# 13 ----------------------------------------------------------------------------------------------------------------------------
def test_a_closed_tab_can_be_reopened(world):
    win, _d, left, *_ = world
    (left / "sub").mkdir()
    win.left.new_tab(str(left / "sub"))
    pump(win, lambda: win.left.path == str(left / "sub"))
    win.left.close_tab(win.left.tabs.currentIndex())
    assert win.left.tabs.count() == 1
    win.reopen_closed_tab()
    pump(win, lambda: win.left.path == str(left / "sub"))
    assert win.left.tabs.count() == 2 and not win.left.closed_tabs


def test_the_tab_menu_closes_others_and_locks(world):
    win, _d, left, *_ = world
    (left / "sub").mkdir()
    listed(win, win.left, 2)
    win.left.new_tab(str(left))
    win.left.new_tab(str(left))
    menu = win.build_tab_menu(win.left, 0)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Duplicate Tab", "Open in the Other Panel", "Lock Tab", "Close Tab", "Close Other Tabs",
                     "Close Tabs to the Right", "Reopen Closed Tab"]
    next(a for a in menu.actions() if a.text() == "Close Other Tabs").trigger()
    assert win.left.tabs.count() == 1 and len(win.left.closed_tabs) == 2
    win.left.set_tab_locked(0, True)
    pump(win, lambda: win.left.path == str(left))
    listed(win, win.left, 2)
    cursor_on(win.left, "sub")
    win.left.open_current()                                      # a locked tab keeps its folder
    pump(win, lambda: win.left.tabs.count() == 2)
    assert win.left.tab_path(0) == str(left)


# 14 ----------------------------------------------------------------------------------------------------------------------------
def test_ctrl_f6_sorts_by_size_and_again_reverses(world):
    win, _d, left, *_ = world
    (left / "big.txt").write_bytes(b"x" * 5000)
    (left / "small.txt").write_bytes(b"x")
    listed(win, win.left, 3)
    win.active.table.setFocus()
    key(win, Qt.Key.Key_F6, Qt.KeyboardModifier.ControlModifier)
    files = lambda: [win.left.model.entry_at(r).name for r in range(1, win.left.model.entry_count())]  # noqa: E731
    assert files() == ["small.txt", "big.txt"]
    key(win, Qt.Key.Key_F6, Qt.KeyboardModifier.ControlModifier)
    assert files() == ["big.txt", "small.txt"]


# 16 ----------------------------------------------------------------------------------------------------------------------------
def test_ctrl_k_opens_the_command_palette_with_the_menus_commands(world, monkeypatch):
    win, *_ = world
    assert win.act_palette.shortcut().toString() == "Ctrl+K" and win.act_palette.text() == "Command Palette..."
    win.command_palette.refresh()
    win.command_palette.set_filter("root drive")
    assert [c.title for c in win.command_palette.visible_commands()][:1] == ["Root of the Drive"]
