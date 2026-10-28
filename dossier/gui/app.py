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
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if args[:1] == ["--askpass"]:                   # ssh asking for a password: answered at once, with no window and no checks
        from ..core.askpass import main as askpass_main
        return askpass_main(args[1:])
    from ..cli import cli_requested
    if cli_requested(["dossier"] + args):          # a command: run it, never start the window (one program, window and command line)
        try:
            from redactor_common.cli import run
        except ImportError:                          # the shared package is missing: the check below explains what to install
            run = None
        if run is not None:
            from ..cli import main as cli_main
            return run(cli_main, args)
    from .check_install import check_or_explain
    if not check_or_explain():                    # a missing package gets a plain message, not a traceback
        return 1
    if "--check" in args:
        print("Everything Dossier needs is installed.")
        return 0
    if args[:1] == ["view"]:                      # the picture viewer on its own, without the file manager (dossier view picture.jpg)
        from .viewer_app import main as view_main
        return view_main(args[1:])
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
