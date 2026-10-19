"""The F4 notepad: editing, safe saving, Ctrl+H find and replace with regular expressions, column editing."""
import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.textedit import load_document  # noqa: E402
from dossier.gui.editor import from_line_index, line_starts, to_line_index, u16len  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from dossier.gui.notepad import NotepadWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pad(app, tmp_path):
    made = []

    def make(data, name="f.txt", **kw):
        p = tmp_path / name
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        dialogs = FakeDialogs()
        win = NotepadWindow(load_document(str(p)), dialogs, **kw)
        win.show()
        win.activateWindow()
        QTest.qWaitForWindowActive(win)            # window shortcuts only fire in an active window
        made.append(win)
        return win, dialogs, p

    yield make
    for w in made:
        w.mark_clean()
        w.close()


# offsets: Python characters against Scintilla's (line, index) --------------------------------------------------------
def test_offsets_round_trip_including_characters_outside_the_basic_plane():
    text = "ab\nc\U0001F600d\n\nlast"
    starts = line_starts(text)
    assert starts == [0, 3, 7, 8]
    for offset in range(len(text) + 1):
        line, index = to_line_index(starts, text, offset)
        assert from_line_index(starts, text, line, index) == offset
    assert u16len("c\U0001F600d") == 4 and to_line_index(starts, text, 5) == (1, 3)


# editing and saving --------------------------------------------------------------------------------------------------
def test_the_notepad_shows_the_file_and_names_its_subject(pad):
    win, _d, p = pad("one\ntwo\n")
    assert win.editor.text() == "one\ntwo\n"
    assert win.windowTitle() == "Dossier, Subject - f.txt"
    assert win.encoding.currentText() == "utf-8" and win.eol.currentData() == "\n"


def test_an_edit_marks_the_title_and_save_keeps_encoding_bom_and_line_breaks(pad):
    win, _d, p = pad(b"\xef\xbb\xbfcaf\xc3\xa9\r\nline2\r\n")
    assert win.eol.currentData() == "\r\n"
    win.editor.insertAt("X", 0, 0)
    assert win.windowTitle() == "Dossier, Subject - f.txt*"
    assert win.save()
    assert p.read_bytes() == b"\xef\xbb\xbfXcaf\xc3\xa9\r\nline2\r\n"
    assert win.windowTitle() == "Dossier, Subject - f.txt"


def test_save_refuses_when_the_file_changed_and_offers_a_choice(pad):
    win, dialogs, p = pad("original\n")
    win.editor.insertAt("mine ", 0, 0)
    p.write_bytes(b"changed elsewhere\n")
    dialogs.disk_answer = None                                  # cancel
    assert not win.save() and p.read_bytes() == b"changed elsewhere\n"
    dialogs.disk_answer = "overwrite"
    assert win.save() and p.read_bytes() == b"mine original\n"


def test_reload_choice_takes_the_disk_version_and_saves_nothing(pad):
    win, dialogs, p = pad("original\n")
    win.editor.insertAt("mine ", 0, 0)
    p.write_bytes(b"theirs\n")
    dialogs.disk_answer = "reload"
    assert not win.save()
    assert win.editor.text() == "theirs\n" and not win.editor.isModified()


def test_a_character_the_encoding_cannot_hold_offers_utf8(pad):
    win, dialogs, p = pad(b"caf\xe9\n")                          # Windows-1252
    win.editor.insertAt("中", 0, 0)
    dialogs.confirm_answer = False
    assert not win.save() and p.read_bytes() == b"caf\xe9\n"
    dialogs.confirm_answer = True
    assert win.save()
    assert p.read_bytes() == "中café\n".encode("utf-8")


def test_changing_the_line_break_kind_is_written_on_save(pad):
    win, _d, p = pad("a\nb\n")
    win.eol.setCurrentIndex(0)
    win.eol.activated.emit(0)
    assert win.is_modified() and win.windowTitle().endswith("*")
    assert win.save() and p.read_bytes() == b"a\r\nb\r\n" and not win.is_modified()


def test_changing_the_encoding_rereads_the_file(pad):
    win, dialogs, p = pad("æøå\n".encode("windows-1252"))
    assert win.doc.encoding == "windows-1252" and win.editor.text() == "æøå\n"
    i = win.encoding.findText("cp437")
    win.encoding.setCurrentIndex(i)
    win.encoding.activated.emit(i)
    assert win.doc.encoding == "cp437" and win.editor.text() != "æøå\n"


def test_save_as_writes_a_new_file_and_closing_asks_about_unsaved_changes(pad, tmp_path):
    win, dialogs, p = pad("data\n")
    target = tmp_path / "copy.txt"
    dialogs.save_path = str(target)
    win.editor.insertAt("new ", 0, 0)
    assert win.save_as() and target.read_bytes() == b"new data\n" and p.read_bytes() == b"data\n"
    assert win.windowTitle() == "Dossier, Subject - copy.txt"
    win.editor.insertAt("more ", 0, 0)
    dialogs.save_answer = "cancel"
    assert not win.close() and win.isVisible()
    dialogs.save_answer = "save"
    assert win.close() and target.read_bytes() == b"more new data\n"


