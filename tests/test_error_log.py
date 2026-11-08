"""The opt-in error log (core/error_log.py, gui/error_log.py): off writes nothing, on writes failed copies and errors in the program."""
import logging
import sys
import threading

import pytest

from dossier.core.error_log import ErrorLog


def test_off_writes_nothing(tmp_path):
    log = ErrorLog(str(tmp_path / "errors.log"))
    log.write("Copy: failed", "  a -> b: gone")
    logging.getLogger("dossier.core.worker").error("job callback failed")
    assert not (tmp_path / "errors.log").exists()


def test_on_writes_entries_and_the_programs_own_errors(tmp_path):
    path = tmp_path / "errors.log"
    log = ErrorLog(str(path), "Dossier test")
    log.start()
    try:
        log.write("Copy 2 files: 1 of 2 steps failed", r"  C:\a.txt -> \\host\share\a.txt: the network name is gone")
        try:
            raise ValueError("broken callback")
        except ValueError:
            logging.getLogger("dossier.core.worker").exception("job callback failed")
    finally:
        log.stop()
    text = path.read_text(encoding="utf-8")
    assert "started: pid" in text and "Dossier test" in text
    assert r"\\host\share\a.txt: the network name is gone" in text
    assert "job callback failed" in text and "ValueError: broken callback" in text


def test_an_uncaught_error_is_written_and_said_and_the_hooks_go_back(tmp_path):
    path = tmp_path / "errors.log"
    said = []
    before = (sys.excepthook, threading.excepthook)
    log = ErrorLog(str(path), on_error=said.append)
    log.start()
    try:
        try:
            raise RuntimeError("in a slot")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        thread = threading.Thread(target=lambda: 1 / 0)
        thread.start()
        thread.join()
    finally:
        log.stop()
    assert (sys.excepthook, threading.excepthook) == before
    text = path.read_text(encoding="utf-8")
    assert "RuntimeError: in a slot" in text and "ZeroDivisionError" in text
    assert said[0] == "RuntimeError: in a slot"


def test_delete_works_while_it_is_on(tmp_path):
    """faulthandler holds the file open while the log is on: Windows will not delete an open file unless it lets go first."""
    path = tmp_path / "errors.log"
    log = ErrorLog(str(path))
    log.start()
    try:
        log.write("one")
        log.delete()
        assert not path.exists()
        log.write("two")
        assert "two" in path.read_text(encoding="utf-8")
    finally:
        log.stop()


# the window ----------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from tests.test_gui_commander import FakeDialogs, app, pump, world  # noqa: E402,F401

from dossier.core.ops import Kind, Op, Plan  # noqa: E402


def test_a_failed_copy_is_in_the_log_with_where_from_where_to_and_why(world):
    win, dialogs, left, right, tmp = world
    win.act_error_log.setChecked(True)
    gone, dst = left / "gone.txt", right / "gone.txt"
    win._run(Plan("Copy gone.txt", (Op(Kind.COPY, str(gone), str(dst), size=1),)))
    pump(win, lambda: dialogs.infos)
    text = (tmp / "errors.log").read_text(encoding="utf-8")
    assert "Copy gone.txt: 1 of 1 steps failed" in text
    assert f"{gone} -> {dst}: " in text
    assert dialogs.infos[-1][0] == "Some items failed"         # the owner is still told at once, as before


def test_off_by_default_and_the_switch_is_remembered(world):
    win, dialogs, left, right, tmp = world
    assert not win.act_error_log.isChecked() and not win.error_log.on
    win._run(Plan("Copy gone.txt", (Op(Kind.COPY, str(left / "gone.txt"), str(right / "gone.txt"), size=1),)))
    pump(win, lambda: dialogs.infos)
    assert not (tmp / "errors.log").exists()
    win.act_error_log.setChecked(True)
    assert str(win.settings.value("debug/error_log")) == "true" and win.error_log.on


def test_open_and_delete_from_the_help_menu(world):
    win, dialogs, _l, _r, tmp = world
    win.open_error_log()
    assert dialogs.infos[-1][0] == "Error Log" and "Nothing has been recorded" in dialogs.infos[-1][1]
    win.act_error_log.setChecked(True)
    win.error_log.write("something")
    win.delete_error_log()
    assert not (tmp / "errors.log").exists() and "Error Log deleted" in win.status.text()
