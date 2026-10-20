"""Start Dossier: ``python -m dossier`` or the ``dossier`` command."""
from __future__ import annotations

import os
import sys
import threading
import time


def leave(code: int, grace: float = 2.0) -> int:
    """The exit code to return after the window is closed. A background thread stuck in a call to a dead network share
    cannot be stopped, and Python waits for such threads at exit: give them a moment, then end the process (the settings
    were saved when the window closed)."""
    def stuck() -> bool:
        return any(t.is_alive() and not t.daemon and t is not threading.main_thread() for t in threading.enumerate())

    end = time.monotonic() + grace
    while stuck() and time.monotonic() < end:
        time.sleep(0.05)
    if stuck():
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code


def main(argv=None) -> int:
    from PyQt6.QtWidgets import QApplication

    from ..core.platform import set_app_id
    from .appicon import app_icon
    from .main_window import MainWindow

    set_app_id("Erlbon.Dossier")

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())                 # every window of the program, the viewer and notepad too
    window = MainWindow()
    window.show()
    return leave(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
