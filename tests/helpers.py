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
    """Wait until the plans the window was working out in the background are ready and have been handled. A plan still not ready
    after ``timeout`` fails here, where it says so, not later in a confusing assertion."""
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end and win._plans:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    if win._plans:
        raise AssertionError(f"a plan was still being worked out after {timeout} s")


def settle(win, timeout: float = 10.0) -> None:
    """Wait until the window's background work for a command is done (opening a file, working out a plan): the window reads the
    disk on threads and acts when the answer comes, so a test looks only after that."""
    if hasattr(win, "_size_jobs"):                  # a viewer window has no background work of its own
        wait_for(lambda: not win._size_jobs and not win._plans, timeout)
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()


def wait_for(condition, timeout: float = 10.0) -> None:
    """Handle events until ``condition()`` is true: a wait for what a thread delivers, never a guess of how long it takes."""
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError(f"waited {timeout} s and it did not happen")


def when_modal(owner, act, timeout_ms: int = 10000) -> None:
    """Call ``act(dialog)`` once a modal dialog is open (a test that goes through a real ``exec()``). The timer belongs to ``owner``,
    so if the dialog never opens it dies with the owner instead of firing in some later test, as a bare ``singleShot`` would."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    timer = QTimer(owner)
    left = {"ticks": timeout_ms // 20}

    def tick() -> None:
        box = QApplication.activeModalWidget()
        left["ticks"] -= 1
        if box is not None or left["ticks"] <= 0:
            timer.stop()
            timer.deleteLater()
            if box is not None:
                act(box)
    timer.timeout.connect(tick)
    timer.start(20)
