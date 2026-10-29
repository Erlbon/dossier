"""Logging in to a network share that refuses us (wrong or missing user name and password).

Dossier never sees the password: Windows' own sign-in dialog is asked for (``WNetAddConnection3`` with the prompt flags), the same
one Explorer shows, with its "remember my credentials" box. When the dialog is accepted the connection exists and the folder can be
listed again.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Callable, Optional

# Windows error numbers that mean "the share wants a (different) login".
ACCESS_DENIED = 5
BAD_NETPATH_CREDENTIALS = 86            # the specified network password is not correct
SESSION_CREDENTIAL_CONFLICT = 1219      # already connected to the server with other credentials
LOGON_FAILURE = 1326                    # unknown user name or bad password
ACCOUNT_RESTRICTION = 1327
LOGON_TYPE_NOT_GRANTED = 1385
NEEDS_LOGIN = (ACCESS_DENIED, BAD_NETPATH_CREDENTIALS, SESSION_CREDENTIAL_CONFLICT, LOGON_FAILURE, ACCOUNT_RESTRICTION,
               LOGON_TYPE_NOT_GRANTED)

CONNECT_INTERACTIVE = 0x8
CONNECT_PROMPT = 0x10
RESOURCETYPE_DISK = 1
NO_ERROR = 0
CANCELLED = 1223


def share_of(path: str) -> str:
    """``\\\\server\\share`` of a network path, or an empty string when ``path`` is not one (a drive letter, a URL...)."""
    back = chr(92)
    text = (path or "").replace("/", back)
    if not text.startswith(back * 2) or text.startswith(back * 2 + "?"):
        return ""
    parts = [p for p in text[2:].split(back) if p]
    if len(parts) < 2:
        return ""
    return back * 2 + back.join(parts[:2])


def needs_login(error: BaseException, path: str) -> bool:
    """True when listing ``path`` failed because the server wants a login, so asking for one can help."""
    if sys.platform != "win32" or not share_of(path):
        return False
    return getattr(error, "winerror", None) in NEEDS_LOGIN


def ask_login(path: str, hwnd: int = 0, connect: Optional[Callable] = None) -> bool:
    """Show Windows' sign-in dialog for the share of ``path``. True when a login was accepted. ``connect`` is a seam for tests: it
    gets (share, hwnd) and returns the Windows result code."""
    share = share_of(path)
    if not share:
        return False
    code = (connect or _connect)(share, hwnd)
    return code == NO_ERROR


def _connect(share: str, hwnd: int) -> int:
    if sys.platform != "win32":
        return 1
    from ctypes import wintypes

    class NetResource(ctypes.Structure):
        _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD), ("dwDisplayType", wintypes.DWORD),
                    ("dwUsage", wintypes.DWORD), ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]

    resource = NetResource()
    resource.dwType = RESOURCETYPE_DISK
    resource.lpRemoteName = share
    mpr = ctypes.WinDLL("mpr")                                                  # type: ignore[attr-defined]
    mpr.WNetAddConnection3W.argtypes = [wintypes.HWND, ctypes.POINTER(NetResource), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                        wintypes.DWORD]
    mpr.WNetAddConnection3W.restype = wintypes.DWORD
    return int(mpr.WNetAddConnection3W(hwnd or None, ctypes.byref(resource), None, None, CONNECT_INTERACTIVE | CONNECT_PROMPT))
