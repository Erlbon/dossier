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


def test_a_drag_that_starts_on_its_own_item_can_still_land_on_a_folder_in_the_same_list(world):
    """As a real drag goes: it enters the list over the item being dragged (no place to land), then moves to a folder row.
    Refusing the enter made Qt send the list nothing more of that drag, so a move within one panel never worked."""
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent
    win, d, left, right, tmp = world
    filled(win, left, ("a.txt", "b.txt"))
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("box") >= 0)
    mime = dragdrop.make_mime([str(left / "a.txt")], str(id(win.left)))
    none = Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(row_center(win.left, "a.txt"), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, none)
    win.left.table.dragEnterEvent(enter)
    assert enter.isAccepted() and win.left.model.drop_row == -1               # taken, but nothing is lit on its own row
    on_file = QDragMoveEvent(row_center(win.left, "b.txt"), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, none)
    win.left.table.dragMoveEvent(on_file)
    assert not on_file.isAccepted()                                           # a file row of its own list is no place to land
    on_box = QDragMoveEvent(row_center(win.left, "box"), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, none)
    win.left.table.dragMoveEvent(on_box)
    assert on_box.isAccepted() and win.left.model.drop_row == win.left.model.row_of("box")
    drop(win.left, [str(left / "a.txt")], pos=row_center(win.left, "box"), source=str(id(win.left)))
    pump(win, lambda: (left / "box" / "a.txt").exists() and not win.busy)
    assert not (left / "a.txt").exists()


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

    def added():                                   # the window swaps the zip on a thread: read it once, and never while it is swapped
        try:
            with zipfile.ZipFile(z) as w:
                return "new.txt" in w.namelist()
        except (OSError, zipfile.BadZipFile):
            return False
    pump(win, lambda: not win.busy and added())


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


# spring-loaded folders, tabs and drives (card 62A) ---------------------------------------------------------------------------
def _drag_move(widget, pos, mime):
    from PyQt6.QtGui import QDragMoveEvent
    event = QDragMoveEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    widget.dragMoveEvent(event)
    return event


def _leave(widget):
    from PyQt6.QtGui import QDragLeaveEvent
    widget.dragLeaveEvent(QDragLeaveEvent())


def _springy(world, monkeypatch, delay=40):
    from dossier.gui.spring_open import SpringTimer
    monkeypatch.setattr(SpringTimer, "DELAY_MS", delay)
    win, d, left, right, tmp = world
    (right / "box").mkdir()
    (right / "box" / "inner.txt").write_text("i")
    (right / "plain.txt").write_text("p")
    win.right.refresh()
    pump(win, lambda: win.right.model.row_of("box") >= 0 and win.right.model.row_of("plain.txt") >= 0)
    return win, left, right, dragdrop.make_mime([str(left / "x")], str(id(win.left)))


