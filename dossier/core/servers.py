"""The servers the owner has saved: where they are, how to log in, whether writing is allowed. No secrets in here.

A saved connection holds the host, port, user and protocol, an optional key file and start folder, and two choices: *read-only* (the
default: nothing can be changed on the server until the owner switches it off for that connection) and *remember the password*. The
password itself is never written to the settings file, a log or an address: it goes to the system's password store (the Windows
credential manager, the macOS keychain, the Linux secret service) through ``keyring``, and only when the owner asked for that; otherwise
it is asked for at each connect. Qt-free.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

PROTOCOLS = (("sftp", "SFTP (the server's file service, over SSH)"),
             ("scp", "SCP (a shell over SSH, for servers that have no SFTP service)"),
             ("webdav", "WebDAV (a web folder, over HTTPS or HTTP)"),
             ("ftp", "FTP or FTPS (the old file transfer service)"))
NAMES = {"sftp": "SFTP", "scp": "SCP", "webdav": "WebDAV", "ftp": "FTP"}
DEFAULT_PORT = 22
SERVICE = "Dossier"
MAX_CONNECTIONS = 200


def default_port(protocol: str, secure: bool = True) -> int:
    if protocol == "ftp":
        return 21                                              # FTPS here is explicit TLS on the same port
    return (443 if secure else 80) if protocol == "webdav" else DEFAULT_PORT


@dataclass
class Connection:
    name: str
    host: str
    user: str = ""
    port: int = DEFAULT_PORT
    protocol: str = "sftp"
    key_file: str = ""
    start_dir: str = ""
    read_only: bool = True
    save_password: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    secure: bool = True                # WebDAV: HTTPS (else plain HTTP, where a password is sent in the clear)
    cert: str = ""                     # WebDAV: the fingerprint of a certificate the owner approved for this server

    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return (f"{self.user}@" if self.user else "") + host + (f":{self.port}" if self.port != default_port(self.protocol, self.secure) else "")

    def url(self, path: str = "/") -> str:
        return f"{self.protocol}://" + self.authority() + (path if path.startswith("/") else "/" + path)

    def describe(self) -> str:
        where = self.authority() + (self.start_dir if self.protocol == "webdav" and self.start_dir else "")
        plain = "  (not encrypted)" if self.protocol in ("webdav", "ftp") and not self.secure else ""
        name = "FTPS" if self.protocol == "ftp" and self.secure else NAMES.get(self.protocol, self.protocol)
        return f"{name}  {where}{plain}" + ("  (read-only)" if self.read_only else "")

    def problem(self) -> str:
        """Why this connection cannot be saved, or an empty string."""
        if not self.name.strip():
            return "give the connection a name"
        if not self.host.strip() or any(c in self.host for c in " /\\@"):
            return "the host is a name or an address, such as files.example.com"
        if not 1 <= int(self.port) <= 65535:
            return "the port is a number from 1 to 65535"
        if self.protocol not in dict(PROTOCOLS):
            return "choose SFTP or SCP"
        if any(c in self.user for c in " /\\@:"):
            return "the user name cannot hold spaces, slashes, colons or @"
        return ""


def parse_authority(authority: str) -> tuple:
    """``(user, host, port)`` of ``user@host:port`` (an IPv6 host is in brackets)."""
    user, at, rest = authority.rpartition("@")
    if not at:
        user, rest = "", authority
    if rest.startswith("["):
        host, _b, tail = rest[1:].partition("]")
        port = tail[1:] if tail.startswith(":") else ""
    else:
        host, _c, port = rest.partition(":")
    try:
        number = int(port) if port else DEFAULT_PORT
    except ValueError:
        number = DEFAULT_PORT
    return user, host, number


def from_url(text: str) -> Optional[dict]:
    """The parts of an address such as ``https://cloud.example.com:8443/remote.php/dav/files/me/`` or ``ftps://user@host/pub`` that a
    connection holds (``protocol``, ``host``, ``port``, ``secure``, ``user``, ``base``), or None when it is not an ``http``, ``https``,
    ``ftp`` or ``ftps`` address."""
    from urllib.parse import unquote, urlsplit
    try:
        parts = urlsplit(text.strip())
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https", "ftp", "ftps") or not parts.hostname:
            return None
        protocol = "ftp" if scheme.startswith("ftp") else "webdav"
        secure = scheme in ("https", "ftps")
        port = parts.port or default_port(protocol, secure)
    except ValueError:
        return None
    base = unquote(parts.path).rstrip("/")
    return {"protocol": protocol, "host": parts.hostname, "port": port, "secure": secure, "user": unquote(parts.username or ""),
            "base": base}


def to_json(connections: list) -> str:
    return json.dumps([c.__dict__ for c in connections[:MAX_CONNECTIONS]], ensure_ascii=False)


def from_json(text) -> list:
    """The saved connections; a damaged or foreign text is an empty list, never an error."""
    try:
        items = json.loads(text) if isinstance(text, str) and text.strip() else []
    except ValueError:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            c = Connection(str(item.get("name", "")), str(item.get("host", "")), str(item.get("user", "")),
                           int(item.get("port", DEFAULT_PORT)), str(item.get("protocol", "sftp")), str(item.get("key_file", "")),
                           str(item.get("start_dir", "")), bool(item.get("read_only", True)), bool(item.get("save_password", False)),
                           str(item.get("id") or uuid.uuid4().hex), bool(item.get("secure", True)), str(item.get("cert", "")))
        except (TypeError, ValueError):
            continue
        if not c.problem():
            out.append(c)
    return out


# passwords --------------------------------------------------------------------------------------------------------------------------
def _account(c: Connection) -> str:
    return f"{c.protocol}:{c.authority()}"


def get_password(c: Connection) -> str:
    """The password kept for ``c`` in the system's store, or an empty string (none kept, or no store on this computer)."""
    try:
        import keyring
        return keyring.get_password(SERVICE, _account(c)) or ""
    except Exception:   # noqa: BLE001 -- no password store is the same as no saved password
        return ""


def set_password(c: Connection, password: str) -> bool:
    try:
        import keyring
        keyring.set_password(SERVICE, _account(c), password)
        return True
    except Exception:   # noqa: BLE001
        return False


def forget_password(c: Connection) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, _account(c))
    except Exception:   # noqa: BLE001 -- nothing was kept
        pass


def find(connections: list, authority: str, protocol: str = "") -> Optional[Connection]:
    """The saved connection with this address (and kind, when given: the same address can be saved as SFTP and as SCP)."""
    return next((c for c in connections if c.authority() == authority and (not protocol or c.protocol == protocol)), None)