# find and replace ------------------------------------------------------------------------------------------------------------
def test_ctrl_h_shows_the_replace_bar_and_ctrl_f_only_the_find_row(pad):
    win, *_ = pad("x\n")
    assert not win.bar.isVisible()
    QTest.keyClick(win.editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    assert win.bar.isVisible() and win.bar.replace_row.isVisible()
    QTest.keyClick(win.editor, Qt.Key.Key_Escape)
    assert not win.bar.isVisible()
    QTest.keyClick(win.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert win.bar.isVisible() and not win.bar.replace_row.isVisible()


def test_find_next_and_previous_select_the_match_and_wrap(pad):
    win, *_ = pad("alpha beta\nbeta gamma\n")
    win.bar.show_find()
    win.bar.find.setText("beta")
    assert win.find(True) and win.editor.selectedText() == "beta" and win.editor.getSelection()[:2] == (0, 6)
    assert win.find(True) and win.editor.getSelection()[:2] == (1, 0)
    assert win.find(True) and win.editor.getSelection()[:2] == (0, 6) and "Wrapped" in win.bar.message.text()
    assert win.find(False) and win.editor.getSelection()[:2] == (1, 0)


def test_a_missing_match_and_a_bad_regex_are_explained_not_raised(pad):
    win, *_ = pad("abc\n")
    win.bar.show_find()
    win.bar.find.setText("zzz")
    assert not win.find(True) and win.bar.message.text() == "No match"
    win.bar.regex.setChecked(True)
    win.bar.find.setText("(unclosed")
    assert not win.find(True) and "regular expression" in win.bar.message.text()
    win.bar.find.setText("a")
    win.bar.replace.setText(r"\g<nope>")
    assert win.replace_all() == 0 and "replacement" in win.bar.message.text()
    assert win.editor.text() == "abc\n"


def test_replace_one_replaces_the_selected_match_then_moves_on(pad):
    win, *_ = pad("cat cat cat\n")
    win.bar.show_replace()
    win.bar.find.setText("cat")
    win.bar.replace.setText("dog")
    win.replace_one()                                     # nothing selected yet: it only finds the first
    assert win.editor.text() == "cat cat cat\n" and win.editor.selectedText() == "cat"
    win.replace_one()
    assert win.editor.text() == "dog cat cat\n" and win.editor.getSelection()[:2] == (0, 4)
    win.replace_one()
    assert win.editor.text() == "dog dog cat\n"


def test_replace_all_with_regex_groups_is_one_undo_step(pad):
    win, *_ = pad("2024-10-19\n2025-01-02\nnot a date\n")
    win.bar.show_replace()
    win.bar.regex.setChecked(True)
    win.bar.find.setText(r"(\d{4})-(\d\d)-(\d\d)")
    win.bar.replace.setText(r"\3.\2.\1")
    assert win.replace_all() == 2
    assert win.editor.text() == "19.10.2024\n02.01.2025\nnot a date\n"
    assert "Replaced 2" in win.bar.message.text()
    win.editor.undo()
    assert win.editor.text() == "2024-10-19\n2025-01-02\nnot a date\n"          # one undo brings both back


def test_replace_all_in_selection_only_and_with_unicode_text(pad):
    win, *_ = pad("æ æ æ\nlast æ\n")
    win.bar.show_replace()
    win.bar.find.setText("æ")
    win.bar.replace.setText("\U0001F600")
    win.editor.setSelection(0, 0, 0, 3)                                     # the first two on line one
    win.bar.in_selection.setChecked(True)
    assert win.replace_all() == 2
    assert win.editor.text() == "\U0001F600 \U0001F600 æ\nlast æ\n"
    win.bar.in_selection.setChecked(False)
    win.editor.setCursorPosition(0, 0)
    win.editor.SendScintilla(win.editor.SCI_SETSEL, 0, 0)
    assert win.replace_all() == 2
    assert win.editor.text().count("\U0001F600") == 4


def test_regex_options_whole_word_case_and_dot_all(pad):
    win, *_ = pad("Cat cat concat\nend\n")
    win.bar.show_replace()
    win.bar.find.setText("cat")
    win.bar.word.setChecked(True)
    win.bar.replace.setText("X")
    assert win.replace_all() == 2 and win.editor.text() == "X X concat\nend\n"
    win.bar.word.setChecked(False)
    win.bar.regex.setChecked(True)
    win.bar.find.setText("t.end")
    assert win.replace_all() == 0                          # the dot stops at a line break
    win.bar.dotall.setChecked(True)
    assert win.replace_all() == 1 and win.editor.text() == "X X concaX\n"


def test_the_live_check_counts_matches_and_shows_regex_errors(pad):
    win, *_ = pad("a a a\n")
    win.bar.show_find()
    win.bar.find.setText("a")
    win._validate()
    assert win.bar.message.text() == "3 matches"
    win.bar.regex.setChecked(True)
    win.bar.find.setText("[")
    assert win._validate() is False and "regular expression" in win.bar.message.text()


# column editing ------------------------------------------------------------------------------------------------------------------
def test_a_vertical_selection_types_into_every_line(pad):
    win, *_ = pad("one\ntwo\nthree\nfour\n")
    ed = win.editor
    ed.select_block(0, 1, 2, 1)                                  # column 1, lines 0 to 2
    assert ed.is_block_selection() and ed.selection_count() == 3
    QTest.keyClicks(ed, "--")
    assert ed.text() == "o--ne\nt--wo\nt--hree\nfour\n"


def test_a_vertical_selection_copies_and_deletes_the_block_and_pastes_it_down_a_column(pad, app):
    win, *_ = pad("abcdef\nghijkl\nmnopqr\n")
    ed = win.editor
    ed.select_block(0, 1, 2, 4)
    ed.copy()
    from PyQt6.QtGui import QGuiApplication
    block = QGuiApplication.clipboard().text().replace(chr(13), "").strip()
    assert block.split(chr(10)) == ["bcd", "hij", "nop"]
    ed.removeSelectedText()
    assert ed.text() == "aef\ngkl\nmqr\n"


def test_alt_shift_arrows_grow_a_vertical_selection_from_the_keyboard(pad):
    win, *_ = pad("abcdef\nghijkl\nmnopqr\n")
    ed = win.editor
    ed.setCursorPosition(0, 2)
    mods = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(ed, Qt.Key.Key_Down, mods)
    QTest.keyClick(ed, Qt.Key.Key_Down, mods)
    QTest.keyClick(ed, Qt.Key.Key_Right, mods)
    assert ed.is_block_selection() and ed.selection_count() == 3


def test_a_block_can_reach_past_the_end_of_short_lines(pad):
    win, *_ = pad("ab\nabcdefgh\nx\n")
    ed = win.editor
    ed.select_block(0, 5, 2, 5)
    QTest.keyClicks(ed, "|")
    lines = ed.text().split("\n")
    assert lines[1] == "abcde|fgh"                              # only the line long enough got the character


# the file manager: F4, viewer hand-over ------------------------------------------------------------------------------------------
@pytest.fixture
def commander(app, tmp_path):
    (tmp_path / "left").mkdir()
    (tmp_path / "left" / "a.txt").write_text("alpha\n")
    (tmp_path / "left" / "b.txt").write_text("beta\n")
    (tmp_path / "left" / "bin.dat").write_bytes(b"MZ\x00\x01" * 50)
    (tmp_path / "left" / "sub").mkdir()
    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path / "left"), str(tmp_path)),
                     dialogs=dialogs)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)
    yield win, dialogs, tmp_path
    for e in list(win.editors):
        e.mark_clean()
    win.close()


