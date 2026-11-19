"""Quick Look (card 45A): the system's own preview window for one item.

The Mac has ``qlmanage -p``. Linux has the GNOME previewer (sushi), a D-Bus service that Files uses for the space bar; it is called
with ``gdbus``. Windows has nothing of the kind, so there is no entry there. No Qt in here: the window asks ``QuickLook`` whether it
is available and which command to start.

Sushi's call, from its published interface (``data/org.gnome.NautilusPreviewer2.xml``, checked 2026-11-19): bus name
``org.gnome.NautilusPreviewer``, object ``/org/gnome/NautilusPreviewer``, ``org.gnome.NautilusPreviewer2.ShowFile(s uri,
s windowHandle, b closeIfAlreadyShown, s activationToken)``; an empty window handle and token are allowed. Not yet tried on a
real desktop.
"""
from __future__ import annotations

import os
import shutil
import threading
from typing import Callable, Optional
from urllib.parse import quote

from .platform import IS_LINUX, IS_MACOS

SUSHI_SERVICE = "org.gnome.NautilusPreviewer"
_SERVICE_FILE = SUSHI_SERVICE + ".service"


def _system_now() -> str:
    return "linux" if IS_LINUX else "mac" if IS_MACOS else ""


def sushi_installed(data_dirs: Optional[list] = None, exists: Callable[[str], bool] = os.path.exists,
                    which: Callable[[str], Optional[str]] = shutil.which) -> bool:
    """Is the GNOME previewer there: its D-Bus service file under the XDG data folders, or a ``sushi`` program on the path, and
    ``gdbus`` to call it with. Looks on disk, so it runs on a thread."""
    if which("gdbus") is None:
        return False
    if data_dirs is None:
        home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        data_dirs = [home] + [d for d in dirs.split(":") if d]
    if any(exists(os.path.join(d, "dbus-1", "services", _SERVICE_FILE)) for d in data_dirs):
        return True
    return which("sushi") is not None


def command_for(path: str, system: str, sushi: bool = False) -> Optional[list]:
    """The command that previews ``path``: ``qlmanage -p`` on the Mac, a ``gdbus`` call to sushi on Linux when it is installed;
    None when this system cannot (or the path is not a full local path)."""
    if not path:
        return None
    if system == "mac":
        return ["qlmanage", "-p", path]
    if system == "linux" and sushi and path.startswith("/"):
        uri = "file://" + quote(path)                 # percent-encoded, so it holds no quote mark
        return ["gdbus", "call", "--session", "--dest", SUSHI_SERVICE, "--object-path", "/org/gnome/NautilusPreviewer",
                "--method", SUSHI_SERVICE + "2.ShowFile", f"'{uri}'", "''", "false", "''"]
    return None


class QuickLook:
    """Whether Quick Look is available here. The Mac always has it; on Linux whether sushi is installed is looked up once on a
    thread (``start``), and ``available`` is False until that is done."""

    def __init__(self, system: Optional[str] = None, detector: Optional[Callable[[], bool]] = None) -> None:
        self.system = _system_now() if system is None else system
        self._detector = detector or sushi_installed
        self._sushi = False
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self.system != "linux" or self._started:
                return
            self._started = True
        threading.Thread(target=self.detect_now, daemon=True, name="dossier-quicklook").start()

    def detect_now(self) -> None:
        try:
            found = bool(self._detector())
        except OSError:
            found = False
        with self._lock:
            self._sushi = found

    @property
    def available(self) -> bool:
        return self.system == "mac" or (self.system == "linux" and self._sushi)

    def command(self, path: str) -> Optional[list]:
        return command_for(path, self.system, self._sushi) if self.available else None
