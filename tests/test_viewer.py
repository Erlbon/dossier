"""The F3 text viewer and its line view, driven offscreen."""
import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from tests.helpers import activate_window  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui.line_view import col_of_vcol, vcol_of  # noqa: E402
from dossier.gui.viewer import TextViewerWindow  # noqa: E402
from dossier.gui.qt_bridge import QtDispatcher  # noqa: E402
from tests.test_gui_commander import FakeDialogs, key  # noqa: E402,F401
from dossier.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(win, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if not win.busy:
            return
        time.sleep(0.005)
    raise AssertionError("viewer stayed busy")


@pytest.fixture
def viewer(app, tmp_path):
    made = []

    def make(files: dict, index=0):
        paths = []
        for name, data in files.items():
            p = tmp_path / name
            p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
            paths.append(str(p))
        win = TextViewerWindow(paths, index)
        win.show()
        settle(win)
        made.append(win)
        return win

    yield make
    for w in made:
        w.close()


def lines(n):
    return "".join(f"line {i}\n" for i in range(n))


# helpers -------------------------------------------------------------------------------------
def test_visual_columns_expand_tabs():
    assert vcol_of("a\tb", 2) == 8 and vcol_of("abc", 2) == 2
    assert col_of_vcol("a\tb", 8) == 2 and col_of_vcol("a\tb", 3) == 1 and col_of_vcol("ab", 9) == 2


# viewing -----------------------------------------------------------------------------------------
def test_the_viewer_shows_the_file_and_its_line_count(viewer):
    win = viewer({"a.txt": lines(500)})
    assert win.source.line_count == 500 and win.view.total == 500
    assert "Line 1 of 500" in win.position.text()
    assert "utf-8" in win.status.text()
    assert win.windowTitle() == "Dossier, Subject - a.txt"


def test_scrolling_and_goto(viewer):
    win = viewer({"a.txt": lines(1000)})
    win.goto_line_number(500)
    assert win.view.top <= 499 < win.view.top + win.view.visible_lines
    key = win.view.verticalScrollBar()
    key.setValue(0)
    QTest.keyClick(win.view, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert win.view.at_end()
    QTest.keyClick(win.view, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    assert win.view.top == 0


def test_a_missing_file_says_so_instead_of_crashing(app, tmp_path):
    win = TextViewerWindow([str(tmp_path / "gone.txt")])
    try:
        assert win.source is None and "Cannot open" in win.status.text()
    finally:
        win.close()


def test_an_empty_file_is_fine(viewer):
    win = viewer({"e.txt": b""})
    assert win.view.total == 0 and "Line 1 of 1" not in win.position.text()


def test_binary_files_are_flagged(viewer):
    win = viewer({"b.bin": b"MZ\x00\x01\x02" * 100})
    assert "binary" in win.status.text()


# find ---------------------------------------------------------------------------------------------
def test_find_next_previous_and_wrap_around(viewer):
    win = viewer({"a.txt": "alpha\nneedle one\nmid\nNeedle two\nend\n"})
    win.find_edit.setText("needle")
    win.find(forward=True)
    settle(win)
    assert win.view.match == (1, 0, 6)
    win.find(forward=True)
    settle(win)
    assert win.view.match == (3, 0, 6)
    win.find(forward=True)
    settle(win)
    assert win.view.match == (1, 0, 6) and "wrapping" in win.status.text()
    win.find(forward=False)
    settle(win)
    assert win.view.match == (3, 0, 6)


def test_match_case_and_not_found(viewer):
    win = viewer({"a.txt": "Needle\nneedle\n"})
    win.find_edit.setText("needle")
    win.case.setChecked(True)
    win.find(forward=True)
    settle(win)
    assert win.view.match == (1, 0, 6)
    win.find_edit.setText("absent")
    win.find(forward=True)
    settle(win)
    assert "Not found" in win.status.text() and win.view.match is None


def test_found_text_is_scrolled_into_view(viewer):
    win = viewer({"a.txt": lines(2000) + "THE TARGET\n"})
    win.find_edit.setText("the target")
    win.find(forward=True)
    settle(win)
    line = win.view.match[0]
    assert line == 2000 and win.view.top <= line < win.view.top + win.view.visible_lines


# encodings and files -----------------------------------------------------------------------------------
def test_changing_the_encoding_redecodes(viewer):
    win = viewer({"a.txt": "æøå\n".encode("windows-1252")})
    assert win.source.line(0) == "æøå"
    win.encoding.setCurrentText("cp437")
    settle(win)
    assert win.source.line(0) != "æøå" and win.source.encoding == "cp437"
    win.encoding.setCurrentText("Auto")
    settle(win)
    assert win.source.line(0) == "æøå"


def test_stepping_through_several_files(viewer):
    win = viewer({"a.txt": "first\n", "b.txt": "second\n", "c.txt": "third\n"})
    assert win.file_buttons_visible and win.source.line(0) == "first"
    win.step(1)
    settle(win)
    assert win.source.line(0) == "second" and "2 of 3" in win.windowTitle()
    win.step(-1)
    win.step(-1)
    settle(win)
    assert win.source.line(0) == "third"       # wraps round


def test_a_single_file_has_no_file_buttons(viewer):
    assert not viewer({"a.txt": "x\n"}).file_buttons_visible


# follow --------------------------------------------------------------------------------------------------
def test_follow_picks_up_new_lines_and_keeps_the_end_in_view(viewer):
    win = viewer({"log.txt": lines(200)})
    win.follow.setChecked(True)
    with open(win.source.path, "ab") as f:
        f.write(b"".join(b"more %d\n" % i for i in range(300)))
    win._poll()
    assert win.source.line_count == 500 and win.view.at_end()
    win.follow.setChecked(False)


def test_the_viewer_does_not_stop_another_program_truncating_the_file(viewer):
    win = viewer({"log.txt": lines(50)})
    with open(win.source.path, "wb") as f:      # a logger rotating its file by truncating it
        f.write(b"fresh\n")
    win._poll()
    assert win.source.line_count == 1 and win.source.line(0) == "fresh"


# selection and copy -----------------------------------------------------------------------------------------
def cell_pos(win, line, col):
    v = win.view
    return QPoint(v.gutter() + col * v.cw + 1, (line - v.top) * v.lh + 2)


def test_normal_selection_copies_text(viewer, app):
    win = viewer({"a.txt": "hello world\nsecond line\nthird\n"})
    v = win.view
    QTest.mousePress(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cell_pos(win, 0, 6))
    QTest.mouseMove(v.viewport(), cell_pos(win, 1, 6))
    v.head = (1, 6)
    v.copy()
    assert QGuiApplication.clipboard().text() == "world\nsecond"


def test_vertical_selection_by_alt_drag_copies_a_block(viewer, app):
    win = viewer({"a.txt": "abcdef\nghijkl\nmnopqr\n"})
    v = win.view
    QTest.mousePress(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, cell_pos(win, 0, 2))
    assert v.block
    v.head = (2, 4)
    v.copy()
    assert QGuiApplication.clipboard().text() == "cd\nij\nop"


def test_vertical_selection_by_alt_shift_arrows(viewer, app):
    win = viewer({"a.txt": "abcdef\nghijkl\nmnopqr\n"})
    v = win.view
    v.anchor = v.head = (0, 1)
    mods = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(v, Qt.Key.Key_Down, mods)
    QTest.keyClick(v, Qt.Key.Key_Down, mods)
    QTest.keyClick(v, Qt.Key.Key_Right, mods)
    QTest.keyClick(v, Qt.Key.Key_Right, mods)
    assert v.block and v.head == (2, 3)
    assert v.selected_text() == "bc\nhi\nno"


def test_a_block_over_short_lines_and_tabs_stays_aligned(viewer, app):
    win = viewer({"a.txt": "ab\nabcdefgh\nx\tyz\n"})
    v = win.view
    v.block = True
    v.anchor, v.head = (0, 2), (1, 5)
    assert v.selected_text() == "\ncde"           # line 0 ends before the block: nothing from it, no padding
    v.anchor, v.head = (1, 2), (2, 3)
    assert v.selected_text() == "cdefgh\n\ty"    # the tab is one character but eight columns wide


def test_escape_clears_the_selection_and_ctrl_c_copies(viewer, app):
    win = viewer({"a.txt": "hello\n"})
    v = win.view
    v.block = False
    v.anchor, v.head = (0, 0), (0, 5)
    QTest.keyClick(v, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "hello"
    QTest.keyClick(v, Qt.Key.Key_Escape)
    assert not v.has_selection()


# from the commander --------------------------------------------------------------------------------------------
@pytest.fixture
def commander(app, tmp_path):
    left = tmp_path / "left"
    left.mkdir()
    (left / "a.txt").write_text("alpha\n")
    (left / "b.txt").write_text("beta\n")
    (left / "sub").mkdir()
    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(tmp_path)), dialogs=dialogs)
    win.show()
    win.activateWindow()
    activate_window(win)
    yield win, dialogs
    win.close()


def test_f3_opens_the_file_under_the_cursor(commander):
    win, _d = commander
    win.left.table.setCurrentIndex(win.left.model.index(2, 0))      # a.txt (row 0 is .., row 1 is sub)
    QTest.keyClick(win.left.table, Qt.Key.Key_F3)
    QApplication.processEvents()
    assert len(win.viewers) == 1
    viewer = win.viewers[0]
    settle(viewer)
    assert viewer.source.line(0) == "alpha"


def test_f3_on_marked_files_steps_through_them(commander):
    win, _d = commander
    win.selection.add([str(os.path.join(win.left.path, n)) for n in ("a.txt", "b.txt")])
    win.view_file()
    viewer = win.viewers[0]
    settle(viewer)
    assert len(viewer.paths) == 2 and viewer.file_buttons_visible


def test_f3_on_a_folder_asks_for_a_file(commander):
    win, dialogs = commander
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))      # sub
    win.view_file()
    assert win.viewers == [] and dialogs.infos and "file" in dialogs.infos[-1][1]


