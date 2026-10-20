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
import sys
from dataclasses import dataclass
from typing import Callable, Optional

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
    if sys.platform == "win32":
        root = os.environ.get("SystemRoot") or os.environ.get("windir") or ""
        return bool(root) and os.path.isfile(os.path.join(root, "System32", "mount.exe"))
    return shutil.which("mount.nfs") is not None


def free_letters(used: list) -> list:
    """Drive letters not in use, from Z backwards (the way Windows suggests them)."""
    taken = {u[:1].upper() for u in used if u[1:2] == ":"}
    return [c + ":" for c in reversed(string.ascii_uppercase) if c not in taken and c not in "AB"]


def clean_address(protocol: str, text: str) -> str:
    """The share address in the form the system wants, or an empty string when it is not one.

    SMB: ``\\\\server\\share`` (forward slashes are accepted). NFS: ``\\\\server\\export`` or ``server:/export``."""
    text = (text or "").strip().strip(chr(34))
    if not text or "://" in text:
        return ""
    back = chr(92)
    if protocol == NFS and re.fullmatch(r"[^\s:\\/]+:/\S*", text):
        return text
    text = text.replace("/", back)
    if not text.startswith(back * 2):
        return ""
    parts = [p for p in text[2:].split(back) if p]
    if len(parts) < 2 or any(c in text for c in ' \t"<>|*?'):
        return ""
    return back * 2 + back.join(parts)


def build_command(protocol: str, address: str, letter: str = "") -> list:
    """The argument list that mounts ``address`` (already cleaned) on ``letter`` ("" = let the system pick, SMB only)."""
    if sys.platform != "win32":
        raise OSError("Mounting from Dossier is only built for Windows; mount the share with your system's tools and it "
                      "will appear here")
    if protocol == NFS:
        return ["mount", "-o", "anon", address, letter or "*"]
    return ["net", "use", letter or "*", address, "/persistent:no"]


def run_command(argv: list, timeout: int = TIMEOUT, runner: Optional[Callable] = None) -> MountResult:
    """Run the mount command and return what it said. Never raises: a missing program or a timeout is a failed result."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = (runner or subprocess.run)(argv, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                                          stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return MountResult(False, f"No answer after {timeout} seconds. The server may be off or unreachable.")
    except OSError as e:
        return MountResult(False, str(e.strerror or e))
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    return MountResult(done.returncode == 0, text or ("Mounted." if done.returncode == 0 else f"Failed (code {done.returncode})."))
