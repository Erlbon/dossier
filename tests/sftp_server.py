"""A real SFTP server for the tests: OpenSSH's own ``sftp-server``, started as a child process that speaks SFTP on its standard streams.

No SSH is involved (the encryption and the login are the operating system's ssh, which the tests do not need): this is the file protocol
only, answered by the program real servers use, so the client is checked against a real implementation and not against itself. It is
found where Git for Windows, OpenSSH for Windows or a Linux package puts it; without it the tests that need it are skipped.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional

CANDIDATES = (r"C:\Program Files\Git\usr\lib\ssh\sftp-server.exe", r"C:\Windows\System32\OpenSSH\sftp-server.exe",
              "/usr/lib/openssh/sftp-server", "/usr/lib/ssh/sftp-server", "/usr/libexec/openssh/sftp-server", "/usr/libexec/sftp-server")


def find_sftp_server() -> Optional[str]:
    found = shutil.which("sftp-server")
    if found:
        return found
    git = shutil.which("git")
    if git:
        near = os.path.join(os.path.dirname(os.path.dirname(git)), "usr", "lib", "ssh", "sftp-server.exe")
        if os.path.isfile(near):
            return near
    return next((p for p in CANDIDATES if os.path.isfile(p)), None)


class LocalServer:
    """``sftp-server`` as a child process; ``reader`` and ``writer`` are its pipes, ``root`` the folder the tests work in."""

    def __init__(self, exe: str, root: str) -> None:
        self.root = root
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.process = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
        self.reader, self.writer = self.process.stdout, self.process.stdin

    def path(self, *parts: str) -> str:
        """A path in the server's own spelling (forward slashes; on Windows the drive letter first, as the Git build understands it)."""
        return "/".join([self.root.replace(os.sep, "/")] + list(parts))

    def stop(self) -> None:
        for stream in (self.writer, self.reader):
            try:
                stream.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def find_sh() -> Optional[str]:
    """A POSIX shell for the tests of the ``scp`` kind of connection (the one in Git for Windows, or the system's)."""
    found = shutil.which("sh")
    if found:
        return found
    git = shutil.which("git")
    if git:
        for rel in (("usr", "bin", "sh.exe"), ("bin", "sh.exe")):
            near = os.path.join(os.path.dirname(os.path.dirname(git)), *rel)
            if os.path.isfile(near):
                return near
    return "/bin/sh" if os.path.isfile("/bin/sh") else None


def make_fake_ssh(folder, monkeypatch, mode: str = "serve", log: str = "") -> str:
    """Put a fake ``ssh`` (see ``fake_ssh.py``) where ``sshlink.find_tool`` will find it, and return its path."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_ssh.py")
    if sys.platform == "win32":
        path = os.path.join(str(folder), "fake_ssh.cmd")
        body = f'@echo off\r\n"{sys.executable}" "{here}" %*\r\n'
    else:
        path = os.path.join(str(folder), "fake_ssh.sh")
        body = f'#!/bin/sh\nexec "{sys.executable}" "{here}" "$@"\n'
    with open(path, "w", newline="") as f:
        f.write(body)
    if sys.platform != "win32":
        os.chmod(path, 0o700)
    from dossier.core import sshlink
    monkeypatch.setattr(sshlink, "find_tool", lambda name: path if name == "ssh" else "")
    monkeypatch.setenv("FAKE_SSH_MODE", mode)
    monkeypatch.setenv("FAKE_SFTP_SERVER", find_sftp_server() or "")
    monkeypatch.setenv("FAKE_SH", find_sh() or "")
    if log:
        monkeypatch.setenv("FAKE_SSH_LOG", log)
    return path
