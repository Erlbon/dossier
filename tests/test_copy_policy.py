"""C2 and C3 of the copy engine plan: retry of locked files, the error policy, speed, time left and the limit."""
import errno
import threading
import time

import pytest

from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import ExecOptions, execute, is_transient, plan_copy
from dossier.core.progress import CancelToken, Cancelled, RateMeter, SpeedLimit, human_duration
from dossier.core.vfs import NotWritable


class Flaky(MemoryFileSystem):
    """Creating a target fails ``failures[name]`` times, then works (a file the scanner holds for a moment)."""

    def __init__(self, failures=None, error=None):
        super().__init__()
        self.failures = dict(failures or {})
        self.error = error or (lambda path: PermissionError(13, "in use", path))
        self.attempts = {}
        self.lock = threading.Lock()

    def open_write(self, path, *, exclusive=False):
        name = self.basename(path)
        if name.endswith(".dossier-part"):
            real = name[:-len(".dossier-part")]
            with self.lock:
                self.attempts[real] = self.attempts.get(real, 0) + 1
                left = self.failures.get(real, 0)
                if left:
                    self.failures[real] = left - 1
                    raise self.error(path)
        return super().open_write(path, exclusive=exclusive)


def world(names=("a.txt", "b.txt", "c.txt"), **kw):
    fs = Flaky(**kw)
    fs.makedirs("mem://dst")
    for n in names:
        fs.put(f"mem://src/{n}", b"data-" + n.encode())
    plan = plan_copy(fs, [f"mem://src/{n}" for n in names], "mem://dst")
    return fs, plan


FAST = dict(retry_delay=0.001)


# what counts as transient ---------------------------------------------------------------------------------
def test_locks_are_transient_and_missing_files_full_disks_and_read_only_are_not():
    assert is_transient(PermissionError(13, "denied"))
    assert is_transient(OSError(errno.EBUSY, "busy"))
    sharing = OSError(13, "sharing violation")
    sharing.winerror = 32
    assert is_transient(sharing)
    assert not is_transient(FileNotFoundError(2, "gone"))
    assert not is_transient(FileExistsError(17, "taken"))
    assert not is_transient(OSError(errno.ENOSPC, "disk full"))
    assert not is_transient(NotWritable("read-only"))


# C2: retry -------------------------------------------------------------------------------------------------
def test_a_file_that_is_locked_for_a_moment_is_copied_on_a_later_try():
    fs, plan = world(failures={"b.txt": 2})
    res = execute(plan, fs, options=ExecOptions(**FAST))
    assert not res.failed and len(res.done) == 3
    assert fs.attempts["b.txt"] == 3
    assert [r.op.src.endswith("b.txt") for r in res.retried] == [True] and res.retried[0].attempts == 3
    assert fs.stat("mem://dst/b.txt").size == len(b"data-b.txt")


def test_a_file_that_stays_locked_fails_after_the_retries_and_the_others_are_copied():
    fs, plan = world(failures={"b.txt": 99})
    res = execute(plan, fs, options=ExecOptions(retries=2, **FAST))
    assert [r.op.src.endswith("b.txt") for r in res.failed] == [True]
    assert fs.attempts["b.txt"] == 3                          # the first try and two more
    assert len(res.done) == 2 and not res.aborted


def test_an_error_that_cannot_pass_is_not_tried_again():
    fs, plan = world(failures={"b.txt": 99}, error=lambda path: OSError(errno.ENOSPC, "disk full", path))
    res = execute(plan, fs, options=ExecOptions(**FAST))
    assert fs.attempts["b.txt"] == 1 and len(res.failed) == 1


def test_retries_can_be_switched_off():
    fs, plan = world(failures={"b.txt": 1})
    res = execute(plan, fs, options=ExecOptions(retries=0, **FAST))
    assert len(res.failed) == 1 and fs.attempts["b.txt"] == 1


def test_cancel_during_the_wait_stops_at_once():
    fs, plan = world(failures={"b.txt": 99})
    token = CancelToken()
    seen = []

    def on_error(op, text):
        seen.append(text)
        return "skip"

    threading.Timer(0.2, token.cancel).start()
    res = execute(plan, fs, cancel=token, options=ExecOptions(retry_delay=5.0, on_error=on_error))
    assert res.cancelled and not seen


