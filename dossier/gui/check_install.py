"""Before the window opens: is everything Dossier needs installed? A missing package must give a plain message, not a traceback
(and a program started without a console window, like the ``dossier`` command, must show the message in a box).

The packages, and the module inside each that this version of Dossier needs. ``redactor_common`` is checked by a module that was added
in the tag the program is pinned to, so an older copy of it is told apart from none at all.
"""
from __future__ import annotations

import importlib.util
import sys
from typing import Callable, Optional

REQUIRED = (
    ("PyQt6.QtWidgets", "PyQt6", "the windows"),
    ("send2trash", "send2trash", "the recycle bin"),
    ("redactor_common.core.meta_fields", "redactor_common", "the dialogs and readers shared with the Redactor apps (needs the tag "
                                                           "2026-10-20-02 or newer)"),
)
INSTALL = "python -m pip install -r requirements.txt"


def _has(module: str, find: Callable = importlib.util.find_spec) -> bool:
    try:
        return find(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def missing(find: Callable = importlib.util.find_spec) -> list:
    """``[(package, what it is for)]`` for everything that is not installed (or too old)."""
    return [(package, why) for module, package, why in REQUIRED if not _has(module, find)]


def message(problems: list) -> str:
    lines = ["Dossier cannot start: something it needs is not installed.", ""]
    lines += [f"  {package}: {why}" for package, why in problems]
    lines += ["", "Install everything in one go, from the Dossier folder:", f"  {INSTALL}"]
    return "\n".join(lines)


def check_or_explain(find: Callable = importlib.util.find_spec, show: Optional[Callable] = None) -> bool:
    """True when all is in place. Otherwise the message is printed (and, on Windows, shown in a box, since a program started
    without a console has nowhere to print) and False is returned."""
    problems = missing(find)
    if not problems:
        return True
    text = message(problems)
    print(text, file=sys.stderr)
    if show is not None:
        show(text)
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Dossier", 0x10)
        except Exception:   # noqa: BLE001 -- the printed message is enough
            pass
    return False
