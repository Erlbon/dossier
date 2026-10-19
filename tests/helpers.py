"""Helpers shared by the window tests."""
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication


def activate_window(win, timeout: int = 1500) -> None:
    """Make ``win`` the active window, so its shortcuts fire. Windows does not let a background process take the
    focus while the user is working in another program, so when the system will not do it the application is told
    which window is the active one."""
    win.activateWindow()
    win.raise_()
    if not QTest.qWaitForWindowActive(win, timeout):
        QApplication.setActiveWindow(win)
        QApplication.processEvents()