# C2: the error policy ----------------------------------------------------------------------------------------
def test_on_error_skip_keeps_going_and_reports_the_failure():
    fs, plan = world(failures={"b.txt": 99})
    asked = []
    res = execute(plan, fs, options=ExecOptions(retries=0, on_error=lambda op, t: asked.append(op.src) or "skip", **FAST))
    assert len(asked) == 1 and len(res.failed) == 1 and len(res.done) == 2


def test_on_error_retry_tries_again_and_can_succeed():
    fs, plan = world(failures={"b.txt": 2})
    answers = []

    def on_error(op, text):
        answers.append(text)
        return "retry"

    res = execute(plan, fs, options=ExecOptions(retries=0, on_error=on_error, **FAST))
    assert len(answers) == 2 and not res.failed and len(res.done) == 3


def test_on_error_abort_stops_the_steps_that_have_not_started():
    fs, plan = world(names=("a.txt", "b.txt", "c.txt", "d.txt"), failures={"b.txt": 99})
    res = execute(plan, fs, options=ExecOptions(retries=0, workers=1, on_error=lambda op, t: "abort", **FAST))
    assert res.aborted
    assert [r.op.src.rsplit("/", 1)[1] for r in res.results] == ["a.txt", "b.txt"]
    assert res.results[1].status == "failed"
    assert fs.stat("mem://dst/a.txt").size > 0                 # what was done stays done


# C3: speed and time left -------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_the_rate_meter_measures_over_a_window_and_estimates_the_time_left():
    clock = Clock()
    meter = RateMeter(window=4.0, clock=clock)
    assert meter.speed() == 0.0
    for second in range(0, 11):
        clock.t = 100.0 + second
        meter.add(second * 10_000_000)
    assert meter.speed() == pytest.approx(10_000_000, rel=0.01)
    assert meter.seconds_left(100_000_000, 300_000_000) == pytest.approx(20, rel=0.02)
    assert meter.seconds_left(300_000_000, 300_000_000) is None


def test_a_change_of_speed_shows_within_the_window():
    clock = Clock()
    meter = RateMeter(window=3.0, clock=clock)
    done = 0
    for second in range(0, 6):
        clock.t = 100.0 + second
        meter.add(done)
        done += 50_000_000
    for second in range(6, 12):
        clock.t = 100.0 + second
        meter.add(done)
        done += 1_000_000
    assert meter.speed() < 5_000_000


def test_progress_that_goes_back_after_a_retry_does_not_give_a_negative_speed():
    clock = Clock()
    meter = RateMeter(clock=clock)
    meter.add(0)
    clock.t += 1
    meter.add(5_000_000)
    clock.t += 1
    meter.add(0)
    clock.t += 1
    meter.add(2_000_000)
    assert meter.speed() >= 0


def test_durations_read_naturally():
    assert human_duration(None) == "" and human_duration(0.2) == "1 s" and human_duration(45) == "45 s"
    assert human_duration(125) == "2 min 05 s" and human_duration(3 * 3600 + 120) == "3 h 02 min"


def test_the_speed_limit_spaces_the_chunks_out():
    clock = Clock()
    slept = []

    def sleep(step):
        slept.append(step)
        clock.t += step

    limit = SpeedLimit(1_000_000, clock=clock, sleep=sleep)
    for _ in range(10):
        limit.wait(500_000)                                    # 5 MB in all
    assert 4.5 <= clock.t - 100.0 <= 5.0               # 5 s of data, less the short burst allowed


def test_the_speed_limit_ends_its_wait_on_cancel():
    token = CancelToken()
    limit = SpeedLimit(10)                                     # 10 bytes a second: 1000 bytes would take 100 s
    threading.Timer(0.2, token.cancel).start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        limit.wait(1000, token)
    assert time.monotonic() - start < 5


def test_a_limited_copy_really_takes_the_time_and_an_unlimited_one_does_not():
    import time
    fs = MemoryFileSystem()
    fs.makedirs("mem://dst")
    fs.put("mem://src/big.bin", b"x" * 400_000)
    plan = plan_copy(fs, ["mem://src/big.bin"], "mem://dst")
    start = time.monotonic()
    res = execute(plan, fs, options=ExecOptions(limit_bps=1_000_000))       # about 0.4 s of data
    took = time.monotonic() - start
    assert not res.failed and took >= 0.1
    fs2 = MemoryFileSystem()
    fs2.makedirs("mem://dst")
    fs2.put("mem://src/big.bin", b"x" * 400_000)
    start = time.monotonic()
    execute(plan_copy(fs2, ["mem://src/big.bin"], "mem://dst"), fs2)
    assert time.monotonic() - start < took


