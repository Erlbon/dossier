"""Worker model and selection bookkeeping (plan step 6)."""
import os
import shutil
import threading
import time

import pytest

from dossier.core.ops import Resolution, execute, plan_copy, plan_delete, plan_move, selection_effects
from dossier.core.progress import CancelToken
from dossier.core.selection import SelectionStore
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem
from dossier.core.worker import JobRunner, JobState, run_plan_job

fs = LocalFileSystem()
MAIN = threading.get_ident()


class Pump:
    """A dispatcher that only queues; the test drains it on the main thread, like a GUI event loop."""

    def __init__(self):
        self.queue = []

    def __call__(self, fn):
        self.queue.append(fn)

    def drain(self):
        while self.queue:
            self.queue.pop(0)()


def wait_done(job, pump, timeout=5):
    assert job.wait(timeout), "job did not finish"
    pump.drain()


# JobRunner -----------------------------------------------------------------------------------
def test_job_runs_off_thread_and_callbacks_arrive_on_the_dispatcher_thread():
    pump = Pump()
    runner = JobRunner(pump)
    seen = {}

    def work(progress, cancel):
        seen["worker"] = threading.get_ident()
        progress(1, 1)
        return 42

    job = runner.submit("t", work,
                        on_progress=lambda d, t: seen.setdefault("progress", threading.get_ident()),
                        on_done=lambda j: seen.setdefault("done", (threading.get_ident(), j.state, j.result)))
    wait_done(job, pump)
    runner.shutdown()
    assert seen["worker"] != MAIN
    assert seen["progress"] == MAIN
    assert seen["done"] == (MAIN, JobState.DONE, 42)


def test_progress_is_throttled_but_the_last_value_always_arrives():
    pump = Pump()
    runner = JobRunner(pump, progress_interval=10.0)
    got = []

    def work(progress, cancel):
        for i in range(1, 1001):
            progress(i, 1000)

    job = runner.submit("t", work, on_progress=lambda d, t: got.append(d))
    wait_done(job, pump)
    runner.shutdown()
    assert got[-1] == 1000 and len(got) < 20


def test_cancel_marks_the_job_cancelled():
    pump = Pump()
    runner = JobRunner(pump)
    started = threading.Event()

    def work(progress, cancel):
        started.set()
        while not cancel.cancelled:
            time.sleep(0.005)
        return "partial"

    job = runner.submit("t", work)
    assert started.wait(5)
    job.cancel()
    wait_done(job, pump)
    runner.shutdown()
    assert job.state is JobState.CANCELLED and job.result == "partial"


def test_failure_is_reported_not_raised():
    pump = Pump()
    runner = JobRunner(pump)
    done = []

    def work(progress, cancel):
        raise ValueError("boom")

    job = runner.submit("t", work, on_done=done.append)
    wait_done(job, pump)
    runner.shutdown()
    assert job.state is JobState.FAILED and isinstance(job.error, ValueError) and done == [job]


def test_a_failing_callback_does_not_break_the_runner():
    pump = Pump()
    runner = JobRunner(pump)

    def bad(job):
        raise RuntimeError("callback bug")

    first = runner.submit("a", lambda p, c: 1, on_done=bad)
    second = runner.submit("b", lambda p, c: 2)
    assert second.wait(5) and first.wait(5)
    pump.drain()   # must not raise
    runner.shutdown()
    assert second.result == 2


# selection with a dispatcher --------------------------------------------------------------------------
def test_dispatched_selection_coalesces_notifications():
    pump = Pump()
    s = SelectionStore(dispatch=pump)
    calls = []
    s.subscribe(lambda st: calls.append(len(st)))
    s.add(["/a"])
    s.add(["/b"])
    s.add(["/c"])
    assert calls == []            # nothing before the event loop runs
    pump.drain()
    assert calls == [3]


