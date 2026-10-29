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
             ("ftp", "FTP or FTPS (the old file transfer service)"),
             ("opds", "OPDS (a book catalogue: Calibre, Calibre-Web, Kavita, Komga; read-only)"),
             ("subsonic", "Subsonic (a music server: Navidrome, Airsonic, Gonic; read-only)"),
             ("gdrive", "Google Drive (you sign in with your Google account in the browser)"))
NAMES = {"sftp": "SFTP", "scp": "SCP", "webdav": "WebDAV", "ftp": "FTP", "opds": "OPDS", "subsonic": "Subsonic", "gdrive": "Google Drive"}
GDRIVE = "gdrive"
CLOUD = (GDRIVE,)                                  # cloud drives: signed in with OAuth in the browser; no host, port, user or password
GDRIVE_HINT = ("Google wants every program that opens your Drive to be registered once, by you: in the Google Cloud console create a "
               "project, switch on the Google Drive API, and make an OAuth client ID of the type Desktop app. Paste its client ID and "
               "client secret here. Google shows an 'unverified app' page the first time you sign in; for your own account that is "
               "expected: choose Advanced and continue. Dossier keeps only a sign-in token (in the system's password store); it never sees your "
               "Google password.")
NEXTCLOUD = "nextcloud"
PRESETS = ((NEXTCLOUD, "Nextcloud or ownCloud (a WebDAV web folder; the address of your files is filled in)"),)   # a preset is a WebDAV connection
APP_PASSWORD_HINT = ("Log in with an app password, not your main password: in Nextcloud open Settings > Security > Devices and sessions, "
                     "give the new app password a name such as Dossier, and copy it here. It works with two-factor login and can be "
                     "revoked there at any time.")
CATALOGS = ("opds", "subsonic")                    # web catalogues: always read-only, no key file, the "start in" is an address on the server
WEB = ("webdav", "ftp") + CATALOGS                 # kinds that have an encrypted (https, FTPS) and a plain form
DEFAULT_PORT = 22
SERVICE = "Dossier"
MAX_CONNECTIONS = 200


def default_port(protocol: str, secure: bool = True) -> int:
    if protocol == "ftp":
        return 21                                              # FTPS here is explicit TLS on the same port
    return (443 if secure else 80) if protocol == "webdav" or protocol in CATALOGS else DEFAULT_PORT


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
    preset: str = ""                   # "nextcloud": made from the Nextcloud preset (still a WebDAV connection; the start folder follows the user)
    client_id: str = ""                # a cloud drive: the id of the app the owner registered (public; its secret is in the password store)

    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return (f"{self.user}@" if self.user else "") + host + (f":{self.port}" if self.port != default_port(self.protocol, self.secure) else "")

    def url(self, path: str = "/") -> str:
        return f"{self.protocol}://" + self.authority() + (path if path.startswith("/") else "/" + path)

    def describe(self) -> str:
        if self.protocol in CLOUD:
            return NAMES[self.protocol] + ("  (read-only)" if self.read_only else "")
        shown_dir = self.start_dir if self.protocol in ("webdav",) + CATALOGS and self.start_dir and not self.preset else ""
        where = self.authority() + shown_dir
        plain = "  (not encrypted)" if self.protocol in WEB and not self.secure else ""
        name = "Nextcloud" if self.preset == NEXTCLOUD else "FTPS" if self.protocol == "ftp" and self.secure else NAMES.get(self.protocol, self.protocol)
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
        if self.protocol in CLOUD and not self.client_id.strip():
            return "paste the client ID of your Google app (see the note above)"
        if any(c in self.user for c in " /\\@:"):
            return "the user name cannot hold spaces, slashes, colons or @"
        if self.preset == NEXTCLOUD and not self.user.strip():
            return "Nextcloud needs your user name: it is part of the address of your files"
        return ""

    def force_rules(self) -> "Connection":
        """A catalogue is read-only whatever was asked."""
        if self.protocol in CATALOGS:
            self.read_only = True
        return self


def nextcloud_prefix(path: str) -> str:
    """The folder a Nextcloud lives in on its server, from any address of it: ``/nextcloud/index.php/apps/files/`` gives ``/nextcloud``, a
    server at the top gives an empty string."""
    path = "/" + path.strip().strip("/")
    for marker in ("/index.php", "/remote.php", "/apps/", "/f/", "/s/"):
        at = path.find(marker)
        if at >= 0:
            path = path[:at]
    return path.rstrip("/")


def nextcloud_start(prefix_or_address_path: str, user: str) -> str:
    """The WebDAV folder of ``user``'s files on a Nextcloud or ownCloud: ``<where it lives>/remote.php/dav/files/<user>``."""
    from urllib.parse import quote
    return nextcloud_prefix(prefix_or_address_path) + "/remote.php/dav/files/" + quote(user.strip(), safe="")


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
                           str(item.get("id") or uuid.uuid4().hex), bool(item.get("secure", True)), str(item.get("cert", "")),
                           str(item.get("preset", "")), str(item.get("client_id", "")))
        except (TypeError, ValueError):
            continue
        if not c.problem():
            out.append(c.force_rules())
    return out


# passwords --------------------------------------------------------------------------------------------------------------------------
def _account(c: Connection) -> str:
    return f"{c.protocol}:{c.authority()}"


def get_secret(account: str) -> str:
    """What the system's store keeps under ``account``, or an empty string (nothing kept, or no store on this computer)."""
    try:
        import keyring
        return keyring.get_password(SERVICE, account) or ""
    except Exception:   # noqa: BLE001 -- no password store is the same as no saved password
        return ""


def set_secret(account: str, value: str) -> bool:
    try:
        import keyring
        keyring.set_password(SERVICE, account, value)
        return True
    except Exception:   # noqa: BLE001
        return False


def forget_secret(account: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, account)
    except Exception:   # noqa: BLE001 -- nothing was kept
        pass


def get_password(c: Connection) -> str:
    """The password kept for ``c`` in the system's store, or an empty string. For a cloud drive it is the long-lasting sign-in token."""
    return get_secret(_account(c))


def set_password(c: Connection, password: str) -> bool:
    return set_secret(_account(c), password)


def forget_password(c: Connection) -> None:
    forget_secret(_account(c))


def client_secret_account(client_id: str) -> str:
    """Where the client secret of a cloud-drive app is kept (the id is public; the secret goes to the store, never to the settings)."""
    return f"{GDRIVE}-client:{client_id}"


def find(connections: list, authority: str, protocol: str = "") -> Optional[Connection]:
    """The saved connection with this address (and kind, when given: the same address can be saved as SFTP and as SCP)."""
    return next((c for c in connections if c.authority() == authority and (not protocol or c.protocol == protocol)), None)
