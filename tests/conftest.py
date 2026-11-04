"""Shared test housekeeping.

A window that a test closed is only hidden: Qt keeps it, its menus, its timers and its signal connections for as long as the program
runs, and every later ``processEvents`` has to serve all of them. After a few hundred tests a window that opened in a second took
fifteen. So after every test the windows and menus that are still there are really deleted.

Every test also gets an assistant folder of its own: a window started by a test must never read (or write) the settings, the state and the
requests of the assistant feature on the computer the tests run on.
"""
import os
import sys
import traceback

import pytest

# One platform for every run: a single test file run alone used the real desktop (and took the focus) while a full run was offscreen,
# only because some test module that happened to be collected first set it.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _callback_errors_fail_the_test():
    """An exception in a Qt callback (a timer, a slot) reaches ``sys.excepthook``; with Python's own hook there PyQt aborts the whole
    process (exit 0xC0000409, no trace), which once ended a full run in the middle. Here such an exception is kept and fails the test
    it happened in."""
    caught = []
    before = sys.excepthook
    sys.excepthook = lambda kind, value, tb: caught.append("".join(traceback.format_exception(kind, value, tb)))
    yield
    sys.excepthook = before
    if caught:
        pytest.fail("an exception in a Qt callback:" + chr(10) + caught[0], pytrace=False)


@pytest.fixture(autouse=True)
def _own_assistant_folder(tmp_path, monkeypatch):
    from dossier.assistant import paths
    monkeypatch.setenv(paths.ENV, str(tmp_path / "_assistant"))


@pytest.fixture(autouse=True)
def _auto_refresh_off_unless_a_test_asks(monkeypatch):
    """The panels would refresh themselves while a test is changing files under them: off here, and a test of auto refresh switches it on."""
    try:
        from dossier.gui import auto_refresh
    except ImportError:                          # no Qt in this environment
        return
    monkeypatch.setattr(auto_refresh, "DEFAULT_LOCAL", False)


@pytest.fixture(autouse=True)
def _patient_listings(request, monkeypatch):
    """A panel waits ``NAV_BUDGET`` (0.15 s) for a folder, then shows the old one and goes on listing it on a thread. Most tests read
    the panel straight after opening a folder; on a busy machine (a virus scanner, a full test run) a listing took longer now and
    then, the test read the old rows, and about one full run in four failed. So tests wait up to 10 s here; tests of slow folders
    are marked ``short_nav_budget`` and keep the real budget."""
    if request.node.get_closest_marker("short_nav_budget"):
        return
    try:
        from dossier.gui import panel
    except ImportError:                          # no Qt in this environment
        return
    monkeypatch.setattr(panel, "NAV_BUDGET", 10.0)


@pytest.fixture(autouse=True)
def _delete_leftover_windows():
    yield
    widgets = sys.modules.get("PyQt6.QtWidgets")
    core = sys.modules.get("PyQt6.QtCore")
    if widgets is None or core is None:
        return                                   # a test that never used Qt
    app = widgets.QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:                     # already deleted by its owner
            pass
    app.processEvents()
    app.sendPostedEvents(None, core.QEvent.Type.DeferredDelete.value)
    app.processEvents()


@pytest.fixture(autouse=True)
def _no_real_tailscale(monkeypatch):
    """A test window never runs the Tailscale program of the computer the tests run on (and never lists its devices)."""
    from dossier.core import tailnet
    monkeypatch.setattr(tailnet, "find_tailscale", lambda: "")
