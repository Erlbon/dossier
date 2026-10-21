"""The devices of a Tailscale network, as the local ``tailscale`` program knows them. Qt-free.

Tailscale is a VPN: every device of the owner's network (the *tailnet*) has an address and a name, and ordinary SFTP, WebDAV, OPDS or
Subsonic connections to them just work. This module only *reads* what the local Tailscale client says (``tailscale status --json``): it
never logs in or out, changes a setting or scans the network. When the program is not installed or not running there are no devices, and
the Home page shows no Tailnet section.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional

TIMEOUT = 5.0


@dataclass(frozen=True)
class Device:
    name: str                   # the machine's own name (HostName)
    dns: str                    # its MagicDNS name, without the final dot (empty when the tailnet has none)
    address: str                # its first IPv4 address (else its first address)
    os: str = ""
    online: bool = False
    is_self: bool = False

    @property
    def host(self) -> str:
        """What to type as the host of a connection: the address, which needs no name service."""
        return self.address or self.dns

    def detail(self) -> str:
        """The text of the Details column: the address alone, so the column lines up."""
        return self.address or self.dns

    def type_text(self) -> str:
        """The text of the Type column: the system and whether the device is there (``Windows, online``)."""
        system = self.os.capitalize() if self.os and self.os.islower() else self.os
        state = "this computer" if self.is_self else ("online" if self.online else "offline")
        return f"{system}, {state}" if system else state


def find_tailscale() -> str:
    """The path of the ``tailscale`` command, or an empty string."""
    found = shutil.which("tailscale")
    if found:
        return found
    candidates = []
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(var):
                candidates.append(os.path.join(os.environ[var], "Tailscale", "tailscale.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    return next((c for c in candidates if os.path.isfile(c)), "")


def _device(node: dict, is_self: bool) -> Optional[Device]:
    if not isinstance(node, dict):
        return None
    addresses = [a for a in node.get("TailscaleIPs", []) if isinstance(a, str)]
    v4 = next((a for a in addresses if "." in a), "")
    dns = str(node.get("DNSName") or "").rstrip(".")
    name = str(node.get("HostName") or dns.split(".")[0] or "").strip()
    if not name:
        return None
    return Device(name, dns, v4 or (addresses[0] if addresses else ""), str(node.get("OS") or ""), bool(node.get("Online")) or is_self, is_self)


def parse_status(text: str) -> list:
    """The devices in the output of ``tailscale status --json``: this computer first, then the online ones, then the others (by name).
    A damaged or foreign text is an empty list, never an error."""
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    me = _device(doc.get("Self"), True)
    peers = doc.get("Peer") if isinstance(doc.get("Peer"), dict) else {}
    others = [d for d in (_device(n, False) for n in peers.values()) if d is not None]
    others.sort(key=lambda d: (not d.online, d.name.lower()))
    return ([me] if me else []) + others


def read_devices(exe: str = "", run: Callable = subprocess.run) -> Optional[list]:
    """The devices of the tailnet, or None when Tailscale is not installed, not running or not logged in. Takes a moment (it starts a
    program): call it on a thread."""
    exe = exe or find_tailscale()
    if not exe:
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        done = run([exe, "status", "--json"], capture_output=True, text=True, timeout=TIMEOUT, creationflags=flags, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    devices = parse_status(done.stdout)
    return devices or None
