"""Connecting to a server: the operating system's OpenSSH does the encryption and the login, Dossier does the rest.

Nothing is installed for this and no SSH library is bundled: ``ssh`` (with ``ssh-keyscan``, and ``scp``) comes with Windows 10 and 11,
macOS and nearly every Linux. ``ssh -s host sftp`` runs the server's file service and its standard streams carry the SFTP protocol of
``sftp_proto.py``.

* **Host keys are never accepted silently.** Before the first login the server's keys are fetched (``ssh-keyscan``) and shown with their
  fingerprints; only a key the owner approves is written to Dossier's own known-hosts file, and ``ssh`` is run with strict checking
  against that file only. A key that differs from the one approved before stops the connection with a plain warning.
* **A password never appears on a command line, in a file or in a log.** It reaches the one ``ssh`` process through its environment, and a
  tiny helper (``askpass.py``) prints it when ssh asks. Key files and the ssh-agent work without one.
* **Everything has a timeout and a way out:** the connect is cut off after the given time, ssh pings the server (``ServerAlive``) so a
  dead link is noticed, and closing the client ends the process.
"""
from __future__ import annotations

import base64
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Optional

from .askpass import VARIABLE
from .servers import Connection
from .sftp_proto import SftpClient
from .shellclient import ShellClient

WINDOWS_OPENSSH = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH")
CONNECT_TIMEOUT = 20
STDERR_KEEP = 8192


class ConnectError(Exception):
    """A connection that could not be made, with a sentence the owner can act on. ``kind`` is ``auth`` when the server refused the
    login (so a password is worth asking for), else an empty string."""

    def __init__(self, message: str, kind: str = "") -> None:
        super().__init__(message)
        self.kind = kind


def find_tool(name: str) -> str:
    """The path of an OpenSSH program (``ssh``, ``ssh-keyscan``, ``scp``), or an empty string when it is not installed."""
    if sys.platform == "win32":                           # Windows' own OpenSSH first: it works with the ssh-agent service and plain paths
        candidate = os.path.join(WINDOWS_OPENSSH, name + ".exe")
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name) or ""


def no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# host keys ---------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class HostKey:
    type: str
    b64: str

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.b64)


def fingerprint(b64: str) -> str:
    """``SHA256:...`` of a host key, in the form ``ssh-keygen -l`` and every ssh program shows."""
    try:
        blob = base64.b64decode(b64 + "=" * (-len(b64) % 4))
    except ValueError:
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def known_name(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def parse_keyscan(text: str) -> list:
    """The keys in the output of ``ssh-keyscan`` (comment lines and anything that is not ``host type key`` are skipped)."""
    keys = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("#") and parts[1].startswith(("ssh-", "ecdsa-", "sk-")):
            key = HostKey(parts[1], parts[2])
            if key not in keys:
                keys.append(key)
    rank = {"ssh-ed25519": 0, "ecdsa-sha2-nistp256": 1, "ssh-rsa": 2}
    return sorted(keys, key=lambda k: rank.get(k.type, 3))


def scan_host_keys(host: str, port: int = 22, timeout: int = 10) -> list:
    """Ask the server for its host keys (what a first connection would be shown). Raises ``ConnectError`` when it cannot be reached."""
    tool = find_tool("ssh-keyscan")
    if not tool:
        raise ConnectError("OpenSSH is not installed on this computer (ssh-keyscan was not found)")
    try:
        done = subprocess.run([tool, "-T", str(timeout), "-p", str(port), host], capture_output=True, text=True, timeout=timeout + 5,
                              creationflags=no_window())
    except subprocess.TimeoutExpired:
        raise ConnectError(f"{host} did not answer within {timeout} seconds")
    except OSError as e:
        raise ConnectError(f"ssh-keyscan could not be started: {e}")
    keys = parse_keyscan(done.stdout)
    if not keys:
        raise ConnectError(friendly(done.stderr) or f"{host} did not offer a host key (is there an SSH server on port {port}?)")
    return keys


class KnownHosts:
    """Dossier's own known-hosts file (in the OpenSSH format): the host keys the owner has approved."""

    def __init__(self, path: str) -> None:
        self.path = path

    def _lines(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def lookup(self, host: str, port: int = 22) -> list:
        name = known_name(host, port)
        out = []
        for line in self._lines():
            parts = line.split()
            if len(parts) >= 3 and not line.startswith("#") and name in parts[0].split(","):
                out.append(HostKey(parts[1], parts[2]))
        return out

    def check(self, host: str, port: int, scanned: list) -> str:
        """``known`` (a key the owner approved is offered), ``unknown`` (never seen) or ``changed`` (seen before, and now it is a
        different key: the sign of a man in the middle, or of a server that was reinstalled)."""
        stored = self.lookup(host, port)
        if not stored:
            return "unknown"
        return "known" if any(k in stored for k in scanned) else "changed"

    def add(self, host: str, port: int, keys: list) -> None:
        name = known_name(host, port)
        have = set(self.lookup(host, port))
        lines = self._lines() + [f"{name} {k.type} {k.b64}" for k in keys if k not in have]
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

    def remove(self, host: str, port: int = 22) -> None:
        name = known_name(host, port)
        kept = [ln for ln in self._lines() if not (ln.split() and name in ln.split()[0].split(","))]
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))


