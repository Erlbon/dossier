"""A WebDAV client over HTTP or HTTPS. Standard library only (``http.client``, ``ssl``, ``xml``).

It offers the same calls as ``SftpClient`` (``listdir``, ``stat``, ``open``, ``read_blocks``...), so ``SftpFileSystem`` and everything above it
work on a WebDAV server unchanged. A server is a base address (host, port, TLS or not) and the paths below it.

* **TLS is checked.** The system's certificate store decides. A server with a certificate of its own (a NAS, a home server) can be trusted
  by pinning its fingerprint: the owner is shown the SHA-256 fingerprint and says yes once; from then on the connection is allowed only
  when the server shows exactly that certificate, so a changed certificate stops the connection (``CertificateChanged``).
* **Login:** Basic and Digest (MD5 and SHA-256). A password over plain HTTP is sent in the clear; the window says so.
* **Safe to parse:** a reply with a DOCTYPE or entity declaration is refused (the "billion laughs" attack) and a reply is capped in size.
* **Reads** use ranges (any size, any starting point); **writes** are collected in a temporary file and sent in one PUT when the file is
  closed, which is how WebDAV works. A folder is deleted only when it is empty (DELETE on a collection removes everything in it on the
  server, so the recursion stays in the operations layer, where it is planned and confirmed).
* A server does not take the modified time of an uploaded file: ``set_mtime`` does nothing.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import http.client
import re
import secrets
import socket
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

from .sftp_proto import EXCL_FLAG, FAILURE, NO_SUCH_FILE, PERMISSION_DENIED, S_IFDIR, S_IFREG, WRITE_FLAG, Attrs, Name, SftpError, error_for

DAV = "{DAV:}"
MAX_REPLY = 64 * 1024 * 1024
BLOCK = 1024 * 1024
TIMEOUT = 30
MAX_REDIRECTS = 4
PROPFIND_BODY = (b'<?xml version="1.0" encoding="utf-8"?><propfind xmlns="DAV:"><prop><resourcetype/><getcontentlength/>'
                 b'<getlastmodified/></prop></propfind>')


class CertificateError(ConnectionError):
    """The server's certificate is not trusted (``fingerprint`` is what it showed, for the owner to judge)."""

    def __init__(self, message: str, fingerprint: str = "", changed: bool = False) -> None:
        super().__init__(message)
        self.fingerprint = fingerprint
        self.changed = changed


class AuthError(PermissionError):
    """The server wants a login (or refused the one given)."""


def fingerprint_of(der: bytes) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode().rstrip("=")


