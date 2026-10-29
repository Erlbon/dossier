"""A Google Drive and its sign-in server in memory, as a ``transport(method, url, headers, body)``: enough of the real service for the
client, the sign-in and the window to be tested without a network."""
from __future__ import annotations

import json
import re
import urllib.parse

FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"
B = chr(92)


class FakeDrive:
    def __init__(self) -> None:
        self.files: dict = {}                  # id -> {"name", "mime", "parents", "data", "mtime", "trashed"}
        self.drives: dict = {}                 # id -> name
        self.shared: list = []                 # ids of files shared with the account
        self.calls: list = []                  # (method, path) of every Drive request, for a test to look at
        self.valid: set = set()                # access tokens that work
        self.refreshes = 0
        self.refresh_token = "refresh-1"
        self.client_secret = ""
        self.uploads: dict = {}
        self._n = 0
        self.rate_limit_next = 0               # this many requests are answered 429 first
        self.files["root"] = {"name": "My Drive", "mime": FOLDER, "parents": [], "data": b"", "mtime": "2026-01-01T00:00:00.000Z", "trashed": False}

    # building the content -----------------------------------------------------------------------------------------------------------------
    def add(self, name: str, parent: str = "root", data: bytes = b"", mime: str = "text/plain", **extra) -> str:
        self._n += 1
        key = f"id{self._n}"
        self.files[key] = {"name": name, "mime": mime, "parents": [parent], "data": data, "mtime": "2026-03-04T05:06:07.000Z",
                           "trashed": False, **extra}
        return key

    def folder(self, name: str, parent: str = "root") -> str:
        return self.add(name, parent, b"", FOLDER)

    def expire(self) -> None:
        self.valid.clear()

    def named(self, name: str):
        return next((k for k, v in self.files.items() if v["name"] == name and not v["trashed"]), None)

    # the web ----------------------------------------------------------------------------------------------------------------------------
    def __call__(self, method: str, url: str, headers: dict, body=None) -> tuple:
        if hasattr(body, "read"):
            body = body.read()
        parts = urllib.parse.urlsplit(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        path = parts.path
        if parts.netloc == "oauth2.googleapis.com":
            return self._token(body)
        if parts.netloc == "upload.fake":
            return self._put_upload(path, body)
        auth = headers.get("Authorization", "")
        if auth.removeprefix("Bearer ") not in self.valid:
            return 401, {}, json.dumps({"error": {"message": "Invalid Credentials"}}).encode()
        self.calls.append((method, path))
        if self.rate_limit_next:
            self.rate_limit_next -= 1
            return 429, {}, b"{}"
        return self._route(method, path, query, headers, body)

    def _token(self, body) -> tuple:
        form = {k: v[0] for k, v in urllib.parse.parse_qs((body or b"").decode()).items()}
        if self.client_secret and form.get("client_secret") != self.client_secret:
            return 401, {}, json.dumps({"error": "invalid_client"}).encode()
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") != self.refresh_token:
            return 400, {}, json.dumps({"error": "invalid_grant", "error_description": "Token has been revoked"}).encode()
        if form.get("grant_type") == "authorization_code" and form.get("code") != "the-code":
            return 400, {}, json.dumps({"error": "invalid_grant"}).encode()
        self.refreshes += 1
        token = f"access-{self.refreshes}"
        self.valid.add(token)
        out = {"access_token": token, "expires_in": 3600}
        if form.get("grant_type") == "authorization_code":
            out["refresh_token"] = self.refresh_token
        return 200, {}, json.dumps(out).encode()

    def _json(self, status: int, obj) -> tuple:
        return status, {}, json.dumps(obj).encode()

    def _item(self, key: str) -> dict:
        f = self.files[key]
        out = {"id": key, "name": f["name"], "mimeType": f["mime"], "modifiedTime": f["mtime"]}
        if f["mime"] != FOLDER and not f["mime"].startswith("application/vnd.google-apps"):
            out["size"] = str(len(f["data"]))
        if f.get("target"):
            out["shortcutDetails"] = {"targetId": f["target"], "targetMimeType": self.files[f["target"]]["mime"]}
        return out

    def _route(self, method: str, path: str, query: dict, headers: dict, body) -> tuple:
        if path == "/drive/v3/about":
            return self._json(200, {"user": {"displayName": "Erlend", "emailAddress": "erlend@example.com"}})
        if path == "/drive/v3/drives":
            return self._json(200, {"drives": [{"id": k, "name": v} for k, v in self.drives.items()]})
        if path == "/drive/v3/files" and method == "GET":
            q = query.get("q", "")
            m = re.match(r"'([^']+)' in parents and trashed = false", q)
            if m:
                keys = [k for k, f in self.files.items() if m.group(1) in f["parents"] and not f["trashed"]]
            elif q.startswith("sharedWithMe"):
                keys = [k for k in self.shared if not self.files[k]["trashed"]]
            else:
                return self._json(400, {"error": {"message": "bad query"}})
            return self._json(200, {"files": [self._item(k) for k in sorted(keys, key=lambda k: self.files[k]["name"])]})
        if path == "/drive/v3/files" and method == "POST":
            meta = json.loads(body.decode())
            key = self.add(meta["name"], meta["parents"][0], b"", meta.get("mimeType", "application/octet-stream"))
            return self._json(200, {"id": key})
        m = re.match(r"/drive/v3/files/([^/]+)(/export)?$", path)
        if m:
            key, export = m.group(1), bool(m.group(2))
            f = self.files.get(key)
            if f is None:
                return self._json(404, {"error": {"message": "File not found"}})
            if method == "GET" and export:
                return 200, {}, b"EXPORT:" + f["data"]
            if method == "GET":
                data = f["data"]
                rng = re.match(r"bytes=(\d+)-(\d+)", headers.get("Range", ""))
                if rng:
                    a, z = int(rng.group(1)), int(rng.group(2))
                    return (206, {}, data[a:z + 1]) if a < len(data) else (416, {}, b"")
                return 200, {}, data
            if method == "PATCH":
                meta = json.loads(body.decode()) if body else {}
                if "name" in meta:
                    f["name"] = meta["name"]
                if "trashed" in meta:
                    f["trashed"] = meta["trashed"]
                if "modifiedTime" in meta:
                    f["mtime"] = meta["modifiedTime"]
                if query.get("addParents"):
                    f["parents"] = [p for p in f["parents"] if p != query.get("removeParents")] + [query["addParents"]]
                return self._json(200, {"id": key})
        m = re.match(r"/upload/drive/v3/files(?:/([^/]+))?$", path)
        if m and query.get("uploadType") == "resumable":
            meta = json.loads(body.decode()) if body else {}
            token = f"u{len(self.uploads) + 1}"
            self.uploads[token] = {"existing": m.group(1), "name": meta.get("name"), "parent": (meta.get("parents") or [""])[0]}
            return 200, {"location": f"https://upload.fake/{token}"}, b""
        return self._json(404, {"error": {"message": f"no route {method} {path}"}})

    def _put_upload(self, path: str, body) -> tuple:
        info = self.uploads[path.lstrip("/")]
        if info["existing"]:
            self.files[info["existing"]]["data"] = body
            return self._json(200, {"id": info["existing"]})
        key = self.add(info["name"], info["parent"], body, "application/octet-stream")
        return self._json(200, {"id": key})