# the window ----------------------------------------------------------------------------------------------
def test_the_progress_box_shows_speed_and_time_left_for_bytes_but_not_for_counts():
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui import dialogs
    app = QApplication.instance() or QApplication([])
    box = dialogs.ProgressBox(None, "Copy", lambda: None)
    clock = Clock()
    box._meter = RateMeter(clock=clock)
    total = 400 * 1024 * 1024
    for second in range(6):
        clock.t = 100.0 + second
        box.update(second * 20 * 1024 * 1024, total)
    text = box.status_text(100 * 1024 * 1024, total)
    assert text.startswith("Copy") and "100 MB of 400 MB" in text and "20 MB/s" in text and "15 s left" in text
    box.close()
    count_box = dialogs.ProgressBox(None, "Delete", lambda: None)
    count_box.update(3, 10)
    assert count_box._dlg.labelText() == "Delete"             # a count of steps has no speed
    count_box.close()


def test_the_window_passes_the_copy_settings_to_the_run(tmp_path):
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui.main_window import MainWindow
    from tests.test_gui_commander import FakeDialogs
    app = QApplication.instance() or QApplication([])
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)), dialogs=FakeDialogs())
    try:
        assert win._exec_options().limit_bps is None and win._exec_options().on_error is None
        win.limit_actions[5].trigger()
        win.act_ask_error.setChecked(True)
        options = win._exec_options()
        assert options.limit_bps == 5 * 1024 * 1024 and options.on_error is not None
    finally:
        win.close()


# progress that does not leave the user wondering ---------------------------------------------------------------
class OtherDrive(MemoryFileSystem):
    """A rename that cannot cross to another drive, as between two disks: the move has to copy."""

    def rename(self, src, dst, *, overwrite=False):
        if self.basename(src).endswith(".dossier-part"):
            return super().rename(src, dst, overwrite=overwrite)
        raise OSError(errno.EXDEV, "cross-device link")


def test_a_move_to_another_drive_reports_bytes_so_speed_and_remaining_can_be_shown():
    from dossier.core.ops import plan_move
    fs = OtherDrive()
    fs.makedirs("mem://dst")
    fs.put("mem://src/big.bin", b"x" * 3_000_000)
    plan = plan_move(fs, ["mem://src/big.bin"], "mem://dst")
    assert plan.total_work == 3_000_000                               # bytes, not one unit
    seen = []
    res = execute(plan, fs, progress=lambda d, t: seen.append((d, t)))
    assert not res.failed and len(seen) > 2 and seen[-1][0] == seen[-1][1] == 3_000_000
    assert fs.stat("mem://dst/big.bin").size == 3_000_000


def test_on_item_names_each_step_in_order_and_counts_them():
    fs, plan = world()
    names = []
    execute(plan, fs, options=ExecOptions(workers=1, on_item=lambda op, n, count: names.append((op.src.rsplit("/", 1)[1], n, count))))
    assert names == [("a.txt", 1, 3), ("b.txt", 2, 3), ("c.txt", 3, 3)]      # the folder that is made is not a step


def test_the_box_says_the_item_the_sizes_done_and_remaining_the_speed_and_the_time_left():
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui import dialogs
    app = QApplication.instance() or QApplication([])
    box = dialogs.ProgressBox(None, "Copy", lambda: None)
    clock = Clock()
    box._meter = RateMeter(clock=clock)
    box.plan_bytes = 400 * 1024 * 1024
    box.detail = "holiday.mkv  (2 of 5)"
    total = 800 * 1024 * 1024                        # the bar's own total also counts reading the copy back
    for second in range(6):
        clock.t = 100.0 + second
        box.update(second * 40 * 1024 * 1024, total)
    text = box._dlg.labelText()
    lines = text.split(chr(10))
    assert lines[0] == "Copy" and lines[1] == "holiday.mkv  (2 of 5)"
    assert "100 MB of 400 MB" in lines[2] and "300 MB remaining" in lines[2]       # real bytes, not the bar's total
    assert "20 MB/s" in lines[3] and "15 s left" in lines[3]
    box.close()


def test_the_box_shows_the_item_even_when_the_job_is_not_bytes():
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from dossier.gui import dialogs
    app = QApplication.instance() or QApplication([])
    box = dialogs.ProgressBox(None, "Delete", lambda: None)
    box.detail = "old.log  (3 of 40)"
    box.update(3, 40)
    assert box._dlg.labelText() == "Delete" + chr(10) + "old.log  (3 of 40)"
    box.close()