def fetch_fingerprint(host: str, port: int, timeout: float = 10.0) -> str:
    """The fingerprint of the certificate a server shows, whether or not it is trusted (for the owner to look at)."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return fingerprint_of(tls.getpeercert(binary_form=True) or b"")


# Digest login (RFC 7616; the 2617 form without a hash name is MD5) -----------------------------------------------------------------------
def parse_challenge(header: str) -> dict:
    """``{"scheme": "digest", "realm": ..., "nonce": ...}`` from a ``WWW-Authenticate`` value."""
    scheme, _space, rest = header.strip().partition(" ")
    fields = {k.lower(): (v1 or v2) for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', rest)}
    fields["scheme"] = scheme.lower()
    return fields


def digest_response(user: str, password: str, method: str, uri: str, challenge: dict, nc: int, cnonce: str) -> str:
    algorithm = challenge.get("algorithm", "MD5").upper().replace("-SESS", "")
    h = (lambda text: hashlib.sha256(text.encode()).hexdigest()) if algorithm == "SHA-256" else \
        (lambda text: hashlib.md5(text.encode()).hexdigest())             # noqa: S324 -- the protocol asks for MD5
    realm, nonce = challenge.get("realm", ""), challenge.get("nonce", "")
    ha1 = h(f"{user}:{realm}:{password}")
    if challenge.get("algorithm", "").upper().endswith("-SESS"):
        ha1 = h(f"{ha1}:{nonce}:{cnonce}")
    ha2 = h(f"{method}:{uri}")
    qops = [q.strip() for q in challenge.get("qop", "").split(",") if q.strip()]
    if "auth" in qops:
        value = h(f"{ha1}:{nonce}:{nc:08x}:{cnonce}:auth:{ha2}")
    else:
        value = h(f"{ha1}:{nonce}:{ha2}")
    parts = [f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"', f'response="{value}"']
    if "auth" in qops:
        parts += ["qop=auth", f"nc={nc:08x}", f'cnonce="{cnonce}"']
    if challenge.get("opaque"):
        parts.append(f'opaque="{challenge["opaque"]}"')
    if challenge.get("algorithm"):
        parts.append(f'algorithm={challenge["algorithm"]}')
    return "Digest " + ", ".join(parts)


@dataclass
class Reply:
    status: int
    headers: dict
    body: bytes = b""

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


def _parse_multistatus(data: bytes) -> list:
    """``[(path, Attrs)]`` of the responses of a PROPFIND; the path is decoded and has no trailing slash (except the root)."""
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data[:65536].lower():
        raise SftpError(FAILURE, "the server's reply was refused (it holds a document type declaration)")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as e:
        raise SftpError(FAILURE, f"the server's reply is not valid XML ({e})")
    out = []
    for response in root.iter(f"{DAV}response"):
        href = (response.findtext(f"{DAV}href") or "").strip()
        if not href:
            continue
        path = unquote(urlparse(href).path) or "/"
        attrs = Attrs(perm=S_IFREG | 0o644, flags=1 | 4 | 8)
        for propstat in response.findall(f"{DAV}propstat"):
            if " 200 " not in " " + (propstat.findtext(f"{DAV}status") or "200") + " ":
                continue
            prop = propstat.find(f"{DAV}prop")
            if prop is None:
                continue
            kind = prop.find(f"{DAV}resourcetype")
            if kind is not None and kind.find(f"{DAV}collection") is not None:
                attrs.perm = S_IFDIR | 0o755
            length = prop.findtext(f"{DAV}getcontentlength")
            if length and length.strip().isdigit():
                attrs.size = int(length)
            modified = prop.findtext(f"{DAV}getlastmodified")
            if modified:
                try:
                    attrs.mtime = attrs.atime = int(parsedate_to_datetime(modified).timestamp())
                except (TypeError, ValueError):
                    pass
        out.append((path if path == "/" else path.rstrip("/"), attrs))
    return out


class DavClient:
    def __init__(self, host: str, port: int, secure: bool = True, user: str = "", password: str = "", pinned: str = "",
                 timeout: float = TIMEOUT) -> None:
        self.host, self.port, self.secure = host, port, secure
        self.user, self.password, self.pinned = user, password, pinned
        self.timeout = timeout
        self.closed = False
        self.version = 0
        self.extensions: dict = {}
        self._lock = threading.RLock()
        self._conn: Optional[http.client.HTTPConnection] = None
        self._auth: Optional[dict] = None             # what the server asked for: {"scheme": "basic"|"digest", ...}
        self._nc = 0
        self._handles: dict = {}
        self._next = 0
        self.peer_fingerprint = ""

    # the connection ---------------------------------------------------------------------------------------------------------------
    def _open(self) -> http.client.HTTPConnection:
        if not self.secure:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            conn.connect()
            return conn
        context = ssl.create_default_context()
        if self.pinned:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE         # the pinned fingerprint is checked below instead of the chain of trust
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=context)
        try:
            conn.connect()
        except ssl.SSLCertVerificationError as e:
            try:
                shown = fetch_fingerprint(self.host, self.port, self.timeout)
            except (OSError, ssl.SSLError):
                shown = ""
            raise CertificateError(f"the server's certificate is not trusted ({getattr(e, 'verify_message', None) or e})", shown)
        except ssl.SSLError as e:
            raise ConnectionError(f"the secure connection could not be made ({e})")
        der = conn.sock.getpeercert(binary_form=True) or b""
        self.peer_fingerprint = fingerprint_of(der)
        if self.pinned and self.peer_fingerprint != self.pinned:
            conn.close()
            raise CertificateError("the server's certificate is not the one you approved", self.peer_fingerprint, changed=True)
        return conn

    def close(self) -> None:
        self.closed = True
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except OSError:
                    pass
                self._conn = None
            for state in self._handles.values():
                if state.get("temp") is not None:
                    state["temp"].close()
            self._handles.clear()

    def connect(self) -> None:
        """Open the connection and check the login (a PROPFIND on the root); raises ``CertificateError``, ``AuthError``..."""
        self.stat("/")

    # one request ------------------------------------------------------------------------------------------------------------------------
    def _authorization(self, method: str, target: str) -> Optional[str]:
        if not self.user or self._auth is None:
            return None
        if self._auth["scheme"] == "basic":
            token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode("ascii")
            return "Basic " + token
        if self._auth["scheme"] == "digest":
            self._nc += 1
            return digest_response(self.user, self.password, method, target, self._auth, self._nc, secrets.token_hex(8))
        return None

    def request(self, method: str, path: str, body=None, headers: Optional[dict] = None, *, length: Optional[int] = None,
                want: tuple = ()) -> Reply:
        """One HTTP request and its whole (capped) answer. Follows redirects, logs in when asked, reconnects once when the server dropped
        an idle connection. A status in ``want`` is returned; any other error status is raised as the matching ``OSError``."""
        target = quote(path if path.startswith("/") else "/" + path, safe="/~!$&'()*+,;=:@-._")
        with self._lock:
            redirects, logins = 0, 0
            while True:
                reply = self._send(method, target, body, dict(headers or {}), length)
                stale = parse_challenge(reply.header("www-authenticate")).get("stale", "").lower() == "true" if reply.status == 401 else False
                if reply.status == 401 and (logins == 0 or (stale and logins < 3)):
                    challenge = reply.header("www-authenticate")
                    if not self.user or not challenge:
                        raise AuthError(errno.EACCES, "the server wants a login")
                    options = [c.strip() for c in re.split(r",\s*(?=(?:basic|digest)\b)", challenge, flags=re.I)]
                    chosen = next((parse_challenge(c) for c in options if c.lower().startswith("digest")), None) or \
                        next((parse_challenge(c) for c in options if c.lower().startswith("basic")), None)
                    if chosen is None:
                        raise AuthError(errno.EACCES, "the server wants a kind of login this program does not know")
                    self._auth, logins = chosen, logins + 1
                    if hasattr(body, "seek"):
                        body.seek(0)
                    continue
                if reply.status in (301, 302, 307, 308) and redirects < MAX_REDIRECTS and reply.header("location"):
                    where = urlparse(reply.header("location"))
                    if where.netloc and where.netloc.split(":")[0].lower() != self.host.lower():
                        raise SftpError(FAILURE, "the server redirects to another computer; add that address as a server instead")
                    target = where.path + (f"?{where.query}" if where.query else "") or target
                    redirects += 1
                    if hasattr(body, "seek"):
                        body.seek(0)
                    continue
                break
        if reply.status == 401:
            raise AuthError(errno.EACCES, "the server refused the login: the user name or the password is wrong")
        if reply.status in want or 200 <= reply.status < 300:
            return reply
        raise self._error(reply, path)

    def _send(self, method: str, target: str, body, headers: dict, length: Optional[int]) -> Reply:
        if self.closed:
            raise ConnectionError("the connection to the server was closed")
        headers.setdefault("User-Agent", "Dossier")
        headers.setdefault("Accept-Encoding", "identity")
        for attempt in (1, 2):
            if self._conn is None:
                self._conn = self._open()
            auth = self._authorization(method, target)
            if auth:
                headers["Authorization"] = auth
            if length is not None:
                headers["Content-Length"] = str(length)
            try:
                self._conn.request(method, target, body=body, headers=headers)
                response = self._conn.getresponse()
                data = response.read(MAX_REPLY + 1) if method != "HEAD" else b""
                if len(data) > MAX_REPLY:
                    raise SftpError(FAILURE, "the server's reply is too big")
                if response.getheader("Connection", "").lower() == "close" or response.will_close:
                    self._conn.close()
                    self._conn = None
                return Reply(response.status, {k.lower(): v for k, v in response.getheaders()}, data)
            except (http.client.HTTPException, ConnectionError, socket.timeout, ssl.SSLError, OSError) as e:
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
                repeatable = body is None or isinstance(body, (bytes, bytearray)) or hasattr(body, "seek")
                if isinstance(e, (CertificateError, SftpError)) or attempt == 2 or not repeatable:
                    if isinstance(e, (socket.timeout, TimeoutError)):
                        raise ConnectionError("the server did not answer in time")
                    raise ConnectionError(f"the connection to the server was lost ({e})") if not isinstance(e, (CertificateError, SftpError)) else e
                if hasattr(body, "seek"):
                    body.seek(0)
        raise ConnectionError("the connection to the server was lost")

    @staticmethod
    def _error(reply: Reply, path: str) -> OSError:
        s = reply.status
        if s in (404, 410):
            return error_for(NO_SUCH_FILE, "no such file", path)
        if s in (403, 423):
            return error_for(PERMISSION_DENIED, "the server does not allow it", path)
        if s in (405, 412) or s == 409:
            return FileExistsError(errno.EEXIST, "it already exists, or its folder does not", path) if s != 409 else \
                FileNotFoundError(errno.ENOENT, "the folder above it does not exist", path)
        if s in (507, 413):
            return OSError(errno.ENOSPC, "the server has no room for it", path)
        return SftpError(FAILURE, f"the server answered {s}", path)

    # whole-item calls ---------------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        return "/" if path in (".", "") else path

    def _propfind(self, path: str, depth: int) -> list:
        reply = self.request("PROPFIND", path, PROPFIND_BODY, {"Depth": str(depth), "Content-Type": "application/xml"}, length=len(PROPFIND_BODY),
                             want=(207,))
        return _parse_multistatus(reply.body)

    def stat(self, path: str, follow: bool = True) -> Attrs:
        want = path if path == "/" else path.rstrip("/")
        found = self._propfind(path, 0)
        if not found:
            raise error_for(NO_SUCH_FILE, "no such file", path)
        return next((a for p, a in found if p == want), found[0][1])

    def listdir(self, path: str) -> list:
        base = path if path == "/" else path.rstrip("/")
        found = self._propfind(path if path.endswith("/") else path + "/", 1)
        out = []
        for p, attrs in found:
            if p == base or p == base + "/":
                continue                                           # the folder itself
            name = p.rsplit("/", 1)[-1]
            if name:
                out.append(Name(name, "", attrs))
        return out

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        self.request("MKCOL", path)

    def rmdir(self, path: str) -> None:
        if self.listdir(path):
            raise OSError(errno.ENOTEMPTY, "the folder is not empty", path)
        self.request("DELETE", path)

    def remove(self, path: str) -> None:
        self.request("DELETE", path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        scheme = "https" if self.secure else "http"
        port = "" if (self.secure and self.port == 443) or (not self.secure and self.port == 80) else f":{self.port}"
        destination = f"{scheme}://{self.host}{port}" + quote(new if new.startswith("/") else "/" + new, safe="/~!$&'()*+,;=:@-._")
        self.request("MOVE", old, headers={"Destination": destination, "Overwrite": "T" if overwrite else "F"})

    def set_mtime(self, path: str, mtime: float) -> None:
        return None                                                # a server dates a file when it is uploaded

    def readlink(self, path: str) -> str:
        raise OSError(errno.EINVAL, "WebDAV has no links", path)

    # contents -----------------------------------------------------------------------------------------------------------------------------
    def open(self, path: str, flags: int) -> bytes:
        with self._lock:
            self._next += 1
            handle = str(self._next).encode()
            if flags & WRITE_FLAG:
                if flags & EXCL_FLAG:
                    try:
                        self.stat(path)
                    except FileNotFoundError:
                        pass
                    else:
                        raise SftpError(FAILURE, "the file already exists", path)
                self._handles[handle] = {"path": path, "temp": tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024), "size": 0}
            else:
                attrs = self.stat(path)
                if attrs.is_dir:
                    raise error_for(NO_SUCH_FILE, "it is a folder", path)
                self._handles[handle] = {"path": path, "temp": None, "size": attrs.size}
            return handle

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        state = self._handles.get(handle)
        file = state["path"] if state else path
        size = state["size"] if state else offset + count
        if offset >= size:
            return b""
        last = min(offset + count, size) - 1
        reply = self.request("GET", file, headers={"Range": f"bytes={offset}-{last}"}, want=(200, 206))
        if reply.status == 206:
            return reply.body
        return reply.body[offset:offset + count]                   # the server ignored the range and sent everything

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        state = self._handles[handle]
        if offset != state["size"]:
            raise OSError(errno.EINVAL, "a WebDAV file can only be written from its start, in order", state["path"])
        state["temp"].write(data)
        state["size"] += len(data)

    def close_handle(self, handle: bytes) -> None:
        state = self._handles.pop(handle, None)
        if state is None or state["temp"] is None:
            return
        temp = state["temp"]
        try:
            temp.seek(0)
            self.request("PUT", state["path"], temp, {"Content-Type": "application/octet-stream"}, length=state["size"])
        finally:
            temp.close()