# the login helper --------------------------------------------------------------------------------------------------------------------
def askpass_command() -> list:
    """The program ssh runs to get a password: this program's own helper (``askpass.py``, or ``dossier --askpass`` in the built exe)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--askpass"]
    from . import askpass
    return [sys.executable, os.path.abspath(askpass.__file__)]


def askpass_shim(folder: str) -> str:
    """A small script in ``folder`` that ssh can run as ``SSH_ASKPASS`` (it needs one program name, not a command line)."""
    os.makedirs(folder, exist_ok=True)
    command = askpass_command()
    if sys.platform == "win32":
        path = os.path.join(folder, "askpass.cmd")
        body = "@echo off\r\n" + " ".join(f'"{c}"' for c in command) + " %*\r\n"
    else:
        path = os.path.join(folder, "askpass.sh")
        body = "#!/bin/sh\nexec " + " ".join("'" + c.replace("'", "'\\''") + "'" for c in command) + ' "$@"\n'
    if not os.path.isfile(path) or open(path, encoding="utf-8").read() != body:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        if sys.platform != "win32":
            os.chmod(path, 0o700)
    return path


def option_path(path: str) -> str:
    """A file name as the value of an ``-o`` option: ssh reads the option like a line of its config file, so a name with a space must be
    in quotes, and forward slashes are understood on every system (a backslash would be an escape)."""
    text = path.replace(chr(92), "/")
    return f'"{text}"' if any(ch.isspace() for ch in text) else text


def short_path(path: str) -> str:
    """On Windows the 8.3 form of a path with a space in it (ssh starts its password helper from a plain command line); else as is."""
    if sys.platform != "win32" or not any(ch.isspace() for ch in path):
        return path
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(520)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, 520)
        return buffer.value if 0 < n < 520 else path
    except Exception:   # noqa: BLE001 -- the long form is still the best guess
        return path


def ssh_command(c: Connection, known_hosts: str, subsystem: str = "sftp", *, with_password: bool = False, shell: bool = False) -> list:
    """The ``ssh`` command line that runs ``subsystem`` of the server (``-s``): strict host-key checking against Dossier's file only."""
    exe = find_tool("ssh")
    if not exe:
        raise ConnectError("OpenSSH is not installed on this computer (the ssh program was not found). On Windows it is an optional "
                           "feature: Settings > System > Optional features > OpenSSH Client")
    cmd = [exe, "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={option_path(known_hosts)}", "-o", f"GlobalKnownHostsFile={option_path(os.devnull)}",
           "-o", "HashKnownHosts=no", "-o", f"ConnectTimeout={CONNECT_TIMEOUT}", "-o", "ServerAliveInterval=15",
           "-o", "ServerAliveCountMax=4", "-o", "NumberOfPasswordPrompts=1", "-o", "LogLevel=ERROR", "-p", str(c.port)]
    if not with_password:
        cmd += ["-o", "BatchMode=yes"]
    if c.key_file:
        cmd += ["-i", c.key_file, "-o", "IdentitiesOnly=yes"]
    target = f"{c.user}@{c.host}" if c.user else c.host
    cmd += ["-T", target, "sh"] if shell else ["-s", target, subsystem]       # a shell to send commands to, or the server's SFTP service
    return cmd


