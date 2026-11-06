"""The copy box with a bar for the file and one for the whole job, and a Pause button (decided 2026-11-06, option R, after TeraCopy).

Small files go eight at a time, so "this file" means something only for a big one, which always runs alone: the file bar shows while a
big file is copied, with its own speed and time left, and is hidden for small files. Pause in the box pauses the queue, as Tools >
Operations > Pause or Resume Operations does, and the box shows which it is."""
import os

import pytest

from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import ExecOptions, execute, plan_copy
from dossier.core.progress import RateMeter

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def test_a_big_file_reports_its_own_bytes_and_a_small_one_does_not():
    fs = MemoryFileSystem()
    fs.makedirs("mem://dst")
    fs.put("mem://src/big.bin", b"x" * 3_000_000)
    fs.put("mem://src/small.txt", b"y" * 100)
    plan = plan_copy(fs, ["mem://src/big.bin", "mem://src/small.txt"], "mem://dst")
    seen = []
    execute(plan, fs, options=ExecOptions(small_limit=1_000_000,
                                          on_file_bytes=lambda op, done, size: seen.append((op.src.rsplit("/", 1)[1], done, size))))
    assert {name for name, _d, _s in seen} == {"big.bin"}
    assert seen[-1] == ("big.bin", 3_000_000, 3_000_000) and all(a[1] <= b[1] for a, b in zip(seen, seen[1:]))


def box_for(on_pause=None):
    from dossier.gui import dialogs
    return dialogs.ProgressBox(None, "Copy", lambda: None, on_pause=on_pause)


def test_the_file_bar_shows_for_a_big_file_with_its_own_speed_and_time_left(app):
    box = box_for()
    clock = Clock()
    box._file_meter = RateMeter(clock=clock)
    size = 800 * 1024 * 1024
    for second in range(6):
        clock.t = 100.0 + second
        box.set_file("holiday.mkv", second * 40 * 1024 * 1024, size)
    assert box.file_shown()
    line = box.file_text()
    assert line.startswith("This file") and "200 MB of 800 MB" in line and "40 MB/s" in line and "15 s left" in line
    box.set_paused(True)
    assert "MB/s" not in box.file_text() and "200 MB of 800 MB" in box.file_text()      # paused: no speed that is not there
    box.clear_file()
    assert not box.file_shown()
    box.close()


def test_a_new_file_starts_its_own_speed_again(app):
    box = box_for()
    clock = Clock()
    box._file_meter = RateMeter(clock=clock)
    for second in range(4):
        clock.t = 100.0 + second
        box.set_file("one.mkv", second * 100 * 1024 * 1024, 1024 ** 3)
    box.set_file("two.mkv", 0, 1024 ** 3)
    assert "MB/s" not in box.file_text()                                   # no speed yet for the new file
    box.close()


def test_pause_in_the_box_asks_the_window_and_the_box_says_paused(app):
    asked = []
    box = box_for(on_pause=lambda: asked.append(1))
    assert box.pause_button.text() == "Pause"
    box.pause_button.click()
    assert asked == [1]
    box.set_paused(True)
    assert box.pause_button.text() == "Resume" and "Paused" in box.text()
    box.set_paused(False)
    assert box.pause_button.text() == "Pause" and "Paused" not in box.text()
    box.close()
    plain = box_for()
    assert plain.pause_button is None                                       # a box with nothing to pause has no button
    plain.close()


def test_closing_the_box_when_the_job_ends_is_not_a_cancel(app):
    from dossier.gui import dialogs
    cancelled = []
    box = dialogs.ProgressBox(None, "Copy", lambda: cancelled.append(1))
    box._dlg.show()
    box.close()
    assert cancelled == []


def test_the_window_feeds_the_file_bar_and_the_box_pauses_the_queue(world):
    win, dialogs, left, right, _t = world
    (left / "big.bin").write_bytes(os.urandom(9 * 1024 * 1024))           # over the 8 MB that makes a file big
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("big.bin"), 0))
    win.copy()
    pump(win, lambda: (right / "big.bin").exists() and dialogs.progress_boxes and dialogs.progress_boxes[-1].closed, timeout=20)
    box = dialogs.progress_boxes[-1]
    assert box.files and box.files[-1][0] == "big.bin" and box.files[-1][2] == 9 * 1024 * 1024
    box.pause()
    assert win.paused
    win.toggle_pause()
    assert not win.paused