def test_closing_the_commander_closes_its_viewers(commander):
    win, _d = commander
    win.left.table.setCurrentIndex(win.left.model.index(2, 0))
    win.view_file()
    viewer = win.viewers[0]
    win.close()
    QApplication.processEvents()
    from PyQt6 import sip
    assert sip.isdeleted(viewer)          # closed, and deleted with it (WA_DeleteOnClose)


def test_menus_view_has_modes_and_notes_while_settings_has_the_choices(commander):
    win, _d = commander
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert titles == ["Files", "Mark", "View", "Commands", "Settings", "Help"]
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    view = [a.text() for a in menus["View"].actions() if not a.isSeparator()]
    assert view == ["Details", "Folder Notes", "Home Page", "Edit the Path", "Refresh", "Tabs"]
    settings = [a.text() for a in menus["Settings"].actions()]
    assert settings == ["Color Scheme", "Copy Speed Limit", "Verify Copies After Copying", "Ask When a File Cannot Be Copied", "Slowness Log", "Icon Set", "Drive Selector"]


def test_folder_notes_can_be_switched_off_and_the_choice_is_kept(commander, tmp_path):
    win, _d = commander
    (tmp_path / "left" / "README.md").write_text("A note.")
    win.left.refresh()
    assert win.left.model.note_row >= 0
    win.act_notes.setChecked(False)
    assert win.left.model.note_row == -1
    win.close()
    again = MainWindow(settings_path=str(tmp_path / "s.ini"), dialogs=FakeDialogs())
    try:
        assert not again.act_notes.isChecked() and again.left.model.note_row == -1
    finally:
        again.close()
