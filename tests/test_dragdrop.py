"""Dragging files: out of a panel, into the other one, onto a folder, and to and from other programs."""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from dossier.core.zipfs import archive_root  # noqa: E402
from dossier.gui import dragdrop, panel as panel_module  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

SEP = os.sep


# the helpers --------------------------------------------------------------------------------------------------------
def test_a_drop_onto_itself_or_into_its_own_subfolder_makes_no_sense():
    a = SEP.join(["C:", "data", "a"])
    assert not dragdrop.can_drop([a], a, SEP) and not dragdrop.can_drop([a], a + SEP + "sub", SEP)
    assert dragdrop.can_drop([a], SEP.join(["C:", "data", "b"]), SEP) and dragdrop.can_drop([a], SEP.join(["C:", "data", "a2"]), SEP)
    assert not dragdrop.can_drop([], a, SEP) and not dragdrop.can_drop([a], "", SEP)


def test_the_mime_carries_our_exact_paths_and_file_urls_for_files_on_a_drive():
    data = dragdrop.make_mime(["C:" + SEP + "a.txt", "C:" + SEP + "b.txt"], "42")
    assert dragdrop.read_paths(data) == (["C:" + SEP + "a.txt", "C:" + SEP + "b.txt"], "42")
    assert len(data.urls()) == 2
    inside = dragdrop.make_mime(["zip://C:" + SEP + "a.zip!/x.txt"], "7")
    assert dragdrop.read_paths(inside)[0] == ["zip://C:" + SEP + "a.zip!/x.txt"] and not inside.hasUrls()


def test_files_dragged_in_from_another_program_are_read_from_their_urls(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(f))])
    paths, source = dragdrop.read_paths(data)
    assert paths == [os.path.normpath(str(f))] and source is None
    assert dragdrop.read_paths(QMimeData()) == ([], None)


# starting a drag ----------------------------------------------------------------------------------------------------
class FakeDrag:
    made = []

    def __init__(self, parent):
        self.mime = None
        FakeDrag.made.append(self)

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pixmap):
        pass

    def exec(self, *args):
        return Qt.DropAction.IgnoreAction


def row_center(panel, name):
    r = panel.model.row_of(name)
    return panel.table.visualRect(panel.model.index(r, 0)).center()


def drag_from(panel, name, dx=40, dy=0):
    start = row_center(panel, name)
    QTest.mousePress(panel.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(panel.table.viewport(), start + QPoint(dx, dy))
    QTest.mouseMove(panel.table.viewport(), start + QPoint(dx * 2, dy * 2))
    QTest.mouseRelease(panel.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(dx * 2, dy * 2))


@pytest.fixture
def fake_drag(monkeypatch):
    FakeDrag.made = []
    monkeypatch.setattr(panel_module, "QDrag", FakeDrag)
    return FakeDrag


def filled(win, left, names=("a.txt", "b.txt", "c.txt")):
    for n in names:
        (left / n).write_text(n)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= len(names) + 1)


def test_dragging_an_unmarked_item_carries_that_item_and_marks_nothing(world, fake_drag):
    win, d, left, *_ = world
    filled(win, left)
    drag_from(win.left, "b.txt", dx=0, dy=30)                       # down over the other rows: this used to mark them
    assert len(fake_drag.made) == 1
    assert dragdrop.read_paths(fake_drag.made[0].mime)[0] == [str(left / "b.txt")]
    assert win.left.marked_here() == []


def test_dragging_a_marked_item_carries_all_the_marked_ones(world, fake_drag):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt"), str(left / "c.txt")])
    drag_from(win.left, "c.txt")
    paths = dragdrop.read_paths(fake_drag.made[0].mime)[0]
    assert sorted(paths) == sorted([str(left / "a.txt"), str(left / "c.txt")])


def test_an_unmarked_item_is_dragged_alone_even_when_others_are_marked(world, fake_drag):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt")])
    drag_from(win.left, "b.txt")
    assert dragdrop.read_paths(fake_drag.made[0].mime)[0] == [str(left / "b.txt")]


def test_the_up_row_and_a_click_start_no_drag(world, fake_drag):
    win, d, left, *_ = world
    filled(win, left)
    start = row_center(win.left, "a.txt")
    QTest.mouseClick(win.left.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    up = win.left.table.visualRect(win.left.model.index(0, 0)).center()
    QTest.mousePress(win.left.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, up)
    QTest.mouseMove(win.left.table.viewport(), up + QPoint(60, 0))
    QTest.mouseMove(win.left.table.viewport(), up + QPoint(120, 0))
    QTest.mouseRelease(win.left.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, up + QPoint(120, 0))
    assert fake_drag.made == []


# taking a drop ------------------------------------------------------------------------------------------------------
def drop(panel, paths, pos=None, source="other", mods=Qt.KeyboardModifier.NoModifier):
    point = pos if pos is not None else QPoint(10, panel.table.viewport().height() - 5)       # empty space below the rows
    mime = dragdrop.make_mime(paths, source)
    event = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, mods)
    panel.table.dropEvent(event)
    return event