def test_a_drag_held_over_a_folder_opens_it_after_the_delay(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    event = _drag_move(win.right.table, row_center(win.right, "box"), mime)
    assert event.isAccepted() and win.right.path == str(right)                 # not at once
    pump(win, lambda: win.right.path == str(right / "box"))
    assert win.right.model.drop_row == -1


def test_leaving_before_the_delay_opens_nothing(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch, delay=150)
    _drag_move(win.right.table, row_center(win.right, "box"), mime)
    _leave(win.right.table)
    QTest.qWait(300)
    assert win.right.path == str(right)
    _drag_move(win.right.table, row_center(win.right, "box"), mime)           # moving on to a file row cancels it as well
    _drag_move(win.right.table, row_center(win.right, "plain.txt"), mime)
    QTest.qWait(300)
    assert win.right.path == str(right)


def test_with_the_setting_off_nothing_springs_open(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    assert win.act_spring_open.isChecked()
    win.act_spring_open.setChecked(False)
    assert win.right.spring_open is False and win.left.spring_open is False
    _drag_move(win.right.table, row_center(win.right, "box"), mime)
    QTest.qWait(250)
    assert win.right.path == str(right)
    win.act_spring_open.setChecked(True)
    assert win.right.spring_open is True


def test_the_dragged_folder_itself_and_a_mac_package_do_not_spring(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    (right / "Thing.app").mkdir()
    win.right.refresh()
    pump(win, lambda: win.right.model.row_of("Thing.app") >= 0)
    own = dragdrop.make_mime([str(right / "box")], str(id(win.right)))
    _drag_move(win.right.table, row_center(win.right, "box"), own)             # a folder hovering over itself
    win.right.spring_mac = True
    _drag_move(win.right.table, row_center(win.right, "Thing.app"), mime)       # a package on the Mac
    QTest.qWait(250)
    assert win.right.path == str(right)


def test_the_up_row_does_not_spring(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    win.right.set_folder(str(right / "box"))
    pump(win, lambda: win.right.path == str(right / "box") and win.right.model.row_of("inner.txt") >= 0)
    up = next(r for r in range(win.right.model.entry_count()) if win.right.model.is_up_row(r))
    _drag_move(win.right.table, win.right.table.visualRect(win.right.model.index(up, 0)).center(), mime)
    QTest.qWait(250)
    assert win.right.path == str(right / "box")


def test_a_drag_held_over_a_tab_switches_to_it(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    win.right.new_tab(str(left), activate=False)
    assert win.right.tabs.count() == 2 and win.right.tabs.currentIndex() == 0
    bar = win.right.tabs
    pos = bar.tabRect(1).center()
    event = _drag_move(bar, pos, mime)
    assert not event.isAccepted()                                              # no drop on a tab bar
    assert win.right.tabs.currentIndex() == 0
    pump(win, lambda: win.right.tabs.currentIndex() == 1)
    pump(win, lambda: win.right.path == str(left))


def test_a_drag_held_over_a_drive_on_the_home_page_opens_it(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    win.right.set_folder("home://")
    pump(win, lambda: win.right.is_home and win.right.model.entry_count() > 1)
    row = next(r for r in range(win.right.model.entry_count())
               if win.right.model.entry_at(r).kind not in ("header", "action") and win.right.model.entry_at(r).is_dir)
    target = win.right.model.entry_at(row).path
    opened = []
    monkeypatch.setattr(win.right, "set_folder", lambda path, *a, **k: opened.append(path) or True)
    _drag_move(win.right.table, win.right.table.visualRect(win.right.model.index(row, 0)).center(), mime)
    pump(win, lambda: opened)
    assert opened == [target]


def test_after_a_spring_the_drop_lands_in_the_folder_it_opened(world, monkeypatch):
    win, left, right, mime = _springy(world, monkeypatch)
    (left / "a.txt").write_text("A")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.txt") >= 0)
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("box") >= 0)
    own = dragdrop.make_mime([str(left / "a.txt")], str(id(win.left)))
    _drag_move(win.left.table, row_center(win.left, "box"), own)
    pump(win, lambda: win.left.path == str(left / "box"))
    drop(win.left, [str(left / "a.txt")], source=str(id(win.left)))             # on the empty space of the folder that sprang open
    pump(win, lambda: (left / "box" / "a.txt").exists() and not win.busy)


# the way back when nothing is dropped (card 62A) ------------------------------------------------------------------------------
def test_a_drag_from_another_program_that_leaves_sends_the_panel_back(world, monkeypatch):
    from dossier.gui.spring_open import SpringTimer
    win, left, right, mime = _springy(world, monkeypatch)
    monkeypatch.setattr(SpringTimer, "LEAVE_MS", 40)
    _drag_move(win.right.table, row_center(win.right, "box"), mime)
    pump(win, lambda: win.right.path == str(right / "box"))
    _leave(win.right.table)                                                   # Esc, or a drop outside the panel, ends in a leave
    pump(win, lambda: win.right.path == str(right))


def test_a_drag_from_dossier_ends_when_exec_returns_and_the_panel_goes_back(world, monkeypatch):
    from dossier.gui.spring_open import SpringTimer
    win, left, right, mime = _springy(world, monkeypatch)
    monkeypatch.setattr(SpringTimer, "internal", True)
    _drag_move(win.right.table, row_center(win.right, "box"), mime)
    pump(win, lambda: win.right.path == str(right / "box"))
    _leave(win.right.table)
    QTest.qWait(150)
    assert win.right.path == str(right / "box")                               # a leave alone does not end a drag of ours
    SpringTimer.drag_finished()
    pump(win, lambda: win.right.path == str(right))


def test_after_a_drop_in_the_panel_it_stays_where_it_sprang_to(world, monkeypatch):
    from dossier.gui.spring_open import SpringTimer
    win, left, right, mime = _springy(world, monkeypatch)
    monkeypatch.setattr(SpringTimer, "LEAVE_MS", 40)
    (left / "a.txt").write_text("A")
    _drag_move(win.right.table, row_center(win.right, "box"), mime)
    pump(win, lambda: win.right.path == str(right / "box"))
    drop(win.right, [str(left / "a.txt")], source=str(id(win.left)))
    pump(win, lambda: (right / "box" / "a.txt").exists() and not win.busy)
    _leave(win.right.table)
    SpringTimer.drag_finished()
    QTest.qWait(150)
    assert win.right.path == str(right / "box")


def test_a_spring_on_a_tab_goes_back_to_the_original_tab(world, monkeypatch):
    from dossier.gui.spring_open import SpringTimer
    win, left, right, mime = _springy(world, monkeypatch)
    monkeypatch.setattr(SpringTimer, "LEAVE_MS", 40)
    win.right.new_tab(str(left), activate=False)
    bar = win.right.tabs
    _drag_move(bar, bar.tabRect(1).center(), mime)
    pump(win, lambda: win.right.tabs.currentIndex() == 1 and win.right.path == str(left))
    _leave(bar)
    pump(win, lambda: win.right.tabs.currentIndex() == 0 and win.right.path == str(right))
