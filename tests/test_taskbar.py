"""The queue's progress on the taskbar button: the mapping (core/taskbar.py) and the window feeding it, with a fake button."""
import pytest

from dossier.core import platform
from dossier.core.taskbar import ERROR, INDETERMINATE, NONE, NORMAL, PAUSED, STEPS, TaskbarProgress, taskbar_look


def look(jobs=0, planning=False, done=0, total=0, paused=False, error=False):
    return taskbar_look(jobs=jobs, planning=planning, done=done, total=total, paused=paused, error=error)


def test_an_empty_queue_shows_nothing():
    assert look() == (NONE, 0, 0)
    assert look(paused=True) == (NONE, 0, 0)               # the pause switch alone, with nothing queued, is not shown


def test_planning_and_a_job_without_a_report_yet_move_without_a_fill():
    assert look(planning=True) == (INDETERMINATE, 0, 0)
    assert look(jobs=1) == (INDETERMINATE, 0, 0)


def test_a_running_job_fills_in_thousandths_whatever_its_unit():
    assert look(jobs=1, done=250, total=1000) == (NORMAL, 250, STEPS)
    assert look(jobs=2, done=3 * 2**30, total=12 * 2**30) == (NORMAL, 250, STEPS)     # bytes of a large copy
    assert look(jobs=1, done=7, total=5) == (NORMAL, STEPS, STEPS)                     # never past full
    assert look(jobs=1, planning=True, done=1, total=2) == (NORMAL, 500, STEPS)         # a plan behind a running copy: the copy shows


def test_paused_is_yellow_and_red_wins_over_everything():
    assert look(jobs=1, done=1, total=4, paused=True) == (PAUSED, 250, STEPS)
    assert look(jobs=1, paused=True) == (PAUSED, STEPS, STEPS)                         # no progress yet: a full bar, so the colour shows
    assert look(jobs=1, done=1, total=4, paused=True, error=True) == (ERROR, 250, STEPS)
    assert look(error=True) == (ERROR, STEPS, STEPS)                                   # the report of a failed job, the queue already empty


class FakeButton:
    def __init__(self):
        self.calls = []

    def set(self, state, done, total):
        self.calls.append((state, done, total))


def test_the_button_is_only_called_when_the_look_changes():
    button = FakeButton()
    bar = TaskbarProgress(button)
    bar.show(jobs=0, planning=False, done=0, total=0, paused=False, error=False)
    assert button.calls == []                                                          # it starts empty
    bar.show(jobs=1, planning=False, done=0, total=0, paused=False, error=False)
    for done in (0, 1, 2, 5000, 5001):
        bar.show(jobs=1, planning=False, done=done, total=10_000_000, paused=False, error=False)
    assert button.calls == [(INDETERMINATE, 0, 0), (NORMAL, 0, STEPS)]                 # 0..5001 of ten million is still 0 thousandths
    bar.show(jobs=1, planning=False, done=10_000, total=10_000_000, paused=False, error=False)
    assert button.calls[-1] == (NORMAL, 1, STEPS)
    bar.show(jobs=0, planning=False, done=0, total=0, paused=False, error=False)
    assert button.calls[-1] == (NONE, 0, 0) and bar.shown == (NONE, 0, 0)


def test_without_a_button_it_still_keeps_track():
    bar = TaskbarProgress(None)
    bar.show(jobs=1, planning=False, done=1, total=2, paused=False, error=False)
    assert bar.shown == (NORMAL, 500, STEPS)


def test_the_platform_gives_a_button_on_windows_only():
    button = platform.taskbar_button(lambda: 0)
    assert (button is not None) == platform.IS_WINDOWS


@pytest.mark.skipif(not platform.IS_WINDOWS, reason="the shell's taskbar object is Windows only")
def test_the_windows_button_turns_quiet_instead_of_raising_when_the_system_refuses():
    button = platform.taskbar_button(lambda: "not a window")
    button.set(NORMAL, 1, 2)                                                           # the hwnd cannot be read: no exception
    button.set(NONE, 0, 0)
    assert button._broken


# the window ---------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from dossier.core.worker import Job, JobState  # noqa: E402
from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def fake_button(win):
    button = FakeButton()
    win.taskbar = TaskbarProgress(button)
    return button


def copy_first(win, left, n=3):
    for i in range(n):
        (left / f"f{i}.txt").write_text(str(i) * 50)
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.copy()
    wait_planned(win)


def test_a_paused_copy_is_yellow_then_fills_and_clears_when_the_queue_is_empty(world):
    win, _dialogs, left, right, _t = world
    button = fake_button(win)
    win.paused = False
    win.toggle_pause()
    copy_first(win, left)
    assert win.busy and button.calls[-1] == (PAUSED, STEPS, STEPS)
    win.toggle_pause()
    pump(win, lambda: not win._jobs, timeout=10)
    states = [c[0] for c in button.calls]
    assert NORMAL in states and states[-1] == NONE
    assert (NORMAL, STEPS, STEPS) in button.calls                                      # it reached full before clearing
    assert (right / "f0.txt").exists()


def test_planning_shows_a_moving_bar(world):
    win, _dialogs, _left, _right, _t = world
    button = fake_button(win)
    win._plans.append(object())                                                        # a plan being worked out
    win._update_taskbar()
    assert button.calls[-1] == (INDETERMINATE, 0, 0)
    win._plans.clear()
    win._update_taskbar()
    assert button.calls[-1] == (NONE, 0, 0)


def test_the_report_of_a_failed_copy_is_read_with_a_red_button(world):
    win, dialogs, left, right, _t = world
    button = fake_button(win)
    seen = []
    info = dialogs.info

    def info_seeing_the_button(title, text):
        seen.append(win.taskbar.shown[0])
        info(title, text)

    dialogs.info = info_seeing_the_button
    job = Job("Copy")
    job.state, job.error = JobState.FAILED, OSError("disk full")
    win._report_with_red_button(job, None)
    assert seen == [ERROR] and button.calls == [(ERROR, STEPS, STEPS), (NONE, 0, 0)]


def test_asking_about_a_file_that_cannot_be_copied_turns_the_button_red(world):
    win, dialogs, _left, _right, _t = world
    button = fake_button(win)
    seen = []
    dialogs.ask_error = lambda text: seen.append(win.taskbar.shown[0]) or "skip"
    win.dispatcher = lambda fn: fn()                                                   # the question is asked right here
    win.act_ask_error.setChecked(True)
    on_error = win._exec_options().on_error
    assert on_error(type("Op", (), {"src": str(_left / "a.txt"), "dst": ""})(), "Access is denied") == "skip"
    assert seen == [ERROR] and button.calls[-1] == (NONE, 0, 0)
