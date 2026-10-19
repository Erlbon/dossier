"""The opt-in slowness log: stalls of the window over 200 ms, written with what it was doing."""
import os
import time

import pytest

from dossier.core.stallwatch import StallWatch


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def watch(tmp_path, **kw):
    clock = Clock()
    stacks = iter(kw.pop("stacks", None) or [["a.py:1 first"], ["a.py:2 second"], ["a.py:3 third"], ["a.py:4 fourth"]] * 3)
    w = StallWatch(str(tmp_path / "slow.log"), clock=clock, sampler=lambda: next(stacks),
                   now=lambda: "2026-10-19 12:00:00", **kw)
    return w, clock


def read(tmp_path):
    return open(tmp_path / "slow.log", encoding="utf-8").read()


def test_a_window_that_keeps_beating_writes_nothing(tmp_path):
    w, clock = watch(tmp_path)
    for _ in range(50):
        clock.t += 0.05
        w.beat()
        w.tick()
    assert not (tmp_path / "slow.log").exists()


def test_a_short_pause_under_the_threshold_is_not_a_stall(tmp_path):
    w, clock = watch(tmp_path)
    clock.t += 0.15
    w.tick()
    clock.t += 0.01
    w.beat()
    w.tick()
    assert not (tmp_path / "slow.log").exists()


def test_a_stall_is_written_when_the_window_answers_again_with_duration_and_samples(tmp_path):
    w, clock = watch(tmp_path, context=lambda: "last input: Shift+Down  |  marked: 3")
    clock.t += 0.25
    w.tick()                                           # over the threshold: first sample
    assert not (tmp_path / "slow.log").exists()        # nothing is written until it is over
    clock.t += 0.6
    w.tick()                                           # half a second later: second sample
    clock.t += 1.0
    w.beat()
    w.tick()
    text = read(tmp_path)
    assert text.startswith("2026-10-19 12:00:00  stalled 1.85 s  |  last input: Shift+Down  |  marked: 3")
    assert "0.2 s into the stall" in text and "a.py:1 first" in text and "a.py:2 second" in text
    w.tick()
    assert read(tmp_path) == text                      # one entry per stall


def test_two_stalls_are_two_entries_and_samples_are_limited(tmp_path):
    w, clock = watch(tmp_path)
    for _ in range(2):
        clock.t += 0.3
        w.tick()
        for _ in range(20):
            clock.t += 0.5
            w.tick()
        w.beat()
        w.tick()
        clock.t += 0.1
    text = read(tmp_path)
    assert text.count("stalled") == 2
    assert text.count("into the stall") <= 12


def test_a_failing_sampler_or_context_never_breaks_the_watch(tmp_path):
    def broken():
        raise RuntimeError("no")

    clock = Clock()
    w = StallWatch(str(tmp_path / "slow.log"), clock=clock, sampler=broken, context=broken, now=lambda: "T")
    clock.t += 0.3
    w.tick()
    clock.t += 0.2
    w.beat()
    w.tick()
    assert "stalled" in read(tmp_path) and "(no stack)" in read(tmp_path)


def test_an_unwritable_log_does_not_raise(tmp_path):
    (tmp_path / "slow.log").mkdir()                    # a folder where the file should be
    w, clock = watch(tmp_path)
    clock.t += 0.3
    w.tick()
    clock.t += 0.2
    w.beat()
    w.tick()


def test_the_file_is_capped_and_keeps_the_newest_entries(tmp_path):
    w, clock = watch(tmp_path, max_bytes=2000)
    for n in range(60):
        w._now = lambda n=n: f"entry {n}"
        clock.t += 0.3
        w.tick()
        clock.t += 0.2
        w.beat()
        w.tick()
        clock.t += 0.1
        w.beat()
    text = read(tmp_path)
    assert len(text) <= 2400 and "entry 59" in text and "entry 0 " not in text


def test_the_real_thread_catches_a_real_stall_and_names_the_function_that_was_running(tmp_path):
    w = StallWatch(str(tmp_path / "slow.log"), interval=0.02)
    w.start()
    try:
        def slow_thing_the_user_noticed():
            time.sleep(0.6)

        end = time.time() + 0.3
        while time.time() < end:                       # a healthy window beats
            w.beat()
            time.sleep(0.02)
        slow_thing_the_user_noticed()                  # then stops answering
        w.beat()
        time.sleep(0.2)
    finally:
        w.stop()
    text = read(tmp_path)
    assert "stalled 0." in text and "slow_thing_the_user_noticed" in text


# in the window ------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402

from tests.test_gui_commander import app, world  # noqa: E402,F401


def test_the_log_is_off_by_default_and_nothing_is_recorded_while_off(world):
    win, *_ = world
    assert not win.act_stall_log.isChecked() and getattr(win, "_stall_watch", None) is None
    assert not os.path.exists(win.stall_log_path)


def test_switching_it_on_and_off_starts_and_stops_the_watch_and_remembers_the_choice(world):
    win, *_ = world
    win.act_stall_log.setChecked(True)
    assert win._stall_watch is not None and str(win.settings.value("debug/stall_log")) == "true"
    win.act_stall_log.setChecked(False)
    assert win._stall_watch is None and str(win.settings.value("debug/stall_log")) == "false"


def test_a_stall_of_the_real_window_is_recorded_with_the_last_input_by_name_not_by_letter(world):
    win, *_ = world
    win.act_stall_log.setChecked(True)
    try:
        from PyQt6.QtWidgets import QApplication
        win._stall_watch.threshold = 0.1
        QApplication.sendEvent(win.left.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Q, Qt.KeyboardModifier.NoModifier, "q"))
        assert win._last_input.text == "a typed character"            # the letter itself is never kept
        QApplication.sendEvent(win.left.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down,
                                                         Qt.KeyboardModifier.ShiftModifier))
        assert win._last_input.text == "Shift+Down"
        end = time.time() + 0.3
        while time.time() < end:                                       # the window answers
            QApplication.processEvents()
            time.sleep(0.01)
        time.sleep(0.6)                                                # then the window's thread is blocked
        end = time.time() + 1.0
        while time.time() < end and not os.path.exists(win.stall_log_path):
            QApplication.processEvents()
            time.sleep(0.01)
        text = open(win.stall_log_path, encoding="utf-8").read()
        assert "stalled" in text and "last input: Shift+Down" in text and "marked: 0" in text
        assert "typed" not in text and "q" not in text.split("|")[1]
    finally:
        win.act_stall_log.setChecked(False)


def test_open_and_delete_from_settings(world):
    win, dialogs, *_ = world
    win.open_stall_log()
    assert dialogs.infos and "Nothing has been recorded" in dialogs.infos[-1][1]
    with open(win.stall_log_path, "w", encoding="utf-8") as f:
        f.write("entry")
    dialogs.confirm_answer = False
    win.delete_stall_log()
    assert os.path.exists(win.stall_log_path)                          # declined: kept
    dialogs.confirm_answer = True
    win.delete_stall_log()
    assert not os.path.exists(win.stall_log_path)
    win.delete_stall_log()
    assert "no slowness log" in win.status.text()
