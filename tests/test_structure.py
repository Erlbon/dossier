"""The shared pieces are really shared (one size formatter, one stat helper, one background-job helper), and the window
stays split along its seams."""
import os

import pytest

from dossier.core import ops, sizefmt, undo_log, vfs
from dossier.core.sizefmt import human_size


def test_sizes_are_formatted_in_one_place_in_both_styles():
    assert human_size(0) == "0 B" and human_size(1023) == "1023 B"
    assert human_size(2048) == "2.0 K" and human_size(19_000_000) == "18.1 M"
    assert human_size(2048, long=True) == "2.0 KB" and human_size(5 * 1024 ** 3, long=True) == "5.0 GB"
    assert human_size(12 * 1024 ** 2, long=True, whole_from=10) == "12 MB" and human_size(9.5 * 1024 ** 2, long=True, whole_from=10) == "9.5 MB"
    assert human_size(3 * 1024 ** 5) == "3072.0 T"                                   # the largest unit is the last one


def test_the_callers_use_the_shared_formatter_and_the_shared_stat_helper():
    pytest.importorskip("PyQt6")
    from dossier.gui import dialogs, models
    assert models.human_size is sizefmt.human_size
    assert dialogs._size(12 * 1024 ** 2) == sizefmt.human_size(12 * 1024 ** 2, long=True, whole_from=10) == "12 MB"
    assert ops._stat is vfs.stat_or_none and undo_log._stat is vfs.stat_or_none


def test_stat_or_none_hides_only_a_missing_item(tmp_path):
    fs = vfs.LocalFileSystem()
    (tmp_path / "f").write_text("x")
    assert vfs.stat_or_none(fs, str(tmp_path / "f")).size == 1
    assert vfs.stat_or_none(fs, str(tmp_path / "missing")) is None
    assert vfs.stat_or_none(fs, str(tmp_path / "f" / "inside")) is None            # a file used as a folder: not there either


# the background helper ---------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
import time  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.worker import JobRunner  # noqa: E402
from dossier.gui.background import run_in_background  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.dialogs = FakeDialogs()
        self.said = []

    def _say(self, text):
        self.said.append(text)


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


@pytest.fixture
def runner():
    r = JobRunner()
    yield r
    r.shutdown(wait=True)


def test_a_result_is_handed_over_and_the_job_leaves_the_list(runner):
    import threading
    window, tracked, got = FakeWindow(), [], []
    gate = threading.Event()
    job = run_in_background(window, runner, "Work", lambda progress, cancel: (gate.wait(5), 41 + 1)[1],
                            on_result=got.append, tracked=tracked)
    assert tracked == [job]                                  # listed while it runs
    gate.set()
    wait_for(lambda: got)
    assert got == [42] and tracked == []


def test_a_job_that_ends_before_it_is_listed_is_never_left_in_the_list(runner):
    window, tracked, got = FakeWindow(), [], []
    for _ in range(20):
        run_in_background(window, runner, "Work", lambda progress, cancel: 1, on_result=got.append, tracked=tracked)
    wait_for(lambda: len(got) == 20)
    assert tracked == []


def test_the_box_appears_on_the_first_report_with_the_detail_and_closes_at_the_end(runner):
    window, got = FakeWindow(), []

    def work(progress, cancel):
        progress(1, 4)
        time.sleep(0.05)
        progress(4, 4)
        return "ok"

    run_in_background(window, runner, "Work", work, on_result=got.append, tracked=[], detail=lambda: "the detail",
                      plan_bytes=1234, indeterminate=True)
    wait_for(lambda: got)
    (box,) = window.dialogs.progress_boxes
    assert box.title == "Work" and box.detail == "the detail" and box.plan_bytes == 1234 and box.closed


def test_a_failure_is_shown_and_a_cancel_is_said_and_neither_calls_on_result(runner):
    window, got = FakeWindow(), []

    def boom(progress, cancel):
        raise RuntimeError("it broke")

    run_in_background(window, runner, "Work", boom, on_result=got.append, tracked=[], failed_title="Failed work")
    wait_for(lambda: window.dialogs.infos)
    assert window.dialogs.infos[-1] == ("Failed work", "it broke") and got == []

    started = []

    def waits(progress, cancel):
        started.append(1)
        while not cancel.cancelled:
            time.sleep(0.005)
        return "partial"

    job = run_in_background(window, runner, "Slow", waits, on_result=got.append, tracked=[])
    wait_for(lambda: started)
    job.cancel()
    wait_for(lambda: "Cancelled" in window.said)
    assert got == []


def test_partial_results_can_be_handed_over_after_a_cancel(runner):
    window, got, started = FakeWindow(), [], []

    def waits(progress, cancel):
        started.append(1)
        while not cancel.cancelled:
            time.sleep(0.005)
        return "partial"

    job = run_in_background(window, runner, "Slow", waits, on_result=got.append, tracked=[], partial_on_cancel=True)
    wait_for(lambda: started)
    job.cancel()
    wait_for(lambda: got)
    assert got == ["partial"] and window.said == []


def test_the_window_is_split_along_its_seams_and_stays_small():
    from dossier.gui.main_window import MainWindow
    names = [c.__name__ for c in MainWindow.__mro__]
    for mixin in ("OperationQueueMixin", "StallLogMixin", "GoingPlacesMixin", "FolderSizesMixin", "UnpackMixin"):
        assert mixin in names
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "dossier", "gui", "main_window.py"), encoding="utf-8") as f:
        assert len(f.readlines()) < 1300                      # it was 1580 lines before the queue, the log and the rest moved out
