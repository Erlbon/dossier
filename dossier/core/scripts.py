"""Running a script file (``.bat``, ``.cmd``, ``.ps1``, ``.py``) on Enter, as a double-click in Explorer does. Qt-free.

A script is also text, so under the "viewer" open choice it used to be shown instead of run. The owner wants scripts run (2026-11-03),
with a setting (Settings > Opening Files > Run Scripts on Enter) for people who would rather look first. Ctrl+Enter does the other thing,
F3 views and F4 edits as before.

Each script runs in its own console window with its own folder as the working folder (a batch file with relative paths works as when it
is double-clicked; Windows itself would start it in Dossier's folder). A PowerShell script is started the way Explorer's "Run with
PowerShell" does it: the execution policy is set to Bypass for that one process only, unless the machine demands AllSigned. Nothing in the
system's settings is changed.
"""
from __future__ import annotations

import os
import shutil
from typing import Callable, Optional

from .platform import IS_WINDOWS
from .terminals import Launch

WINDOWS_SCRIPTS = (".bat", ".cmd", ".ps1", ".py")
POSIX_SCRIPTS = (".sh", ".py")
PS_RUN = ("if ((Get-ExecutionPolicy) -ne 'AllSigned') { Set-ExecutionPolicy -Scope Process Bypass }; & ")


def extensions() -> tuple:
    return WINDOWS_SCRIPTS if IS_WINDOWS else POSIX_SCRIPTS


def is_script(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in extensions()


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def launch_for(path: str, which: Callable = shutil.which) -> Optional[Launch]:
    """How to run the script ``path`` in its own folder, or None when it is not a script."""
    if not is_script(path):
        return None
    folder = os.path.dirname(os.path.abspath(path))
    ext = os.path.splitext(path)[1].lower()
    if IS_WINDOWS:
        if ext == ".ps1":
            return Launch(["powershell.exe", "-NoProfile", "-Command", PS_RUN + _ps_quote(path)], folder)
        # .bat and .cmd run; .py goes to the program Windows has for it. /s with the path in two pairs of quotes: cmd takes off only the
        # outer pair, so a folder called "a & b (1)" stays one path (a Windows path can hold no quote of its own).
        return Launch(f'cmd.exe /d /s /c ""{path}""', folder)
    if os.access(path, os.X_OK):
        return Launch([path], folder)
    return Launch(["python3" if ext == ".py" else "sh", path], folder)
