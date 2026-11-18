"""Open With on the Mac and Linux (card 49A): the programs the system itself knows for a file's type, the default first.

Linux reads the XDG standard directly (``desktop_entries``: the launchers, ``mimeapps.list`` and the type table); that touches many
files, so it is read once on a thread (``SystemPrograms.start``) and the menu shows nothing from it until it is ready. The Mac asks
Launch Services through the system library, which answers from its own database. Windows keeps its own chooser
(``platform.open_with_command``). Each program is started by ``tools.program_commands``, which knows a ``.app`` and a ``.desktop``."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .platform import IS_LINUX, IS_MACOS

MAX_PROGRAMS = 20                       # a type that every editor claims (text/plain) should not fill the screen


@dataclass(frozen=True)
class Program:
    name: str
    path: str                           # the launcher (.desktop) or the app (.app): what ``tools.program_commands`` starts
    default: bool = False
    icon: str = ""


def linux_programs(desktop, name: str, is_dir: bool = False) -> list:
    """The programs a Linux desktop offers for ``name``, the default first (marked), from a loaded ``desktop_entries.Desktop``."""
    from .desktop_entries import type_family
    mime = desktop.mime.type_of(name, is_dir)
    apps = desktop.programs_for(name, is_dir)
    default_id = ""
    for m in type_family(mime, desktop.mime.parents):
        found = next((i for i in desktop.associations.default.get(m, []) if i in desktop.apps), "")
        if found:
            default_id = found
            break
    return [Program(a.name, a.path, a.id == default_id and i == 0, a.icon) for i, a in enumerate(apps[:MAX_PROGRAMS])]


def mac_programs(path: str, lookup: Optional[Callable] = None) -> list:
    """The apps Launch Services names for ``path``, the default first, each once. ``lookup(path)`` gives ``(default, [apps])`` as
    paths; by default the system is asked."""
    default, apps = (lookup or _launch_services)(path)
    out, seen = [], set()
    for app in ([default] if default else []) + list(apps):
        key = app.rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(Program(os.path.splitext(os.path.basename(key))[0], key, key == (default or "").rstrip("/")))
        if len(out) >= MAX_PROGRAMS:
            break
    return [out[0]] + sorted(out[1:], key=lambda p: p.name.casefold()) if out and out[0].default else \
        sorted(out, key=lambda p: p.name.casefold())


def _launch_services(path: str) -> tuple:
    """``(default app, [every app])`` for ``path`` from Launch Services, as paths; ``("", [])`` when the system will not say."""
    import ctypes
    import ctypes.util
    try:
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        ls = ctypes.CDLL(ctypes.util.find_library("CoreServices"))
    except (OSError, TypeError):
        return "", []
    vp, idx = ctypes.c_void_p, ctypes.c_long
    cf.CFURLCreateFromFileSystemRepresentation.restype = vp
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [vp, ctypes.c_char_p, idx, ctypes.c_bool]
    cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
    cf.CFURLGetFileSystemRepresentation.argtypes = [vp, ctypes.c_bool, ctypes.c_char_p, idx]
    cf.CFArrayGetCount.restype = idx
    cf.CFArrayGetCount.argtypes = [vp]
    cf.CFArrayGetValueAtIndex.restype = vp
    cf.CFArrayGetValueAtIndex.argtypes = [vp, idx]
    cf.CFRelease.argtypes = [vp]
    ls.LSCopyApplicationURLsForURL.restype = vp
    ls.LSCopyApplicationURLsForURL.argtypes = [vp, ctypes.c_uint32]
    ls.LSCopyDefaultApplicationURLForURL.restype = vp
    ls.LSCopyDefaultApplicationURLForURL.argtypes = [vp, ctypes.c_uint32, vp]
    roles = 0xFFFFFFFF                                                            # kLSRolesAll

    def as_path(url) -> str:
        buf = ctypes.create_string_buffer(4096)
        return os.fsdecode(buf.value) if url and cf.CFURLGetFileSystemRepresentation(url, True, buf, 4096) else ""

    raw = os.fsencode(path)
    url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), os.path.isdir(path))
    if not url:
        return "", []
    try:
        found = ls.LSCopyDefaultApplicationURLForURL(url, roles, None)
        default = as_path(found)
        if found:
            cf.CFRelease(found)
        apps = []
        array = ls.LSCopyApplicationURLsForURL(url, roles)
        if array:
            try:
                apps = [as_path(cf.CFArrayGetValueAtIndex(array, i)) for i in range(cf.CFArrayGetCount(array))]
            finally:
                cf.CFRelease(array)
        return default, [a for a in apps if a]
    finally:
        cf.CFRelease(url)


class SystemPrograms:
    """The system's programs per file, for the Open With menu. On Linux the desktop's data is read once on a thread (``start``)
    and ``for_file`` gives ``[]`` until it is there; on the Mac each call asks Launch Services; elsewhere there are none."""

    def __init__(self, loader: Optional[Callable] = None, mac_lookup: Optional[Callable] = None,
                 system: str = "linux" if IS_LINUX else "mac" if IS_MACOS else "") -> None:
        self.system = system
        self._loader = loader
        self._mac_lookup = mac_lookup
        self._desktop = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Read the Linux desktop's programs on a thread (once; nothing to do elsewhere)."""
        with self._lock:
            if self.system != "linux" or self._started:
                return
            self._started = True
        threading.Thread(target=self.load_now, daemon=True, name="dossier-open-with").start()

    def load_now(self) -> None:
        if self._loader is None:
            from .desktop_entries import Desktop
            loaded = Desktop.load()
        else:
            loaded = self._loader()
        with self._lock:
            self._desktop = loaded

    @property
    def ready(self) -> bool:
        return self.system == "mac" or (self.system == "linux" and self._desktop is not None)

    def for_file(self, path: str, is_dir: bool = False) -> list:
        try:
            if self.system == "mac":
                return mac_programs(path, self._mac_lookup)
            if self.system == "linux" and self._desktop is not None:
                return linux_programs(self._desktop, os.path.basename(path.rstrip("/")), is_dir)
        except (OSError, ValueError, AttributeError):
            return []
        return []
