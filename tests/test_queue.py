"""C4: operations queue instead of being refused, and can be paused and resumed."""
import threading
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core.progress import Cancelled, CancelToken  # noqa: E402
from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def test_a_paused_token_waits_and_a_resume_or_cancel_wakes_it():
    token = CancelToken()
    token.pause()
    assert token.paused
    done = []
    t = threading.Thread(target=lambda: (token.check(), done.append(1)))
    t.start()
    time.sleep(0.15)
    assert not done
    token.resume()
    t.join(2)
    assert done == [1] and not token.paused
    token.pause()
    out = []

    def waiter():
        try:
            token.check()
        except Cancelled:
            out.append("cancelled")

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    token.cancel()
    t.join(2)
    assert out == ["cancelled"]


def fill(left, n=3):
    for i in range(n):
        (left / f"f{i}.txt").write_text(str(i) * 50)


def mark_all_and_copy(win):
    """Copy the file under the cursor (the first one)."""
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.copy()


def move_second(win):
    win.left.table.setCurrentIndex(win.left.model.index(2, 0))
    win.move()


def test_a_second_operation_while_one_runs_is_queued_not_refused(world):
    win, dialogs, left, right, _t = world
    fill(left)
    win.paused = False
    win.toggle_pause()                                     # nothing runs until resumed
    mark_all_and_copy(win)
    assert win.busy and len(win._jobs) == 1
    move_second(win)
    assert len(win._jobs) == 2 and "1 waiting" in win.queue_label.text()
    assert "Paused" in win.queue_label.text()
    assert list(right.iterdir()) == []                     # still nothing done
    win.toggle_pause()
    pump(win, lambda: len(win._jobs) == 0, timeout=10)
    assert sorted(p.name for p in right.iterdir()) == ["f0.txt", "f1.txt"]
    assert (left / "f0.txt").exists() and not (left / "f1.txt").exists()     # the queued move ran after the copy
    assert not win.queue_label.isVisible()


def test_waiting_operations_can_be_cancelled_and_the_running_one_finishes(world):
    win, _d, left, right, _t = world
    fill(left)
    win.toggle_pause()
    mark_all_and_copy(win)
    move_second(win)
    win.cancel_waiting()
    win.toggle_pause()
    pump(win, lambda: len(win._jobs) == 0, timeout=10)
    assert (left / "f1.txt").exists()                      # the move never ran
    assert [p.name for p in right.iterdir()] == ["f0.txt"] # the copy did


def test_closing_the_window_with_a_paused_queue_does_not_hang(world):
    win, _d, left, _r, _t = world
    fill(left)
    win.toggle_pause()
    mark_all_and_copy(win)
    win.close()                                            # the fixture closes again: both must return
