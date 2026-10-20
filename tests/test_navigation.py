"""Non-blocking navigation: a slow folder never freezes the window (plan step H0b)."""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.vfs import LocalFileSystem  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402


class SlowFileSystem(LocalFileSystem):
    """The disk, except that listing the folders named in ``slow`` takes ``delay`` seconds (or fails after it)."""

    def __init__(self, slow=(), delay=0.8, fail=()):
        self.slow, self.delay, self.fail = set(slow), delay, set(fail)
        self.answered = threading.Event()        # set when a slow listing has given its answer: tests wait for this, not a clock

    def list(self, path):
        name = os.path.basename(path)
        try:
            if name in self.slow or name in self.fail:
                time.sleep(self.delay)
                if name in self.fail:
                    raise PermissionError(13, "Access is denied", path)
            return super().list(path)
        finally:
            if name in self.slow or name in self.fail:
                self.answered.set()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make(app, tmp_path, **kw):
    for d in ("fast", "slow", "dead", "other"):
        (tmp_path / d).mkdir()
    (tmp_path / "slow" / "inside.txt").write_text("x")
    fs = SlowFileSystem(**kw)
    win = MainWindow(fs=fs, settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path / "fast"), str(tmp_path / "other")),
                     dialogs=FakeDialogs())
    win.show()
    win.slow_fs = fs
    return win


def pump(cond, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_a_fast_folder_is_shown_at_once(app, tmp_path):
    win = make(app, tmp_path, slow=["slow"])
    try:
        assert win.left.set_folder(str(tmp_path / "other")) is True
        assert win.left.path == str(tmp_path / "other") and not win.left.loading
    finally:
        win.close()


def test_a_slow_folder_leaves_the_window_alive_and_appears_when_ready(app, tmp_path):
    win = make(app, tmp_path, slow=["slow"], delay=0.8)
    try:
        messages = []
        win.left.message.connect(messages.append)
        started = time.time()
        assert win.left.set_folder(str(tmp_path / "slow")) is True
        assert time.time() - started < 0.5                                # it did not wait for the answer
        assert win.left.path == str(tmp_path / "fast")                    # the old folder is still shown
        assert win.left.loading and win.left.pending_path == str(tmp_path / "slow")
        assert any("Opening" in m and "Esc" in m for m in messages)
        QApplication.processEvents()                                      # the window keeps handling events
        pump(lambda: not win.left.loading)
        assert win.left.path == str(tmp_path / "slow") and win.left.model.row_of("inside.txt") >= 0
    finally:
        win.close()


def test_going_somewhere_else_cancels_the_slow_one(app, tmp_path):
    win = make(app, tmp_path, slow=["slow"], delay=0.6)
    try:
        win.left.set_folder(str(tmp_path / "slow"))
        assert win.left.loading
        win.left.set_folder(str(tmp_path / "other"))
        assert win.left.path == str(tmp_path / "other") and not win.left.loading
        assert win.slow_fs.answered.wait(15)                              # the slow listing has now answered
        for _ in range(20):
            QApplication.processEvents()
            time.sleep(0.01)
        assert win.left.path == str(tmp_path / "other")                  # the late answer was ignored
    finally:
        win.close()


def test_escape_cancels_the_wait_and_the_late_answer_changes_nothing(app, tmp_path):
    win = make(app, tmp_path, slow=["slow"], delay=0.6)
    try:
        messages = []
        win.left.message.connect(messages.append)
        win.left.set_folder(str(tmp_path / "slow"))
        QTest.keyClick(win.left.table, Qt.Key.Key_Escape)
        assert not win.left.loading and "Cancelled" in messages
        assert win.slow_fs.answered.wait(15)
        for _ in range(20):
            QApplication.processEvents()
            time.sleep(0.01)
        assert win.left.path == str(tmp_path / "fast")
    finally:
        win.close()


def test_a_folder_that_fails_after_a_wait_is_reported_and_the_old_one_stays(app, tmp_path):
    win = make(app, tmp_path, fail=["dead"], delay=0.5)
    try:
        messages = []
        win.left.message.connect(messages.append)
        assert win.left.set_folder(str(tmp_path / "dead")) is True            # pending, not yet known to fail
        pump(lambda: not win.left.loading)
        assert win.left.path == str(tmp_path / "fast")
        assert any("Cannot open" in m and "denied" in m.lower() for m in messages)
    finally:
        win.close()


def test_a_folder_that_fails_at_once_returns_false_as_before(app, tmp_path):
    win = make(app, tmp_path)
    try:
        assert win.left.set_folder(str(tmp_path / "does-not-exist")) is False
        assert win.left.path == str(tmp_path / "fast")
    finally:
        win.close()


def test_enter_on_a_slow_folder_does_not_freeze_and_a_tab_can_still_be_used(app, tmp_path):
    win = make(app, tmp_path, slow=["slow"], delay=0.7)
    try:
        win.left.set_folder(str(tmp_path))
        win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("slow"), 0))
        QTest.keyClick(win.left.table, Qt.Key.Key_Return)
        assert win.left.loading
        win.left.new_tab(str(tmp_path / "other"))                             # other things keep working meanwhile
        assert win.left.path == str(tmp_path / "other") and not win.left.loading
    finally:
        win.close()
