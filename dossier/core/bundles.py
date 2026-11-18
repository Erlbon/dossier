"""Programs that look like folders or files (card 50A). Qt-free.

On the Mac an app (``Mail.app``) and a document package (a Keynote file, a Photos library) are folders that Finder shows as one
file: Enter starts or opens them through the system, and Show Package Contents goes inside. On Linux a ``.desktop`` launcher is shown
by its own name and started by its own command (asking once per launcher, as Files does); a runnable file of no known type asks
whether to run it, run it in a terminal or view it."""
from __future__ import annotations

import os
import stat
from dataclasses import replace
from typing import Callable, Optional

from .filetypes import BY_EXTENSION
from .platform import IS_LINUX, IS_MACOS, IS_WINDOWS

MAC = IS_MACOS            # read at call time, so a test can switch the Mac or Linux branches on
LINUX = IS_LINUX
WINDOWS = IS_WINDOWS

# the folders Finder shows as one file: apps and their parts, and the document packages of the Mac's own programs
PACKAGE_EXTENSIONS = frozenset(
    "app bundle plugin kext prefpane appex xpc qlgenerator mdimporter saver wdgt "
    "photoslibrary musiclibrary imovielibrary fcpbundle logicx band tvlibrary photolibrary aplibrary migratedphotolibrary "
    "key pages numbers rtfd scptd workflow xcarchive playground pkg mpkg action lpdf".split())
APP_EXTENSIONS = frozenset({"app"})
MAX_LAUNCHERS = 500                     # a folder full of launchers is named only this far (each is a small file read)


def _ext(name: str) -> str:
    return os.path.splitext(name.rstrip("/"))[1].lstrip(".").lower()


def is_package(name: str, is_dir: bool, mac: Optional[bool] = None) -> bool:
    """A Mac folder Finder shows as one file (``Mail.app``, ``Talk.key``). Never on other systems, where they are plain folders."""
    return (MAC if mac is None else mac) and is_dir and _ext(name) in PACKAGE_EXTENSIONS


def is_app(name: str) -> bool:
    return _ext(name) in APP_EXTENSIONS


def is_launcher(name: str, is_dir: bool, linux: Optional[bool] = None) -> bool:
    """A Linux ``.desktop`` launcher."""
    return (LINUX if linux is None else linux) and not is_dir and name.lower().endswith(".desktop")


def name_launchers(entries: list, read: Optional[Callable] = None, linux: Optional[bool] = None) -> list:
    """The listing with each launcher's own name (``Firefox`` for ``firefox.desktop``) in its ``label``, for the Name column. Reads
    each launcher: call it on the listing's thread. A launcher that cannot be read keeps its file name."""
    linux = LINUX if linux is None else linux
    if not linux:
        return entries
    if read is None:
        from .desktop_entries import read_entry
        read = read_entry
    out, named = [], 0
    for e in entries:
        if named < MAX_LAUNCHERS and is_launcher(e.name, e.is_dir, linux) and not e.label:
            named += 1
            try:
                app = read(e.path)
            except (OSError, ValueError):
                app = None
            if app is not None and app.name:
                e = replace(e, label=app.name)
        out.append(e)
    return out


def shown_name(entry) -> str:
    """What the Name column shows: a launcher's own name, else the file's."""
    return entry.label if entry.label and entry.name.lower().endswith(".desktop") and not entry.is_dir else entry.name


def is_runnable(name: str, is_dir: bool, mode: int, windows: Optional[bool] = None) -> bool:
    """A file that may be run as a program and is of no type Dossier knows: the run bit set on a plain file whose name says
    nothing (``install``, ``tool.run``, ``App.AppImage``). Scripts (``scripts.py``), launchers and known types (a ``.jpg`` on a
    stick where every file has the run bit) are left to their own rules."""
    if (WINDOWS if windows is None else windows) or is_dir or not mode or not stat.S_ISREG(mode) or not mode & 0o111:
        return False
    return name_could_run(name)


def name_could_run(name: str) -> bool:
    """The name alone says nothing known (no type, script or launcher): the first test, before the file is looked at."""
    from .scripts import POSIX_SCRIPTS
    ext = _ext(name)
    return ext not in BY_EXTENSION and "." + ext not in POSIX_SCRIPTS and ext != "desktop"


def type_label(entry) -> str:
    """What the Type column says for a package or launcher, else an empty string."""
    if is_package(entry.name, entry.is_dir):
        return "App" if is_app(entry.name) else "Package"
    return "Launcher" if is_launcher(entry.name, entry.is_dir) else ""
