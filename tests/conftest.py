"""Shared test housekeeping.

A window that a test closed is only hidden: Qt keeps it, its menus, its timers and its signal connections for as long as the program
runs, and every later ``processEvents`` has to serve all of them. After a few hundred tests a window that opened in a second took
fifteen. So after every test the windows and menus that are still there are really deleted.

Every test also gets an assistant folder of its own: a window started by a test must never read (or write) the settings, the state and the
requests of the assistant feature on the computer the tests run on.
"""
import sys

import pytest


@pytest.fixture(autouse=True)
def _own_assistant_folder(tmp_path, monkeypatch):
    from dossier.assistant import paths
    monkeypatch.setenv(paths.ENV, str(tmp_path / "_assistant"))


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
