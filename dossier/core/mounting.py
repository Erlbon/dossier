"""Mounting network shares through the operating system: SMB and NFS.

Dossier does not speak these protocols; Windows (or Linux) does, and the share then shows up as an ordinary network drive.
This module only builds the command, says whether the NFS client is installed, and runs the command on request. No password is
ever put on a command line or stored: a share that needs one is mounted through the system's own prompt or credential manager.
"""
from __future__ import annotations

import os
import re
import shutil
import string
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from urllib.parse import quote, unquote

from .platform import IS_MACOS, IS_WINDOWS, no_window_flags

SMB = "smb"
NFS = "nfs"
PROTOCOLS = ((SMB, "SMB (Windows share)"), (NFS, "NFS"))
TIMEOUT = 45

NFS_OFF_TEXT = (
    "Windows needs its Client for NFS to mount an NFS share, and it is not switched on.\n\n"
    "Switch it on in Windows Features (Turn Windows features on or off > Services for NFS > Client for NFS), or in an "
    "administrator PowerShell:\n\n    Enable-WindowsOptionalFeature -Online -FeatureName ServicesForNFS-ClientOnly -All\n\n"
    "Dossier does not change system settings itself.")


@dataclass
class MountResult:
    ok: bool
    output: str


def nfs_client_installed() -> Optional[bool]:
    """Whether the system can mount NFS: on Windows ``mount.exe`` exists in System32 only when Client for NFS is installed
    (no administrator rights needed to look). On Linux, whether ``mount.nfs`` is there. None when it cannot be told."""
    if IS_WINDOWS:
        root = os.environ.get("SystemRoot") or os.environ.get("windir") or ""
        return bool(root) and os.path.isfile(os.path.join(root, "System32", "mount.exe"))
    if IS_MACOS:
        return True                                    # the Mac mounts nfs:// itself
    return shutil.which("gio") is not None or shutil.which("mount.nfs") is not None


def free_letters(used: list) -> list:
    """Drive letters not in use, from Z backwards (the way Windows suggests them)."""
    taken = {u[:1].upper() for u in used if u[1:2] == ":"}
    return [c + ":" for c in reversed(string.ascii_uppercase) if c not in taken and c not in "AB"]


def clean_address(protocol: str, text: str) -> str:
    """The share address in the form the system wants, or an empty string when it is not one.

    SMB: ``\\\\server\\share`` (forward slashes are accepted). NFS: ``\\\\server\\export`` or ``server:/export``."""
    text = (text or "").strip().strip(chr(34))
    if text.lower().startswith(("smb://", "nfs://")):         # the Mac's and the Linux desktop's form
        rest = unquote(text.split("://", 1)[1]).strip("/")
        if protocol == NFS and text.lower().startswith("nfs://"):
            server, _, export = rest.partition("/")
            return f"{server}:/{export}" if server else ""
        text = chr(92) * 2 + rest
    if not text or "://" in text:
        return ""
    back = chr(92)
    if protocol == NFS and re.fullmatch(r"[^\s:\\/]+:/\S*", text):
        return text
    text = text.replace("/", back)
    if not text.startswith(back * 2):
        return ""
    parts = [p for p in text[2:].split(back) if p]
    if len(parts) < 2 or any(c in text for c in '\t"<>|*?'):
        return ""
    return back * 2 + back.join(parts)


def share_url(protocol: str, address: str) -> str:
    """``address`` (cleaned) as the URL the Mac and the Linux desktop mount by: ``smb://server/share``, ``nfs://server/export``."""
    if protocol == NFS and not address.startswith(chr(92) * 2):
        server, _, export = address.partition(":")
        return f"nfs://{server}{export if export.startswith('/') else '/' + export}"
    parts = [quote(p) for p in address[2:].split(chr(92)) if p]
    return f"{protocol}://" + "/".join(parts)


def build_command(protocol: str, address: str, letter: str = "") -> list:
    """The argument list that mounts ``address`` (already cleaned) on ``letter`` ("" = let the system pick, SMB only). On the Mac
    the system's own ``open smb://...`` mounts it under /Volumes, asking for a password itself (Keychain); on Linux ``gio mount``
    hands it to the desktop's GVfs, which puts it under /run/user/<id>/gvfs. Neither takes a drive letter."""
    if not IS_WINDOWS:
        url = share_url(protocol, address)
        return ["open", url] if IS_MACOS else ["gio", "mount", url]
    if protocol == NFS:
        return ["mount", "-o", "anon", address, letter or "*"]
    return ["net", "use", letter or "*", address, "/persistent:no"]


def wants_login(output: str) -> bool:
    """Whether a failed mount says the share wants a login (``gio mount`` asks on its own input, which is empty here)."""
    low = (output or "").lower()
    return any(word in low for word in ("password", "authentication", "user name", "username", "permission denied", "access denied"))


def run_command(argv: list, timeout: int = TIMEOUT, runner: Optional[Callable] = None) -> MountResult:
    """Run the mount command and return what it said. Never raises: a missing program or a timeout is a failed result."""
    flags = no_window_flags()
    try:
        done = (runner or subprocess.run)(argv, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                                          stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return MountResult(False, f"No answer after {timeout} seconds. The server may be off or unreachable.")
    except OSError as e:
        return MountResult(False, str(e.strerror or e))
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    return MountResult(done.returncode == 0, text or ("Mounted." if done.returncode == 0 else f"Failed (code {done.returncode})."))
