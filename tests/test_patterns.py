"""Marking by wildcard pattern (Ctrl+F)."""
import pytest

from dossier.core import patterns
from dossier.core.vfs import Entry


def e(name, is_dir=False):
    return Entry(name, "/x/" + name, is_dir)


def hits(text, entries, **kw):
    return [x.name for x in patterns.select(entries, patterns.parse(text, **kw))]


FILES = [e("a.jpg"), e("B.JPG"), e("c.png"), e("notes.txt"), e("report1.txt"), e("report22.txt"), e("debug.log"),
         e("run.log"), e("backup1", True), e("backup2", True), e("photos", True), e("a b.txt"), e("[x].txt")]


def test_star_and_question_mark_and_several_patterns():
    assert hits("*.jpg", FILES) == ["a.jpg", "B.JPG"]                    # case is ignored by default
    assert hits("*.jpg;*.png", FILES) == ["a.jpg", "B.JPG", "c.png"]
    assert hits("*.jpg, *.png", FILES) == ["a.jpg", "B.JPG", "c.png"]
    assert hits("report?.txt", FILES) == ["report1.txt"]
    assert hits("report*.txt", FILES) == ["report1.txt", "report22.txt"]
    assert hits("*.*", FILES) == ["a.jpg", "B.JPG", "c.png", "notes.txt", "report1.txt", "report22.txt", "debug.log",
                                  "run.log", "a b.txt", "[x].txt"]       # files only, not the folders


def test_case_sensitive_when_the_file_system_is():
    assert hits("*.jpg", FILES, case_sensitive=True) == ["a.jpg"]


def test_exclusions_remove_from_what_the_others_matched():
    assert hits("*.log !debug*", FILES) == ["run.log"]
    assert hits("*.txt !report* !notes*", FILES) == ["a b.txt", "[x].txt"]
    assert hits("!*.log", FILES) == []                                   # nothing to exclude from


def test_a_trailing_slash_means_folders_and_only_folders():
    assert hits("backup*/", FILES) == ["backup1", "backup2"]
    assert hits("*/", FILES) == ["backup1", "backup2", "photos"]
    assert hits("backup*", FILES) == []                                  # a plain pattern is for files
    assert hits("backup*\\", FILES) == ["backup1", "backup2"]
    assert hits("*.txt backup1/", FILES) == ["notes.txt", "report1.txt", "report22.txt", "backup1", "a b.txt", "[x].txt"]


def test_a_name_is_matched_whole_and_a_bare_word_is_not_a_search():
    assert hits("notes", FILES) == []
    assert hits("notes.txt", FILES) == ["notes.txt"]
    assert hits("*otes*", FILES) == ["notes.txt"]


def test_brackets_and_spaces_in_names():
    assert hits("[ab].*", FILES) == ["a.jpg", "B.JPG"]
    assert hits("a?b.txt", FILES) == ["a b.txt"]                         # a space in a name: use ?
    assert hits("[[]x].txt", FILES) == ["[x].txt"]


def test_an_unusable_text_is_explained():
    assert patterns.describe("") is not None
    assert patterns.describe("   ") is not None
    assert patterns.describe("!*.log") is not None
    assert patterns.describe("/") is not None
    assert patterns.describe("*.jpg") is None


# the window --------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402

from tests.test_gui_commander import app, key, world  # noqa: E402,F401

CTRL = Qt.KeyboardModifier.ControlModifier


def marked(win):
    return sorted(p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in win.selection.paths())


def fill(win, left):
    for n in ("a.jpg", "b.jpg", "c.png", "log.txt"):
        (left / n).write_text(n)
    (left / "pics").mkdir()
    win.left.refresh()


def test_ctrl_f_marks_the_matching_files_and_adds_to_earlier_marks(world):
    win, dialogs, left, *_ = world
    fill(win, left)
    dialogs.texts.append("*.jpg")
    key(win, Qt.Key.Key_F, CTRL)
    assert marked(win) == ["a.jpg", "b.jpg"] and "2 marked" in win.status.text()
    dialogs.texts.append("*.png")
    key(win, Qt.Key.Key_F, CTRL)
    assert marked(win) == ["a.jpg", "b.jpg", "c.png"]                    # added to what was marked
    assert win.settings.value("mark/pattern") == "*.png"                 # remembered for next time


def test_ctrl_shift_f_unmarks_and_folders_need_a_trailing_slash(world):
    win, dialogs, left, *_ = world
    fill(win, left)
    win.select_all()
    assert len(win.selection) == 5
    dialogs.texts.append("*.jpg")
    key(win, Qt.Key.Key_F, CTRL | Qt.KeyboardModifier.ShiftModifier)
    assert marked(win) == ["c.png", "log.txt", "pics"]
    dialogs.texts.append("pics/")
    key(win, Qt.Key.Key_F, CTRL | Qt.KeyboardModifier.ShiftModifier)
    assert marked(win) == ["c.png", "log.txt"]


def test_a_pattern_that_matches_nothing_says_so_and_a_bad_one_is_explained(world):
    win, dialogs, left, *_ = world
    fill(win, left)
    dialogs.texts.append("*.zip")
    key(win, Qt.Key.Key_F, CTRL)
    assert "Nothing matches" in win.status.text() and marked(win) == []
    dialogs.texts.append("!*.jpg")
    key(win, Qt.Key.Key_F, CTRL)
    assert dialogs.infos and "pattern" in dialogs.infos[-1][1]
    dialogs.texts.append("")                                             # cancelled: nothing changes
    key(win, Qt.Key.Key_F, CTRL)
    assert marked(win) == []


def test_the_dialog_starts_with_the_last_pattern(world):
    win, dialogs, left, *_ = world
    fill(win, left)
    asked = []
    original = dialogs.ask_text
    dialogs.ask_text = lambda title, label, default="": asked.append(default) or original(title, label, default)
    dialogs.texts.append("*.png")
    key(win, Qt.Key.Key_F, CTRL)
    dialogs.texts.append("*.jpg")
    key(win, Qt.Key.Key_F, CTRL)
    assert asked == ["*.*", "*.png"]
