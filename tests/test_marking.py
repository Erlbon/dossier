"""Marking several items with the keyboard and the mouse, the way Explorer users expect, on top of Space."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def setup_files(win, left, n=6):
    for i in range(n):
        (left / f"f{i}.txt").write_text(str(i))
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))          # row 0 is ".."


def shift_key(win, k):
    """A key pressed while Shift stays held down, as on a real keyboard (QTest.keyClick releases Shift each time)."""
    table = win.left.table
    QTest.keyPress(table, k, SHIFT)
    QTest.keyRelease(table, k)


def marked(win):
    return sorted(p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in win.selection.paths())


def row_pos(win, row):
    table = win.left.table
    rect = table.visualRect(win.left.model.index(row, 0))
    return QPoint(rect.center().x(), rect.center().y())


def test_shift_down_marks_the_rows_it_passes_and_shift_up_takes_them_back(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    for _ in range(2):
        shift_key(win, Qt.Key.Key_Down)
    assert marked(win) == ["f0.txt", "f1.txt", "f2.txt"]
    shift_key(win, Qt.Key.Key_Up)
    assert marked(win) == ["f0.txt", "f1.txt"]                          # the range follows the cursor
    QTest.keyRelease(win.left.table, Qt.Key.Key_Shift)
    key(win, Qt.Key.Key_Down)
    assert marked(win) == ["f0.txt", "f1.txt"]                          # moving without Shift changes nothing


def test_shift_end_and_home_mark_to_the_ends(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    shift_key(win, Qt.Key.Key_End)
    assert marked(win) == [f"f{i}.txt" for i in range(6)]
    shift_key(win, Qt.Key.Key_Home)
    assert marked(win) == ["f0.txt"]                                   # back at the start: only the anchor row is left


def test_a_second_shift_range_adds_to_the_marks_already_made(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    key(win, Qt.Key.Key_Space)                                          # marks f0, moves to f1
    QTest.keyRelease(win.left.table, Qt.Key.Key_Shift)
    key(win, Qt.Key.Key_Down)
    key(win, Qt.Key.Key_Down)                                           # on f3
    shift_key(win, Qt.Key.Key_Down)
    shift_key(win, Qt.Key.Key_Down)
    assert marked(win) == ["f0.txt", "f3.txt", "f4.txt", "f5.txt"]


def test_ctrl_arrows_move_without_marking_and_ctrl_space_marks_in_place(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    key(win, Qt.Key.Key_Down, CTRL)
    key(win, Qt.Key.Key_Down, CTRL)
    assert marked(win) == [] and win.left.current_name() == "f2.txt"
    key(win, Qt.Key.Key_Space, CTRL)
    assert marked(win) == ["f2.txt"] and win.left.current_name() == "f2.txt"       # marked, did not move
    key(win, Qt.Key.Key_Down, CTRL)
    key(win, Qt.Key.Key_Down, CTRL)
    key(win, Qt.Key.Key_Space, CTRL)
    assert marked(win) == ["f2.txt", "f4.txt"]
    key(win, Qt.Key.Key_Space, CTRL)
    assert marked(win) == ["f2.txt"]                                    # again: unmarks


def test_ctrl_click_toggles_and_a_plain_click_only_moves_the_cursor(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    vp = win.left.table.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, CTRL, row_pos(win, 2))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, CTRL, row_pos(win, 4))
    assert marked(win) == ["f1.txt", "f3.txt"]
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_pos(win, 5))
    assert marked(win) == ["f1.txt", "f3.txt"] and win.left.current_name() == "f4.txt"
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, CTRL, row_pos(win, 2))
    assert marked(win) == ["f3.txt"]


def test_shift_click_marks_from_the_cursor_to_the_click(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    vp = win.left.table.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, SHIFT, row_pos(win, 4))
    assert marked(win) == ["f0.txt", "f1.txt", "f2.txt", "f3.txt"]


def test_dragging_over_rows_marks_them_and_back_again_unmarks(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    vp = win.left.table.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_pos(win, 2))
    for row in (3, 4, 5):
        QTest.mouseMove(vp, row_pos(win, row))
        # the move needs the button held: send it as a real event
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent, QPointF
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(row_pos(win, row)), vp.mapToGlobal(QPointF(row_pos(win, row))),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win_app = __import__("PyQt6.QtWidgets", fromlist=["QApplication"]).QApplication
        win_app.sendEvent(vp, event)
    assert marked(win) == ["f1.txt", "f2.txt", "f3.txt", "f4.txt"]
    back = QMouseEvent(QEvent.Type.MouseMove, QPointF(row_pos(win, 3)), vp.mapToGlobal(QPointF(row_pos(win, 3))),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win_app.sendEvent(vp, back)
    assert marked(win) == ["f1.txt", "f2.txt"]
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_pos(win, 3))
    after = marked(win)
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_pos(win, 5))
    assert marked(win) == after                                          # a later plain click leaves the marks alone


def test_the_up_row_is_never_marked(world):
    win, _d, left, *_ = world
    setup_files(win, left, n=3)
    win.left.table.setCurrentIndex(win.left.model.index(0, 0))
    shift_key(win, Qt.Key.Key_Down)
    shift_key(win, Qt.Key.Key_Down)
    assert marked(win) == ["f0.txt", "f1.txt"]


def test_home_and_end_go_to_the_first_and_last_item(world):
    win, _d, left, *_ = world
    setup_files(win, left)
    key(win, Qt.Key.Key_End)
    assert win.left.current_name() == "f5.txt"
    key(win, Qt.Key.Key_Home)
    assert win.left.table.currentIndex().row() == 0                     # the ".." row is the first row