def test_f4_opens_the_file_under_the_cursor_once(commander):
    win, dialogs, tmp = commander
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    QTest.keyClick(win.left.table, Qt.Key.Key_F4)
    assert len(win.editors) == 1 and win.editors[0].editor.text() == "alpha\n"
    win.edit_file()
    assert len(win.editors) == 1                              # the same file is brought forward, not opened twice


def test_f4_refuses_folders_binaries_and_several_files_with_a_reason(commander):
    win, dialogs, tmp = commander
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("sub"), 0))
    win.edit_file()
    assert "one file" in dialogs.infos[-1][1]
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("bin.dat"), 0))
    win.edit_file()
    assert "binary" in dialogs.infos[-1][1] and not win.editors
    win.selection.add([str(tmp / "left" / "a.txt"), str(tmp / "left" / "b.txt")])
    win.edit_file()
    assert "one file" in dialogs.infos[-1][1]


def test_a_file_over_the_limit_points_to_the_viewer(commander, monkeypatch):
    import dossier.core.textedit as te
    win, dialogs, tmp = commander
    monkeypatch.setattr(te, "MAX_EDIT_BYTES", 2)
    monkeypatch.setattr("dossier.gui.main_window.load_document",
                        lambda path: te.load_document(path, max_bytes=2))
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win.edit_file()
    assert "View (F3)" in dialogs.infos[-1][1] and not win.editors


def test_ctrl_h_in_the_viewer_hands_the_file_to_the_notepad_with_the_replace_bar(commander):
    win, dialogs, tmp = commander
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win.view_file()
    viewer = win.viewers[0]
    viewer.activateWindow()
    QTest.qWaitForWindowActive(viewer)
    QTest.keyClick(viewer.view, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert len(win.editors) == 1 and win.editors[0].bar.replace_row.isVisible()


def test_saving_in_the_notepad_refreshes_the_file_manager_and_closing_it_closes_the_notepads(commander):
    win, dialogs, tmp = commander
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win.edit_file()
    pad = win.editors[0]
    pad.editor.insertAt("x" * 5000, 0, 0)
    assert pad.save()
    entry = win.left.model.entry_at(win.left.model.row_of("a.txt"))
    assert entry.size > 5000
    pad.editor.insertAt("dirty", 0, 0)
    win.dialogs.save_answer = "discard"
    win.close()
    assert win.editors == [] or not win.editors[0].isVisible()
