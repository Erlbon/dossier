"""Helpers shared by the window tests."""

def activate_window(win, timeout: int = 1500) -> None:
    """Make ``win`` the active window, so its shortcuts fire. Windows does not let a background process take the
    focus while the user is working in another program, so when the system will not do it the application is told
    which window is the active one."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    win.activateWindow()
    win.raise_()
    if not QTest.qWaitForWindowActive(win, timeout):
        QApplication.setActiveWindow(win)
        QApplication.processEvents()


def wait_planned(win, timeout: float = 10.0) -> None:
    """Wait until the plans the window was working out in the background are ready and have been handled."""
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end and win._plans:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
