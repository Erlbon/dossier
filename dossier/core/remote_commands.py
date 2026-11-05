"""Work done on the server itself, when the owner allows commands on that server (card 34 of the review of 2026-11-05; Qt-free).

A checksum of a file on a server, or a copy from one folder of a server to another, otherwise sends every byte to this computer and (for
the copy) back again. With "Allow commands on this server" on, Dossier runs a fixed command over the connection's shell instead:
``sha256sum`` for a checksum, ``cp -p`` for a copy. The commands are built here, never taken from an assistant or a user, and every path is
quoted with ``shlex.quote``, so nothing a file is called can become a command. When the switch is off, the command is missing or it
fails, the answer is None or False and the caller goes on the ordinary way (SFTP), so the switch can only make things faster.
"""
from __future__ import annotations

import re
import shlex
from typing import Optional

HEX64 = re.compile(r"^([0-9a-fA-F]{64})[ *]")


def sha256(shell, remote_path: str) -> Optional[str]:
    """The SHA-256 of a file on the server, in lower-case hex, or None (no ``sha256sum`` there, or it failed)."""
    try:
        out, status = shell.run(f"sha256sum -b -- {shlex.quote(remote_path)} 2>/dev/null", timeout=3600.0)
    except (ConnectionError, OSError):
        return None
    m = HEX64.match(out.decode("utf-8", "replace").strip())
    return m.group(1).lower() if status == 0 and m else None


def copy(shell, src: str, dst: str) -> bool:
    """Copy one file on the server, keeping its time (``cp -p``). False when it did not work; a half-made target is removed. The caller
    has made sure ``dst`` is a new name (a part file), so nothing is overwritten."""
    try:
        _out, status = shell.run(f"cp -p -- {shlex.quote(src)} {shlex.quote(dst)} 2>/dev/null", timeout=24 * 3600.0)
        if status == 0:
            return True
        shell.run(f"rm -f -- {shlex.quote(dst)} 2>/dev/null")
    except (ConnectionError, OSError):
        pass
    return False
