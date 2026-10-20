"""Shared test housekeeping.

A window that a test closed is only hidden: Qt keeps it, its menus, its timers and its signal connections for as long as the program
runs, and every later ``processEvents`` has to serve all of them. After a few hundred tests a window that opened in a second took
fifteen. So after every test the windows and menus that are still there are really deleted.
"""
import sys

import pytest


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
