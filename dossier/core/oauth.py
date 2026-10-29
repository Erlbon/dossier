"""Signing in to a web service with OAuth 2 from a desktop program (the "installed application" flow). Standard library only, Qt-free.

1. ``begin`` makes a one-time secret (the PKCE verifier) and the address of the service's sign-in page; the caller opens it in the
   owner's own browser, so the owner types the password and answers the two-factor question there, never in Dossier.
2. ``wait_for_code`` listens on ``127.0.0.1`` (a free port, this computer only) for the browser being sent back with a code.
3. ``exchange`` trades the code for a *refresh token* and a short-lived *access token*.

The refresh token is all that is kept (in the system's password store, by the caller). Nothing runs in the background: when a drive is
opened again ``TokenSource`` trades the refresh token for a new access token in a moment, and when it is disconnected the token can
be thrown away. The web is reached through ``transport(method, url, headers, body) -> (status, headers, bytes)``, so a test needs no
network.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

TIMEOUT = 30
WAIT_SECONDS = 180                         # how long the browser sign-in may take


class OAuthError(PermissionError):
    """The sign-in failed or was refused (``code`` is the service's short reason, such as ``invalid_grant``)."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OAuthApp:
    """What the service knows this program by: the sign-in and token addresses, the client id (and the secret some services want even
    from a desktop program; it is not a real secret there), and what the program asks permission for."""
    auth_url: str
    token_url: str
    client_id: str
    client_secret: str = ""
    scopes: tuple = ()
    extra_auth: tuple = ()                 # more (name, value) pairs for the sign-in address, such as ("access_type", "offline")


@dataclass
class Begun:
    url: str                               # open this in the browser
    verifier: str
    state: str
    redirect_uri: str = ""


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")


def begin(app: OAuthApp, port: int) -> Begun:
    """The sign-in address for a browser that will be sent back to ``http://127.0.0.1:<port>``."""
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    redirect = f"http://127.0.0.1:{port}"
    query = [("client_id", app.client_id), ("redirect_uri", redirect), ("response_type", "code"), ("scope", " ".join(app.scopes)),
             ("code_challenge", _challenge(verifier)), ("code_challenge_method", "S256"), ("state", state)] + list(app.extra_auth)
    return Begun(app.auth_url + "?" + urllib.parse.urlencode(query), verifier, state, redirect)


_DONE_PAGE = (b"<html><head><meta charset='utf-8'><title>Dossier</title></head><body style='font-family:sans-serif;margin:3em'>"
              b"<h2>You are signed in.</h2><p>You can close this window and go back to Dossier.</p></body></html>")
_FAILED_PAGE = (b"<html><head><meta charset='utf-8'><title>Dossier</title></head><body style='font-family:sans-serif;margin:3em'>"
                b"<h2>The sign-in did not work.</h2><p>Go back to Dossier and try again.</p></body></html>")


class _Catcher(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:                                            # noqa: N802 -- the name http.server calls
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if not query.get("code") and not query.get("error"):             # the browser asking for an icon or the like
            self.send_response(404)
            self.end_headers()
            return
        self.server.answer = {k: v[0] for k, v in query.items()}         # type: ignore[attr-defined]
        ok = bool(query.get("code")) and not query.get("error")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(_DONE_PAGE if ok else _FAILED_PAGE)
        self.server.got.set()                                            # type: ignore[attr-defined]

    def log_message(self, *args) -> None:
        return None


class Listener:
    """The little web server that catches the browser coming back. ``port`` is known as soon as it exists, so the sign-in address can
    name it."""

    def __init__(self) -> None:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
        self.server.answer = {}                                         # type: ignore[attr-defined]
        self.server.got = threading.Event()                             # type: ignore[attr-defined]
        self.server.timeout = 0.2
        self.port = self.server.server_address[1]

    def wait(self, state: str, cancelled: Optional[Callable[[], bool]] = None, seconds: float = WAIT_SECONDS) -> str:
        """The code the browser brought. Raises ``OAuthError`` when the sign-in was refused, came back with the wrong state (another
        page, not ours), was cancelled, or took too long."""
        end = time.monotonic() + seconds
        try:
            while not self.server.got.is_set():                          # type: ignore[attr-defined]
                if cancelled is not None and cancelled():
                    raise OAuthError("the sign-in was cancelled", "cancelled")
                if time.monotonic() > end:
                    raise OAuthError("no answer from the browser: the sign-in took too long", "timeout")
                self.server.handle_request()
        finally:
            self.server.server_close()
        answer = self.server.answer                                     # type: ignore[attr-defined]
        if answer.get("error"):
            raise OAuthError(f"the service refused the sign-in ({answer['error']})", answer["error"])
        if answer.get("state") != state:
            raise OAuthError("the answer did not come from this sign-in", "state")
        return answer["code"]


def default_transport(method: str, url: str, headers: dict, body=None) -> tuple:
    """One web request. Returns ``(status, headers, bytes)`` for any answer, including an error status; raises ``ConnectionError`` when
    the service cannot be reached."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:                 # noqa: S310 -- https addresses of the service
            return reply.status, {k.lower(): v for k, v in reply.getheaders()}, reply.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ConnectionError(f"the service could not be reached ({getattr(e, 'reason', None) or e})")


def _token_call(app: OAuthApp, form: dict, transport: Callable) -> dict:
    fields = dict(form)
    fields["client_id"] = app.client_id
    if app.client_secret:
        fields["client_secret"] = app.client_secret
    status, _headers, data = transport("POST", app.token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                       urllib.parse.urlencode(fields).encode("ascii"))
    try:
        answer = json.loads(data.decode("utf-8")) if data else {}
    except ValueError:
        answer = {}
    if status != 200 or "access_token" not in answer:
        code = str(answer.get("error", ""))
        raise OAuthError(str(answer.get("error_description") or answer.get("error") or f"the service answered {status}"), code)
    return answer


@dataclass
class Tokens:
    refresh: str
    access: str = ""
    expires: float = 0.0                   # time.monotonic() when the access token stops working


def exchange(app: OAuthApp, begun: Begun, code: str, transport: Callable = default_transport) -> Tokens:
    answer = _token_call(app, {"grant_type": "authorization_code", "code": code, "redirect_uri": begun.redirect_uri,
                               "code_verifier": begun.verifier}, transport)
    if not answer.get("refresh_token"):
        raise OAuthError("the service gave no long-lasting sign-in (refresh token); try again and allow offline access", "no_refresh")
    return Tokens(answer["refresh_token"], answer["access_token"], time.monotonic() + float(answer.get("expires_in", 3600)))


def sign_in(app: OAuthApp, open_browser: Callable[[str], object], transport: Callable = default_transport,
            cancelled: Optional[Callable[[], bool]] = None, seconds: float = WAIT_SECONDS) -> Tokens:
    """The whole sign-in: listen, open the browser on the service's page, wait for the answer, trade the code for tokens."""
    listener = Listener()
    try:
        begun = begin(app, listener.port)
        open_browser(begun.url)
        code = listener.wait(begun.state, cancelled, seconds)
    except BaseException:
        listener.server.server_close()
        raise
    return exchange(app, begun, code, transport)


class TokenSource:
    """Hands out an access token that works: the one it has while it is fresh, else a new one made from the refresh token."""

    SLACK = 60                              # renew this many seconds before the token runs out

    def __init__(self, app: OAuthApp, tokens: Tokens, transport: Callable = default_transport) -> None:
        self.app, self.tokens, self.transport = app, tokens, transport
        self._lock = threading.Lock()

    def access(self, force: bool = False) -> str:
        with self._lock:
            t = self.tokens
            if force or not t.access or time.monotonic() > t.expires - self.SLACK:
                answer = _token_call(self.app, {"grant_type": "refresh_token", "refresh_token": t.refresh}, self.transport)
                t.access = answer["access_token"]
                t.expires = time.monotonic() + float(answer.get("expires_in", 3600))
                if answer.get("refresh_token"):                          # some services rotate it
                    t.refresh = answer["refresh_token"]
            return t.access
