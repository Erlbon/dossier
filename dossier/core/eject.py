"""Eject a drive or unmount a share, on all three systems (card 47A, 2026-11-18).

- **Mac:** ``diskutil eject`` for a disk under /Volumes, ``diskutil unmount`` for a share.
- **Linux:** the desktop's ``gio mount --eject`` for a stick or disc and ``gio mount --unmount`` for a share or a phone it mounted;
  without gio, ``umount`` (which works for what the user may mount).
- **Windows:** a stick or disc is locked, taken off the system and its media ejected (the documented ``DeviceIoControl`` steps), so
  Windows says it is safe to remove; a mapped network drive is let go with ``net use X: /delete``.

When another program holds a file open the system refuses, and its reason is passed on. Waiting for Dossier's own copies to the
drive is the window's job (``touches``). Never raises: a refusal is a failed ``MountResult``.
"""
from __future__ import annotations

import os
import shutil
from typing import Callable, Optional

from .mounting import MountResult, run_command
from .platform import IS_MACOS, IS_WINDOWS, path_key, windows_program

EJECTABLE = ("removable", "optical", "network")


def can_eject(root: str, kind: str) -> bool:
    """Whether a drive of ``kind`` at ``root`` can be ejected or unmounted from Dossier: removable drives, discs and shares,
    never the system disk."""
    return kind in EJECTABLE and root not in ("/", "") and not root.startswith(("home:", "sftp:", "webdav:"))


def eject_commands(root: str, kind: str, which: Callable = shutil.which) -> list:
    """The commands that eject (or unmount) the drive at ``root``, as argument lists, or ``[]`` where Dossier does it itself
    (a stick or disc on Windows)."""
    if IS_WINDOWS:
        if kind == "network":
            return [[windows_program("net.exe"), "use", root.rstrip(chr(92) + "/"), "/delete"]]
        return []
    if IS_MACOS:
        return [["diskutil", "unmount" if kind == "network" else "eject", root]]
    if which("gio"):
        return [["gio", "mount", "--eject" if kind in ("removable", "optical") and "/gvfs/" not in root else "--unmount", root]]
    return [["umount", root]]


def touches(root: str, paths) -> bool:
    """Whether any of ``paths`` (the sources and destinations of the window's queued operations) is on the drive at ``root``."""
    key = path_key(root).rstrip(os.sep)
    for p in paths:
        if not p:
            continue
        k = path_key(p)
        if k == key or k.startswith(key + os.sep):
            return True
    return False


def eject(root: str, kind: str, runner: Optional[Callable] = None, windows_eject: Optional[Callable] = None) -> MountResult:
    """Eject or unmount the drive at ``root``. ``runner`` replaces ``subprocess.run`` and ``windows_eject`` the Windows steps in
    tests."""
    commands = eject_commands(root, kind)
    if not commands:
        try:
            (windows_eject or _windows_eject_volume)(root)
        except OSError as e:
            return MountResult(False, _windows_reason(e))
        return MountResult(True, f"{root.rstrip(chr(92))} can be removed safely.")
    result = MountResult(False, "")
    for argv in commands:
        result = run_command(argv, runner=runner)
        if not result.ok:
            return result
    return MountResult(True, result.output if result.output not in ("", "Mounted.") else f"{root} was ejected.")


def _windows_reason(e: OSError) -> str:
    code = getattr(e, "winerror", None)
    if code in (5, 32, 33):        # access denied, sharing violation, lock violation
        return ("Windows cannot eject it now: another program has a file open on it. Close that program (or its window "
                "showing the drive) and try again.")
    return f"Windows could not eject it: {e.strerror or e}"


def _windows_eject_volume(root: str) -> None:
    """Lock the volume, take it off the system, allow removal and eject its media: the steps Microsoft documents for removable
    media. Fails (with the system's error) when a file on it is open."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.HANDLE]
    kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING = 1, 2, 3
    FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME = 0x00090018, 0x00090020
    IOCTL_STORAGE_MEDIA_REMOVAL, IOCTL_STORAGE_EJECT_MEDIA = 0x002D4804, 0x002D4808
    letter = root.rstrip(chr(92) + "/")
    handle = kernel32.CreateFileW(chr(92) * 2 + "." + chr(92) + letter, GENERIC_READ | GENERIC_WRITE,
                                  FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = wintypes.DWORD()

        def control(code: int, data=None, size: int = 0) -> None:
            if not kernel32.DeviceIoControl(handle, code, data, size, None, 0, ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())

        import time
        for attempt in range(10):                       # Explorer may hold it for a moment after a copy
            try:
                control(FSCTL_LOCK_VOLUME)
                break
            except OSError:
                if attempt == 9:
                    raise
                time.sleep(0.3)
        control(FSCTL_DISMOUNT_VOLUME)
        prevent = ctypes.c_bool(False)
        control(IOCTL_STORAGE_MEDIA_REMOVAL, ctypes.byref(prevent), ctypes.sizeof(prevent))
        control(IOCTL_STORAGE_EJECT_MEDIA)
    finally:
        kernel32.CloseHandle(handle)
