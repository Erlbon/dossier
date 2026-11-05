"""Server folders for the assistant: the SFTP and SCP folders the owner listed in Settings > Assistant Access.

The server connects to them itself, the way the window does (``core/sshlink.py``: the system's ``ssh``), but it never asks anything:

* the connection must be one the owner saved in the window (the window copies it, without secrets, into the assistant's settings);
* its host key must already be approved in the window (Dossier's own ``known_hosts``); an unknown or changed key is refused;
* the login is a key file, an SSH agent, or the password the owner chose to keep in the system's password store. Nothing is typed;
* the connection's read-only switch is kept, so a read-only server cannot be changed whatever the assistant asks.

A failure is a sentence for the assistant to pass on; it never opens a dialog or reaches a host the owner did not list.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from ..core import servers
from ..core.sftpfs import Session, split_path
from .config import SERVER_SCHEMES


class RemoteError(Exception):
    """A server folder that cannot be reached, with a sentence for the assistant."""


class Remotes:
    def __init__(self) -> None:
        self._links: dict = {}
        self._lock = threading.Lock()

    def reconnect(self, config, scheme: str, authority: str):
        """A new Session for a server whose connection died mid-job (set as the file system's ``reconnect``): the same rules as ``ensure``,
        never a question."""
        from ..core import sshlink
        try:
            conn = self._connection(config, scheme, authority)
        except RemoteError:
            return None
        return sshlink.reconnect_saved(conn, config.ssh_folder, self._links)

    def ensure(self, fs, config, path: str) -> None:
        """Connect the server of ``path`` (already checked against the listed roots) if it is not connected yet."""
        scheme = path.split("://", 1)[0]
        if scheme not in SERVER_SCHEMES:
            raise RemoteError("only SFTP and SCP servers can be listed for an assistant")
        authority = split_path(path)[0]
        target = fs.scp if scheme == "scp" else fs.sftp
        target.reconnect = lambda auth, s=scheme: self.reconnect(config, s, auth)
        with self._lock:
            session = target.sessions.get(authority)
            if session is not None and session.alive:
                return
            conn = self._connection(config, scheme, authority)
            from ..core import sshlink
            folder = config.ssh_folder
            if not folder:
                raise RemoteError("open Settings > Assistant Access in Dossier and press Save once, so the server's settings reach the assistant")
            known = os.path.join(folder, "known_hosts")
            if not sshlink.KnownHosts(known).lookup(conn.host, conn.port):
                raise RemoteError(f"the host key of {conn.host} is not approved yet: connect to the server once in the Dossier window and check its key")
            password = servers.get_password(conn) if conn.save_password else ""
            try:
                link = sshlink.connect(conn, password, known, folder)
            except sshlink.ConnectError as e:
                raise RemoteError(f"{conn.name}: {e}")
            sshlink.add_commands(conn, link, password, known, folder)
            try:
                home = link.client.realpath(".")
            except OSError:
                home = "/"
            target.add_session(Session(authority, link.client, read_only=conn.read_only, home=home, scheme=scheme,
                                       commands=link.commands.client if link.commands is not None else None))
            self._links[(scheme, authority)] = link

    @staticmethod
    def _connection(config, scheme: str, authority: str) -> servers.Connection:
        import json
        conn = servers.find(servers.from_json(json.dumps(config.servers)), authority, scheme)
        if conn is None:
            raise RemoteError(f"{scheme}://{authority} is not a saved server: add it on the Home page in Dossier, then save Assistant Access again")
        return conn                                  # (the ssh processes end with the server: they are its children, on its pipes)


def server_paths(value) -> list:
    """Every string in a tool's arguments that names a server folder."""
    out = []
    if isinstance(value, str):
        if value.split("://", 1)[0] in SERVER_SCHEMES and "://" in value:
            out.append(value)
    elif isinstance(value, list):
        for v in value:
            out += server_paths(v)
    elif isinstance(value, dict):
        for v in value.values():
            out += server_paths(v)
    return out
