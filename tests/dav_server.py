"""A small WebDAV server for the tests: a folder served over HTTP (or HTTPS with a certificate of its own), in this process.

It does what the servers do that matter: PROPFIND with percent-encoded hrefs and collections that end in a slash, GET with ranges, PUT, MKCOL,
DELETE, MOVE with the ``Overwrite`` header, keep-alive, optional Basic or Digest login, and the redirect many servers give a folder asked for
without its final slash. ``log`` lists every request (method, path, headers), so a test can see what the client really sent. The login check
for Digest uses the formula of ``davclient.digest_response``, which the tests check separately against the example of the RFC.
"""
from __future__ import annotations

import base64
import os
import shutil
import socket
import ssl
import subprocess
import threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit as urlparse
from xml.sax.saxutils import escape

from dossier.core import davclient


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    # helpers --------------------------------------------------------------------------------------------------------------------------
    @property
    def dav(self) -> "DavServer":
        return self.server.dav

    def local(self, url_path: str) -> str:
        parts = [p for p in unquote(urlparse(url_path).path).split("/") if p and p != ".."]
        return os.path.join(self.dav.root, *parts)

    def send(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def authorised(self) -> bool:
        n = int(self.headers.get("Content-Length") or 0)
        self.data = self.rfile.read(n) if n else b""                  # read first: an answer sent over an unread body breaks keep-alive
        self.dav.log.append((self.command, self.path, dict(self.headers)))
        if not self.dav.users:
            return True
        header = self.headers.get("Authorization", "")
        if self.dav.auth == "basic" and header.startswith("Basic "):
            user, _c, password = base64.b64decode(header[6:]).decode().partition(":")
            if self.dav.users.get(user) == password:
                return True
        if self.dav.auth == "digest" and header.startswith("Digest "):
            fields = davclient.parse_challenge(header)
            challenge = {"realm": "dossier", "nonce": self.dav.nonce, "qop": "auth", "algorithm": fields.get("algorithm", "MD5")}
            user = fields.get("username", "")
            if user in self.dav.users and fields.get("nonce") == self.dav.nonce:
                expected = davclient.digest_response(user, self.dav.users[user], self.command, fields.get("uri", ""), challenge,
                                                     int(fields.get("nc", "1"), 16), fields.get("cnonce", ""))
                if davclient.parse_challenge(expected).get("response") == fields.get("response"):
                    return True
        challenge = ('Basic realm="dossier"' if self.dav.auth == "basic" else
                     f'Digest realm="dossier", nonce="{self.dav.nonce}", qop="auth", algorithm=MD5')
        self.send(401, b"", {"WWW-Authenticate": challenge})
        return False

    def body(self) -> bytes:
        return self.data

    def href(self, path: str) -> str:
        rel = os.path.relpath(path, self.dav.root).replace(os.sep, "/")
        url = "/" if rel == "." else "/" + quote(rel)
        if os.path.isdir(path) and not url.endswith("/"):
            url += "/"
        return url

    def response_xml(self, path: str) -> str:
        st = os.stat(path)
        is_dir = os.path.isdir(path)
        props = ("<d:resourcetype><d:collection/></d:resourcetype>" if is_dir else
                 f"<d:resourcetype/><d:getcontentlength>{st.st_size}</d:getcontentlength>")
        props += f"<d:getlastmodified>{formatdate(st.st_mtime, usegmt=True)}</d:getlastmodified>"
        href = self.href(path)
        if self.dav.absolute_hrefs:
            href = f"http://{self.headers.get('Host')}{href}"
        return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>{props}</d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

    # the methods ------------------------------------------------------------------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        if self.authorised():
            self.send(200, b"", {"DAV": "1", "Allow": "OPTIONS, GET, PUT, PROPFIND, MKCOL, DELETE, MOVE"})

    def do_PROPFIND(self) -> None:
        if not self.authorised():
            return
        self.body()
        path = self.local(self.path)
        if not os.path.exists(path):
            return self.send(404)
        if self.dav.redirect_dirs and os.path.isdir(path) and not urlparse(self.path).path.endswith("/") and urlparse(self.path).path != "":
            return self.send(301, b"", {"Location": urlparse(self.path).path + "/"})
        parts = [self.response_xml(path)]
        if os.path.isdir(path) and self.headers.get("Depth", "1") != "0":
            parts += [self.response_xml(os.path.join(path, n)) for n in sorted(os.listdir(path))]
        xml = '<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">' + "".join(parts) + "</d:multistatus>"
        self.send(207, xml.encode("utf-8"), {"Content-Type": 'application/xml; charset="utf-8"'})

    def do_GET(self) -> None:
        if not self.authorised():
            return
        path = self.local(self.path)
        if not os.path.isfile(path):
            return self.send(404)
        size = os.path.getsize(path)
        rng = self.headers.get("Range", "")
        with open(path, "rb") as f:
            if rng.startswith("bytes=") and self.dav.ranges:
                first, _d, last = rng[6:].partition("-")
                start = int(first)
                end = min(int(last) if last else size - 1, size - 1)
                f.seek(start)
                data = f.read(end - start + 1)
                return self.send(206, data, {"Content-Range": f"bytes {start}-{end}/{size}"})
            self.send(200, f.read())

    do_HEAD = do_GET

    def do_PUT(self) -> None:
        if not self.authorised():
            return
        data = self.body()
        path = self.local(self.path)
        if not os.path.isdir(os.path.dirname(path)):
            return self.send(409)
        if self.headers.get("If-None-Match") == "*" and os.path.exists(path):
            return self.send(412)
        existed = os.path.exists(path)
        with open(path, "wb") as f:
            f.write(data)
        self.send(204 if existed else 201)

    def do_MKCOL(self) -> None:
        if not self.authorised():
            return
        path = self.local(self.path)
        if os.path.exists(path):
            return self.send(405)
        if not os.path.isdir(os.path.dirname(path)):
            return self.send(409)
        os.mkdir(path)
        self.send(201)

    def do_DELETE(self) -> None:
        if not self.authorised():
            return
        path = self.local(self.path)
        if not os.path.exists(path):
            return self.send(404)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        self.send(204)

    def do_MOVE(self) -> None:
        if not self.authorised():
            return
        src = self.local(self.path)
        dst = self.local(self.headers.get("Destination", ""))
        if not os.path.exists(src):
            return self.send(404)
        existed = os.path.exists(dst)
        if existed and self.headers.get("Overwrite", "T") == "F":
            return self.send(412)
        if existed:
            shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
        os.replace(src, dst)
        self.send(204 if existed else 201)


class DavServer:
    def __init__(self, root: str, *, users: dict | None = None, auth: str = "basic", ranges: bool = True, redirect_dirs: bool = False,
                 absolute_hrefs: bool = False, certfile: str = "", keyfile: str = "") -> None:
        self.root, self.users, self.auth = root, users or {}, auth
        self.ranges, self.redirect_dirs, self.absolute_hrefs = ranges, redirect_dirs, absolute_hrefs
        self.nonce = os.urandom(8).hex()
        self.log: list = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.dav = self
        self.secure = bool(certfile)
        if certfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile, keyfile)
            self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="test-dav")
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def methods(self) -> list:
        return [m for m, _p, _h in self.log]


def make_certificate(folder, host: str = "127.0.0.1"):
    """A self-signed certificate for ``host`` made with ``openssl`` (None when there is no openssl on this computer)."""
    exe = shutil.which("openssl")
    if not exe:
        return None
    cert, key = os.path.join(str(folder), "cert.pem"), os.path.join(str(folder), "key.pem")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    san = f"IP:{host}" if host.replace(".", "").isdigit() else f"DNS:{host}"
    done = subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2",
                           "-subj", f"/CN={host}", "-addext", f"subjectAltName={san}"], capture_output=True, creationflags=flags)
    if done.returncode != 0 or not os.path.isfile(cert):
        return None
    der = ssl.PEM_cert_to_DER_cert(open(cert).read())
    return cert, key, davclient.fingerprint_of(der)