def test_selection_is_safe_to_change_from_many_threads():
    s = SelectionStore()

    def add(n):
        for i in range(1000):
            s.add([f"/t{n}/{i}"])

    threads = [threading.Thread(target=add, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(s) == 4000


def test_paths_order_is_stable_after_changes():
    s = SelectionStore()
    s.add(["/b", "/a"])
    first = s.paths()
    s.add(["/c"])
    assert s.paths() == sorted(first + ["/c"], key=lambda p: os.path.normcase(os.path.normpath(p)))
    first.append("/mutating the returned list is harmless")
    assert "/mutating the returned list is harmless" not in s.paths()


# selection follows the files -------------------------------------------------------------------------
def test_remap_follows_a_moved_item_and_things_inside_a_moved_folder(tmp_path):
    s = SelectionStore()
    old = str(tmp_path / "d")
    s.add([old, os.path.join(old, "in.txt"), str(tmp_path / "other")])
    s.remap({old: str(tmp_path / "x" / "d")})
    assert sorted(s.paths()) == sorted([str(tmp_path / "x" / "d"), str(tmp_path / "x" / "d" / "in.txt"),
                                        str(tmp_path / "other")])


def test_remove_missing_drops_vanished_items_only(tmp_path):
    (tmp_path / "here").write_text("x")
    s = SelectionStore()
    s.add([str(tmp_path / "here"), str(tmp_path / "gone"), "zip://a.zip/x"])
    dropped = s.remove_missing(fs)
    assert dropped == [str(tmp_path / "gone")]
    assert len(s) == 2            # virtual items are not checked against the local disk


# whole flow: plan -> job -> selection and undo updated on the dispatcher thread ---------------------
def test_run_plan_job_updates_selection_and_undo_on_the_gui_thread(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    (tmp_path / "src" / "a.txt").write_text("A")
    src = str(tmp_path / "src" / "a.txt")
    pump = Pump()
    runner = JobRunner(pump)
    sel = SelectionStore()
    sel.add([src])
    log = UndoLog()
    seen = {}
    plan = plan_move(fs, [src], str(tmp_path / "dst"))
    job = run_plan_job(runner, plan, fs, selection=sel, undo_log=log,
                       on_done=lambda j: seen.setdefault("thread", threading.get_ident()))
    wait_done(job, pump)
    runner.shutdown()
    assert seen["thread"] == MAIN
    assert sel.paths() == [str(tmp_path / "dst" / "a.txt")]
    assert log.labels() == ["Move"]
    log.undo_last(fs)
    assert (tmp_path / "src" / "a.txt").exists()


def test_selection_effects_for_delete_and_undo_report(tmp_path):
    (tmp_path / "a").write_text("A")
    (tmp_path / "bin").mkdir()

    def trasher(p):
        shutil.move(p, str(tmp_path / "bin"))

    res = execute(plan_delete(fs, [str(tmp_path / "a")]), fs, trasher=trasher)
    effects = selection_effects(res)
    assert effects.removed == [str(tmp_path / "a")] and effects.moved == {}

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "f").write_text("F")
    (tmp_path / "dst").mkdir()
    log = UndoLog()
    execute(plan_move(fs, [str(tmp_path / "src" / "f")], str(tmp_path / "dst")), fs, undo_log=log)
    report = log.undo_last(fs)
    assert report.moved == {str(tmp_path / "dst" / "f"): str(tmp_path / "src" / "f")}


def test_run_plan_job_cancel_still_records_what_was_done(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    for n in "abc":
        (tmp_path / "src" / n).write_text(n * 100)
    pump = Pump()
    runner = JobRunner(pump, progress_interval=0)
    log = UndoLog()
    plan = plan_copy(fs, [str(tmp_path / "src" / n) for n in "abc"], str(tmp_path / "dst"))
    job_box = []

    def progress(done, total):
        if done >= 100 and job_box:
            job_box[0].cancel()

    job = run_plan_job(runner, plan, fs, undo_log=log, on_progress=progress)
    job_box.append(job)
    wait_done(job, pump)
    runner.shutdown()
    assert job.state in (JobState.CANCELLED, JobState.DONE)
    if job.state is JobState.CANCELLED:
        assert len(log) == 1


# Qt bridge ----------------------------------------------------------------------------------------------
def test_qt_dispatcher_runs_callables_on_the_main_thread():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

    from dossier.gui.qt_bridge import QtDispatcher

    app = QCoreApplication.instance() or QCoreApplication([])
    dispatcher = QtDispatcher()
    got = []
    loop = QEventLoop()

    def from_worker():
        dispatcher(lambda: (got.append(threading.get_ident()), loop.quit()))

    t = threading.Thread(target=from_worker)
    t.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    t.join()
    assert got == [MAIN]
    assert app is not None