def test_dropping_on_the_other_panel_moves_on_the_same_drive(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt",))
    win.right.refresh()
    drop(win.right, [str(left / "a.txt")], source=str(id(win.left)))
    pump(win, lambda: (right / "a.txt").exists() and not win.busy)
    assert not (left / "a.txt").exists() and (right / "a.txt").read_text() == "a.txt"
    assert not d.confirms                                          # a drop does not ask unless the setting says so


def test_ctrl_copies_and_shift_moves(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt", "b.txt"))
    drop(win.right, [str(left / "a.txt")], source=str(id(win.left)), mods=Qt.KeyboardModifier.ControlModifier)
    pump(win, lambda: (right / "a.txt").exists() and not win.busy)
    assert (left / "a.txt").exists()
    drop(win.right, [str(left / "b.txt")], source=str(id(win.left)), mods=Qt.KeyboardModifier.ShiftModifier)
    pump(win, lambda: (right / "b.txt").exists() and not win.busy)
    assert not (left / "b.txt").exists()


def test_dropping_on_a_folder_row_puts_the_files_inside_it(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt",))
    (right / "box").mkdir()
    win.right.refresh()
    pump(win, lambda: win.right.model.row_of("box") >= 0)
    drop(win.right, [str(left / "a.txt")], pos=row_center(win.right, "box"), source=str(id(win.left)))
    pump(win, lambda: (right / "box" / "a.txt").exists() and not win.busy)


def test_dropping_inside_the_same_panel_needs_a_folder_row(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt", "b.txt"))
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("box") >= 0)
    drop(win.left, [str(left / "a.txt")], source=str(id(win.left)))                 # on empty space of its own list
    drop(win.left, [str(left / "a.txt")], pos=row_center(win.left, "b.txt"), source=str(id(win.left)))     # on a file row
    assert (left / "a.txt").exists() and not win._plans
    drop(win.left, [str(left / "a.txt")], pos=row_center(win.left, "box"), source=str(id(win.left)))
    pump(win, lambda: (left / "box" / "a.txt").exists() and not win.busy)


def test_a_folder_cannot_be_dropped_into_itself(world):
    win, d, left, right, tmp = world
    (left / "box").mkdir()
    (left / "box" / "inner").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("box") >= 0)
    event = drop(win.left, [str(left / "box")], pos=row_center(win.left, "box"), source=str(id(win.left)))
    assert not event.isAccepted() and (left / "box").exists() and not win._plans


def test_the_drop_asks_about_a_clash_and_only_then(world):
    from dossier.core.ops import Resolution
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt",))
    (right / "a.txt").write_text("OLD")
    d.conflict_answer = Resolution.SKIP
    drop(win.right, [str(left / "a.txt")], source=str(id(win.left)))
    pump(win, lambda: getattr(d, "conflict_rows_seen", None))
    pump(win, lambda: not win.busy)
    assert (right / "a.txt").read_text() == "OLD" and (left / "a.txt").exists()


def test_the_confirmation_box_comes_back_when_the_setting_asks_for_it(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt",))
    win.settings.setValue("copy/ask_on_drop", "true")
    drop(win.right, [str(left / "a.txt")], source=str(id(win.left)))
    pump(win, lambda: d.confirms)
    pump(win, lambda: (right / "a.txt").exists() and not win.busy)


def test_files_from_another_program_are_dropped_like_ours(world, tmp_path):
    win, d, left, right, tmp = world
    outside = tmp / "elsewhere"
    outside.mkdir()
    (outside / "ext.txt").write_text("E")
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(outside / "ext.txt"))])
    event = QDropEvent(QPointF(10, win.right.table.viewport().height() - 5), Qt.DropAction.CopyAction, data,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    win.right.table.dropEvent(event)
    pump(win, lambda: (right / "ext.txt").exists() and not win.busy)
    assert (outside / "ext.txt").exists()


def test_a_drop_into_an_open_zip_adds_to_the_zip(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("keep.txt", "k")
    filled(win, left, ("new.txt",))
    win.right.set_folder(archive_root(str(z)))
    pump(win, lambda: win.right.path.startswith("zip://") and win.right.model.entry_count() >= 1)
    drop(win.right, [str(left / "new.txt")], source=str(id(win.left)), mods=Qt.KeyboardModifier.ControlModifier)
    pump(win, lambda: d.confirms)
    pump(win, lambda: not win.busy and "new.txt" in (zipfile.ZipFile(z).namelist() if z.exists() else []))


def test_a_drag_out_of_an_archive_copies_out(world):
    win, d, left, right, tmp = world
    z = left / "a.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("in.txt", "I")
    win.left.set_folder(archive_root(str(z)))
    pump(win, lambda: win.left.path.startswith("zip://") and win.left.model.entry_count() >= 2)
    drop(win.right, [archive_root(str(z)) + "in.txt"], source=str(id(win.left)))
    pump(win, lambda: (right / "in.txt").exists() and not win.busy)
    assert (right / "in.txt").read_text() == "I"


def test_places_that_cannot_take_files_refuse_the_drop(world):
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt",))
    win.right.set_folder("home://")
    pump(win, lambda: win.right.is_home)
    event = drop(win.right, [str(left / "a.txt")], source=str(id(win.left)))
    assert not event.isAccepted() and (left / "a.txt").exists()


def test_the_folder_under_a_dragging_pointer_is_highlighted(world):
    win, d, left, right, tmp = world
    (right / "box").mkdir()
    win.right.refresh()
    pump(win, lambda: win.right.model.row_of("box") >= 0)
    from PyQt6.QtGui import QDragMoveEvent
    mime = dragdrop.make_mime([str(left / "x")], str(id(win.left)))
    pos = row_center(win.right, "box")
    event = QDragMoveEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.right.table.dragMoveEvent(event)
    assert win.right.model.drop_row == win.right.model.row_of("box") and event.isAccepted()
    win.right.table.dragLeaveEvent(__import__("PyQt6.QtGui", fromlist=["QDragLeaveEvent"]).QDragLeaveEvent())
    assert win.right.model.drop_row == -1


# Ctrl+click and drag marks a range --------------------------------------------------------------------------------------
def ctrl_drag(panel, first, last):
    a, b = row_center(panel, first), row_center(panel, last)
    view = panel.table.viewport()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, a)
    step = QPoint(0, (b.y() - a.y()) // 3 or 1)
    for i in (1, 2, 3):
        QTest.mouseMove(view, a + step * i)
    QTest.mouseMove(view, b)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, b)


def test_ctrl_click_and_drag_marks_every_item_from_the_click_to_the_pointer(world, fake_drag):
    win, d, left, *_ = world
    filled(win, left, ("a.txt", "b.txt", "c.txt", "d.txt"))
    ctrl_drag(win.left, "b.txt", "d.txt")
    assert sorted(os.path.basename(p) for p in win.left.marked_here()) == ["b.txt", "c.txt", "d.txt"]
    assert fake_drag.made == []                                       # it marked, it did not start a file drag


def test_dragging_back_takes_the_far_end_off_again_and_earlier_marks_stay(world):
    win, d, left, *_ = world
    filled(win, left, ("a.txt", "b.txt", "c.txt", "d.txt"))
    win.selection.add([str(left / "a.txt")])
    a, d_ = row_center(win.left, "b.txt"), row_center(win.left, "d.txt")
    view = win.left.table.viewport()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, a)
    QTest.mouseMove(view, d_)
    assert len(win.left.marked_here()) == 4
    QTest.mouseMove(view, row_center(win.left, "c.txt"))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, row_center(win.left, "c.txt"))
    assert sorted(os.path.basename(p) for p in win.left.marked_here()) == ["a.txt", "b.txt", "c.txt"]


def test_ctrl_click_and_drag_over_marked_items_unmarks_them(world):
    win, d, left, *_ = world
    filled(win, left, ("a.txt", "b.txt", "c.txt"))
    win.selection.add([str(left / n) for n in ("a.txt", "b.txt", "c.txt")])
    ctrl_drag(win.left, "a.txt", "c.txt")                              # the first click unmarks a.txt, so the drag unmarks
    assert win.left.marked_here() == []


def test_a_plain_ctrl_click_still_just_toggles_one_item(world):
    win, d, left, *_ = world
    filled(win, left, ("a.txt", "b.txt"))
    QTest.mouseClick(win.left.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     row_center(win.left, "b.txt"))
    assert [os.path.basename(p) for p in win.left.marked_here()] == ["b.txt"]
    QTest.mouseClick(win.left.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     row_center(win.left, "b.txt"))
    assert win.left.marked_here() == []