def session_command(c: Connection, known_hosts: str, remote_dir: str = "") -> list:
    """The ``ssh`` command line of an interactive session on the server, opened in ``remote_dir`` (a terminal window runs it).

    The same strict host-key check as a file connection (only Dossier's own known-hosts file, a key the owner approved), no ``BatchMode``
    and no password helper: ssh asks for a password itself, in the terminal window, where it is typed by the owner and never seen by
    Dossier. Key files and the ssh-agent log in without one."""
    exe = find_tool("ssh")
    if not exe:
        raise ConnectError("OpenSSH is not installed on this computer (the ssh program was not found). On Windows it is an optional "
                           "feature: Settings > System > Optional features > OpenSSH Client")
    if any(ch in remote_dir for ch in (chr(0), chr(13), chr(10))):
        raise ConnectError("a folder name with a line break cannot be used for a session")
    cmd = [exe, "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={option_path(known_hosts)}", "-o", f"GlobalKnownHostsFile={option_path(os.devnull)}",
           "-o", "HashKnownHosts=no", "-o", f"ConnectTimeout={CONNECT_TIMEOUT}", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
           "-p", str(c.port)]
    if c.key_file:
        cmd += ["-i", c.key_file, "-o", "IdentitiesOnly=yes"]
    cmd += ["-t", f"{c.user}@{c.host}" if c.user else c.host]
    if remote_dir:
        cmd.append("cd " + shlex.quote(remote_dir) + ' && exec "${SHELL:-/bin/sh}" -l')       # the server's own shell for this user, as a login shell
    return cmd


def environment(shim: str, password: str) -> dict:
    env = dict(os.environ)
    env["SSH_ASKPASS"] = short_path(shim)
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env.setdefault("DISPLAY", "dossier")                 # older OpenSSH only runs the helper when it believes there is a display
    env[VARIABLE] = password
    return env


def friendly(stderr: str) -> str:
    """A plain sentence for what ssh said on its error stream."""
    text = (stderr or "").strip()
    low = text.lower()
    if not text:
        return ""
    table = (("permission denied", "The server refused the login: the user name, the password or the key is wrong"),
             ("host key verification failed", "The server's host key is not one you have approved"),
             ("remote host identification has changed", "The server's host key has changed: it may be a different computer"),
             ("could not resolve hostname", "There is no computer with that name (check the spelling and your network)"),
             ("name or service not known", "There is no computer with that name (check the spelling and your network)"),
             ("connection timed out", "The server did not answer in time (is it switched on, and the port open?)"),
             ("operation timed out", "The server did not answer in time (is it switched on, and the port open?)"),
             ("connection refused", "The server refused the connection (is an SSH server running on that port?)"),
             ("no route to host", "There is no route to the server (check your network or VPN)"),
             ("network is unreachable", "The network cannot reach the server (check your network or VPN)"),
             ("subsystem request failed", "The server has no SFTP service for this account"),
             ("too many authentication failures", "The server stopped after too many keys were tried"),
             ("no such file or directory", "A key file or program was not found: " + text.splitlines()[-1]))
    for needle, sentence in table:
        if needle in low:
            return sentence
    return text.splitlines()[-1]


# connecting --------------------------------------------------------------------------------------------------------------------------
class Link:
    """A running ``ssh`` process and the SFTP client on its pipes."""

    def __init__(self, process: subprocess.Popen, client: SftpClient, stderr: "list") -> None:
        self.process, self.client, self._stderr = process, client, stderr

    def error_text(self) -> str:
        return friendly("".join(self._stderr))


def _drain(stream, sink: list) -> None:
    try:
        for chunk in iter(lambda: stream.read(512), b""):
            sink.append(chunk.decode("utf-8", "replace"))
            while sum(len(s) for s in sink) > STDERR_KEEP:
                sink.pop(0)
    except (OSError, ValueError):
        pass


def connect(c: Connection, password: str, known_hosts: str, askpass_folder: str, timeout: int = CONNECT_TIMEOUT + 5) -> Link:
    """Start ``ssh -s sftp`` for ``c`` and shake hands. Raises ``ConnectError`` with a sentence for the owner on any failure."""
    shell = c.protocol == "scp"
    cmd = ssh_command(c, known_hosts, "sftp", with_password=bool(password), shell=shell)
    env = environment(askpass_shim(askpass_folder), password)
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                   creationflags=no_window())
    except OSError as e:
        raise ConnectError(f"ssh could not be started: {e}")
    errors: list = []
    threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True, name="ssh-stderr").start()
    watchdog = threading.Timer(timeout, process.kill)
    watchdog.start()

    def stop() -> None:
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    try:
        client = (ShellClient if shell else SftpClient)(process.stdout, process.stdin, stop)
    except (ConnectionError, OSError):
        watchdog.cancel()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        text = "".join(errors)
        raise ConnectError(friendly(text) or "The connection could not be made (no answer from the server)",
                           "auth" if "permission denied" in text.lower() else "")
    watchdog.cancel()
    return Link(process, client, errors)
