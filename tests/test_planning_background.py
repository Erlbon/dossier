"""Choosing many folders and pressing copy must not freeze the window: the plan is made on a thread."""
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import ops as ops_module  # noqa: E402
from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def many_files(left, n=40):
    for i in range(n):
        d = left / "tree" / f"d{i % 5}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.txt").write_text("x")


def slow_planning(monkeypatch, delay=0.02):
    real = ops_module._placed

    def slow(*a, **k):
        time.sleep(delay)
        return real(*a, **k)

    monkeypatch.setattr(ops_module, "_placed", slow)


def start_copy(win, left):
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("tree"), 0))
    start = time.time()
    win.copy()
    return time.time() - start


def test_the_window_answers_at_once_while_a_big_plan_is_worked_out(world, monkeypatch):
    win, dialogs, left, right, _t = world
    many_files(left)
    slow_planning(monkeypatch)                                  # about a second of planning
    took = start_copy(win, left)
    assert took < 0.15                                          # pressing copy returns at once, whatever the size
    assert win.busy and not dialogs.confirms                    # the plan is still being made
    ticks = 0
    end = time.time() + 0.3
    while time.time() < end:                                    # and the window keeps handling events meanwhile
        QApplication.processEvents()
        ticks += 1
        time.sleep(0.005)
    assert ticks > 20
    pump(win, lambda: bool(dialogs.confirms), timeout=15)
    assert "tree" in dialogs.confirms[-1][1] and "Copy 1 item" in dialogs.confirms[-1][1]


def test_a_box_with_cancel_appears_for_a_slow_plan_and_cancel_stops_it_and_changes_nothing(world, monkeypatch):
    win, dialogs, left, right, _t = world
    many_files(left)
    slow_planning(monkeypatch, delay=0.05)
    start_copy(win, left)
    pump_until = time.time() + 5
    while time.time() < pump_until and not dialogs.progress_boxes:
        QApplication.processEvents()
        time.sleep(0.01)
    box = dialogs.progress_boxes[0]
    assert "Preparing the copy" in box.title
    assert "items found so far" in box.detail
    box.cancel()                                                # the user presses Cancel
    wait_planned(win)
    assert not win.busy and not dialogs.confirms and list(right.iterdir()) == []
    assert "Cancelled" in win.status.text() and box.closed


def test_a_quick_plan_goes_straight_to_the_confirmation(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.copy()
    wait_planned(win)
    assert dialogs.confirms and len(dialogs.confirms) == 1


def test_paste_and_move_are_planned_in_the_background_too(world, monkeypatch):
    win, dialogs, left, right, _t = world
    many_files(left, 10)
    slow_planning(monkeypatch, delay=0.01)
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("tree"), 0))
    start = time.time()
    win.move()
    assert time.time() - start < 0.15 and win.busy
    wait_planned(win)
    assert dialogs.confirms


def test_closing_the_window_while_a_plan_is_made_does_not_hang(world, monkeypatch):
    win, dialogs, left, right, _t = world
    many_files(left)
    slow_planning(monkeypatch, delay=0.05)
    start_copy(win, left)
    start = time.time()
    win.close()
    assert time.time() - start < 5
