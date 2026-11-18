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


def clean_up_after_update() -> None:
    """The copy an update replaced (``dossier.exe.old``) and a half-finished download are deleted at the next start. Only the
    built exe has them; from source this does nothing."""
    try:
        from redactor_common.core.selfupdate import remove_leftovers
    except ImportError:                              # the shared package is missing: the install check explains it
        return
    remove_leftovers()


def update_command(args: list) -> bool:
    """Whether the family's update command line (redactor_common.core.update_cli) answers these arguments: --check-update and
    --update, and --version when it is asked for a --result-file (the release gate reads the bare build number from there). A plain
    ``dossier --version`` stays the command line's "Dossier 0.8 (build ...)"."""
    return "--check-update" in args or "--update" in args or ("--version" in args and "--result-file" in args)


FN_NOTE = ("Dossier's commands sit on the F-keys (F5 copies, F6 moves, F7 makes a folder, F8 deletes). On most Mac keyboards these keys "
           "change the brightness and the sound unless you hold Fn, so press Fn+F5 to copy, and so on.\n\n"
           "To use them without Fn, switch on \"Use F1, F2, etc. keys as standard function keys\" in System Settings, Keyboard, "
           "Keyboard Shortcuts, Function Keys.\n\n"
           "Dossier's other shortcuts follow the Mac: where Windows says Ctrl, press Cmd. Completing a name in the command line is "
           "Option+Space.")


def mac_first_start(window) -> bool:
    """On a Mac, the first start shows a short note about the F-keys and Fn (card 39), once. True when it was shown."""
    if str(window.settings.value("mac/fn_note_shown", "false")).lower() == "true":
        return False
    window.settings.setValue("mac/fn_note_shown", "true")
    window.dialogs.info("The F-keys on a Mac", FN_NOTE)
    return True


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if args[:1] == ["--askpass"]:                   # ssh asking for a password: answered at once, with no window and no checks
        from ..core.askpass import main as askpass_main
        return askpass_main(args[1:])
    if update_command(args):                        # the update framework: what this copy would do with a release, or do it
        from redactor_common.core import update_cli

        from ..core.version import APP_NAME, APP_REPO_URL, APP_VERSION
        return update_cli.handle(args, APP_NAME, APP_VERSION, APP_REPO_URL)
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
    clean_up_after_update()

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())                 # every window of the program, the viewer and notepad too
    probe_folder = os.environ.get("DOSSIER_STARTUP_PROBE", "")
    window = MainWindow(settings_path=os.path.join(probe_folder, "dossier.ini") if probe_folder else None)    # a probe never uses yours
    window.show()
    if probe_folder:                               # tools/time_startup.py: say when the window is up and can be typed in, then close
        from PyQt6.QtCore import QTimer
        probe = QTimer(window)
        probe.setSingleShot(True)
        probe.timeout.connect(lambda: (print("dossier-ready", flush=True), window.close()))
        probe.start(0)
    else:
        from ..core.platform import IS_MACOS
        if IS_MACOS:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(400, lambda: mac_first_start(window))
    return leave(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
