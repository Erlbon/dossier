"""Google Drive as folders: ``gdrive://<account>/path`` behind the same calls ``SftpFileSystem`` already knows. Standard library only.

Drive has no paths, only files with ids, and two files may have the same name in one folder. This client makes a tree of it, the way
``catalogclient`` does for a book catalogue: a folder's children get names (a second ``report.txt`` becomes ``report (2).txt``), and a path
is followed from the top, one folder at a time. The top shows My Drive and two more folders, *Shared with me* and *Shared drives*.

* **Google's own documents** (Docs, Sheets, Slides, Drawings) have no file contents: they show with the extension they are exported to
  (``.docx``, ``.xlsx``, ``.pptx``, ``.pdf``), and opening or copying one downloads that export. Forms, Sites and other kinds that cannot
  be exported are left out.
* **Shortcuts** show as the thing they point to.
* **Delete goes to Drive's bin** (it can be restored there for 30 days); nothing is ever deleted for good from here.
* **Writes** are sent when the file is closed, in one resumable upload. A file that already exists keeps its id and gets a new version.
* A call that fails because the sign-in ran out is repeated once with a new access token; a busy service (429, 5xx) is waited for.

The web is reached through ``transport`` and the sign-in through ``TokenSource`` (see ``oauth.py``), so a test needs neither network nor browser.
"""
from __future__ import annotations

import errno
import json
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime
from typing import Callable, Optional

from .catalogclient import Node, safe_name, unique_names
from .oauth import OAuthApp, OAuthError, TokenSource, default_transport
from .sftp_proto import EXCL_FLAG, FAILURE, NO_SUCH_FILE, PERMISSION_DENIED, S_IFDIR, S_IFREG, WRITE_FLAG, Attrs, Name, SftpError, error_for

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
APPS = "application/vnd.google-apps."
ROOT_KEY, SHARED_KEY, DRIVES_KEY = "root", "@shared", "@drives"
SHARED_NAME, DRIVES_NAME = "Shared with me", "Shared drives"
CACHE_SECONDS = 60
RETRIES = 4
MEMORY_UPLOAD = 8 * 1024 * 1024        # an upload up to this size is sent from memory, a bigger one from the temporary file
FIELDS = "nextPageToken,files(id,name,mimeType,size,modifiedTime,shortcutDetails(targetId,targetMimeType))"

# Google's own kinds and what each is exported as: (mime type, extension)
EXPORTS = {
    APPS + "document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    APPS + "spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    APPS + "presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    APPS + "drawing": ("application/pdf", ".pdf"),
}


def app_for(client_id: str, client_secret: str) -> OAuthApp:
    """What Google knows this program by (the owner's own client id, from the Google Cloud console)."""
    return OAuthApp(AUTH_URL, TOKEN_URL, client_id, client_secret, (SCOPE,),
                    (("access_type", "offline"), ("prompt", "consent")))        # offline: the long-lasting refresh token


def _when(text: str) -> float:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


class GoogleDriveClient:
    exact_listings = True

    def __init__(self, tokens: TokenSource, transport: Callable = default_transport) -> None:
        self.tokens = tokens
        self.transport = transport
        self.sleep: Callable[[float], None] = time.sleep
        self.closed = False
        self.version = 0
        self.extensions: dict = {}
        self.account = ""
        self._lock = threading.RLock()
        self._listings: dict = {}              # folder path -> (time, {name: Node})
        self._handles: dict = {}
        self._exported: dict = {}              # file id -> the bytes of its last export, so stat then open do not ask twice
        self._next = 0

    # the web ----------------------------------------------------------------------------------------------------------------------------
    def close(self) -> None:
        self.closed = True
        with self._lock:
            for state in self._handles.values():
                if state.get("temp") is not None:
                    state["temp"].close()
            self._handles.clear()
            self._listings.clear()

    def _call(self, method: str, url: str, params: Optional[dict] = None, body=None, headers: Optional[dict] = None, path: str = "",
              want: tuple = (200,), length: Optional[int] = None) -> tuple:
        """One request to Drive and its answer ``(status, headers, bytes)``. A status in ``want`` is returned; any other becomes the
        matching ``OSError``."""
        if self.closed:
            raise ConnectionError("the connection to Google Drive was closed")
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        refreshed = False
        for attempt in range(RETRIES):
            h = {"Authorization": "Bearer " + self.tokens.access(), "User-Agent": "Dossier", "Accept": "application/json"}
            h.update(headers or {})
            if length is not None:
                h["Content-Length"] = str(length)
            if hasattr(body, "seek"):
                body.seek(0)
            status, reply_headers, data = self.transport(method, url, h, body)
            if status in want:
                return status, reply_headers, data
            if status == 401 and not refreshed:
                refreshed = True
                self.tokens.access(force=True)                                  # the access token ran out: a new one, and once more
                continue
            if status in (429, 500, 502, 503, 504) or (status == 403 and b"ateLimit" in data):
                self.sleep(min(8, 2 ** attempt))
                continue
            raise self._error(status, data, path)
        raise ConnectionError("Google Drive is busy; try again in a moment")

    @staticmethod
    def _error(status: int, data: bytes, path: str) -> OSError:
        try:
            reason = json.loads(data.decode("utf-8")).get("error", {})
            reason = reason.get("message", "") if isinstance(reason, dict) else str(reason)
        except (ValueError, AttributeError):
            reason = ""
        if status == 404:
            return error_for(NO_SUCH_FILE, "no such file", path)
        if status == 401:
            return OAuthError("Google no longer accepts the sign-in: sign in again", "invalid_grant")
        if status == 403:
            return error_for(PERMISSION_DENIED, reason or "Google Drive does not allow it", path)
        if status == 400 and "storage" in reason.lower():
            return OSError(errno.ENOSPC, reason, path)
        return SftpError(FAILURE, reason or f"Google Drive answered {status}", path)

    def _json(self, method: str, url: str, params: Optional[dict] = None, body: Optional[dict] = None, path: str = "") -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"} if body is not None else None
        _s, _h, reply = self._call(method, url, params, data, headers, path)
        return json.loads(reply.decode("utf-8")) if reply else {}

    def connect(self) -> None:
        """Check that the sign-in works, and learn whose drive this is."""
        about = self._json("GET", API + "/about", {"fields": "user(displayName,emailAddress)"})
        user = about.get("user", {})
        self.account = str(user.get("emailAddress") or user.get("displayName") or "")
        self._listings.clear()

    # the tree ---------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _clean(path: str) -> str:
        parts = [p for p in path.replace("\\", "/").split("/") if p and p != "."]
        return "/" + "/".join(parts)

    def _root(self) -> Node:
        return Node("dir", ROOT_KEY)

    def _node(self, path: str) -> Node:
        path = self._clean(path)
        if path == "/":
            return self._root()
        parent, _slash, name = path.rpartition("/")
        kids = self._listing(parent or "/")
        node = kids.get(name) or next((n for k, n in kids.items() if k.lower() == name.lower()), None)
        if node is None:
            raise error_for(NO_SUCH_FILE, "no such file", path)
        return node

    def _listing(self, path: str) -> dict:
        path = self._clean(path)
        with self._lock:
            cached = self._listings.get(path)
            if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
        node = self._node(path)
        if not node.is_dir:
            raise error_for(NO_SUCH_FILE, "it is not a folder", path)
        kids = unique_names(self._children(node))
        with self._lock:
            self._listings[path] = (time.monotonic(), kids)
        return kids

    def _changed(self) -> None:
        with self._lock:
            self._listings.clear()
            self._exported.clear()

    def _children(self, node: Node) -> list:
        out: list = []
        if node.key == DRIVES_KEY:
            token = ""
            while True:
                answer = self._json("GET", API + "/drives", {"pageSize": 100, "fields": "nextPageToken,drives(id,name)",
                                                            **({"pageToken": token} if token else {})})
                out += [(safe_name(d.get("name", "")), Node("dir", d["id"])) for d in answer.get("drives", [])]
                token = answer.get("nextPageToken", "")
                if not token:
                    return out
        query = "sharedWithMe = true and trashed = false" if node.key == SHARED_KEY else f"'{node.key}' in parents and trashed = false"
        token = ""
        while True:
            params = {"q": query, "pageSize": 1000, "fields": FIELDS, "orderBy": "name", "supportsAllDrives": "true",
                      "includeItemsFromAllDrives": "true", **({"pageToken": token} if token else {})}
            answer = self._json("GET", API + "/files", params)
            for item in answer.get("files", []):
                made = self._make(item)
                if made is not None:
                    out.append(made)
            token = answer.get("nextPageToken", "")
            if not token:
                break
        if node.key == ROOT_KEY:
            out += [(SHARED_NAME, Node("dir", SHARED_KEY)), (DRIVES_NAME, Node("dir", DRIVES_KEY))]
        return out

    @staticmethod
    def _make(item: dict) -> Optional[tuple]:
        """``(name, Node)`` of one item Drive listed, or None for a kind that cannot be shown."""
        mime, key = item.get("mimeType", ""), item.get("id", "")
        name = safe_name(item.get("name", ""))
        mtime = _when(item.get("modifiedTime", ""))
        if mime == SHORTCUT:
            target = item.get("shortcutDetails") or {}
            mime, key = target.get("targetMimeType", ""), target.get("targetId", "")
            if not key:
                return None
        if mime == FOLDER:
            return name, Node("dir", key, mtime=mtime)
        if mime in EXPORTS:
            export, ext = EXPORTS[mime]
            return (name if name.lower().endswith(ext) else name + ext), Node("file", key, 0, mtime, mime, {"export": export})
        if mime.startswith(APPS):
            return None                                                        # a form, a site, a map: nothing to download
        return name, Node("file", key, int(item.get("size", 0) or 0), mtime, mime)

    @staticmethod
    def _attrs(node: Node) -> Attrs:
        perm = (S_IFDIR | 0o755) if node.is_dir else (S_IFREG | 0o644)
        return Attrs(size=0 if node.is_dir else max(0, node.size), perm=perm, atime=int(node.mtime), mtime=int(node.mtime), flags=1 | 4 | 8)

    # whole-item calls -------------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        return "/" if path in (".", "") else self._clean(path)

    def stat(self, path: str, follow: bool = True) -> Attrs:
        node = self._node(path)
        if not node.is_dir and node.extra.get("export") and node.size <= 0:
            node.size = len(self._export(node, path))                          # the size of an export is only known by making it
        return self._attrs(node)

    def listdir(self, path: str) -> list:
        return [Name(name, "", self._attrs(node)) for name, node in self._listing(path).items()]

    def readlink(self, path: str) -> str:
        raise OSError(errno.EINVAL, "Google Drive has no links", path)

    def set_mtime(self, path: str, mtime: float) -> None:
        node = self._node(path)
        stamp = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self._json("PATCH", f"{API}/files/{node.key}", {"supportsAllDrives": "true", "fields": "id"}, {"modifiedTime": stamp}, path)
        node.mtime = float(mtime)

    # changes ----------------------------------------------------------------------------------------------------------------------------
    def _parent_and_name(self, path: str) -> tuple:
        path = self._clean(path)
        parent, _slash, name = path.rpartition("/")
        if not name:
            raise error_for(PERMISSION_DENIED, "the top of the drive cannot be changed", path)
        node = self._node(parent or "/")
        if not node.is_dir:
            raise error_for(NO_SUCH_FILE, "it is not a folder", parent)
        if node.key in (SHARED_KEY, DRIVES_KEY):
            raise error_for(PERMISSION_DENIED, "put it in a folder of My Drive or of a shared drive: this list is Google's", parent)
        return node, name

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        parent, name = self._parent_and_name(path)
        if name in self._listing(self._clean(path).rpartition("/")[0] or "/"):
            raise FileExistsError(errno.EEXIST, "it already exists", path)
        self._json("POST", API + "/files", {"supportsAllDrives": "true", "fields": "id"},
                   {"name": name, "mimeType": FOLDER, "parents": [parent.key]}, path)
        self._changed()

    def _trash(self, node: Node, path: str) -> None:
        self._json("PATCH", f"{API}/files/{node.key}", {"supportsAllDrives": "true", "fields": "id"}, {"trashed": True}, path)
        self._changed()

    def rmdir(self, path: str) -> None:
        node = self._node(path)
        if self._listing(path):
            raise OSError(errno.ENOTEMPTY, "the folder is not empty", path)
        if node.key in (ROOT_KEY, SHARED_KEY, DRIVES_KEY):
            raise error_for(PERMISSION_DENIED, "this folder is not a real one", path)
        self._trash(node, path)

    def remove(self, path: str) -> None:
        self._trash(self._node(path), path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        node = self._node(old)
        old_parent, _old_name = self._parent_and_name(old)
        new_parent, new_name = self._parent_and_name(new)
        siblings = self._listing(self._clean(new).rpartition("/")[0] or "/")
        existing = siblings.get(new_name)
        if existing is not None and existing.key != node.key:
            if not overwrite:
                raise FileExistsError(errno.EEXIST, "it already exists", new)
            self._trash(existing, new)
        ext = node.extra.get("export") and next((e for m, e in EXPORTS.values() if m == node.extra["export"]), "")
        if ext and new_name.lower().endswith(ext):
            new_name = new_name[:-len(ext)]                                  # the extension belongs to the export, not to the name
        params = {"supportsAllDrives": "true", "fields": "id"}
        if new_parent.key != old_parent.key:
            params.update({"addParents": new_parent.key, "removeParents": old_parent.key})
        self._json("PATCH", f"{API}/files/{node.key}", params, {"name": new_name}, old)
        self._changed()

    # contents ---------------------------------------------------------------------------------------------------------------------------
    def open(self, path: str, flags: int) -> bytes:
        if flags & WRITE_FLAG:
            parent, name = self._parent_and_name(path)
            existing = self._listing(self._clean(path).rpartition("/")[0] or "/").get(name)
            if existing is not None and flags & EXCL_FLAG:
                raise SftpError(FAILURE, "the file already exists", path)
            if existing is not None and existing.is_dir:
                raise error_for(FAILURE, "it is a folder", path)
            if existing is not None and existing.extra.get("export"):
                raise error_for(PERMISSION_DENIED, "a Google document cannot be written as a file", path)
            state = {"path": path, "temp": tempfile.SpooledTemporaryFile(max_size=MEMORY_UPLOAD), "size": 0, "parent": parent.key,
                     "name": name, "existing": existing.key if existing is not None else ""}
        else:
            node = self._node(path)
            if node.is_dir:
                raise error_for(NO_SUCH_FILE, "it is a folder", path)
            whole = None
            if node.extra.get("export"):                                       # a Google document: its export is the file, read whole
                whole = self._exported.get(node.key)
                if whole is None:
                    whole = self._export(node, path)
                node.size = len(whole)
            state = {"path": path, "temp": None, "size": node.size, "id": node.key, "whole": whole}
        with self._lock:
            self._next += 1
            handle = str(self._next).encode()
            self._handles[handle] = state
        return handle

    def _export(self, node: Node, path: str) -> bytes:
        _s, _h, data = self._call("GET", f"{API}/files/{node.key}/export", {"mimeType": node.extra["export"]}, path=path,
                                  want=(200,))
        self._exported[node.key] = data
        return data

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        state = self._handles.get(handle)
        if state is None:
            raise error_for(FAILURE, "the file is not open", path)
        if state["whole"] is not None:
            return state["whole"][offset:offset + count]
        size = state["size"]
        if size and offset >= size:
            return b""
        last = offset + count - 1 if not size else min(offset + count, size) - 1
        status, _h, data = self._call("GET", f"{API}/files/{state['id']}", {"alt": "media", "supportsAllDrives": "true"},
                                      headers={"Range": f"bytes={offset}-{last}", "Accept": "*/*"}, path=state["path"], want=(200, 206, 416))
        if status == 416:
            return b""
        if status == 200:                                                      # the range was ignored: everything came
            state["whole"] = data
            return data[offset:offset + count]
        return data

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        state = self._handles[handle]
        if offset != state["size"]:
            raise OSError(errno.EINVAL, "a file in Google Drive can only be written from its start, in order", state["path"])
        state["temp"].write(data)
        state["size"] += len(data)

    def close_handle(self, handle: bytes) -> None:
        state = self._handles.pop(handle, None)
        if state is None or state["temp"] is None:
            return
        temp = state["temp"]
        try:
            self._upload(state, temp)
        finally:
            temp.close()

    def _upload(self, state: dict, temp) -> None:
        """One resumable upload: ask for a place to put the bytes, then put them all there."""
        size = state["size"]
        temp.seek(0)
        metadata = {} if state["existing"] else {"name": state["name"], "parents": [state["parent"]]}
        start = (f"{UPLOAD}/files/{state['existing']}" if state["existing"] else f"{UPLOAD}/files")
        _s, headers, _d = self._call("PATCH" if state["existing"] else "POST", start,
                                     {"uploadType": "resumable", "supportsAllDrives": "true", "fields": "id"},
                                     json.dumps(metadata).encode("utf-8"),
                                     {"Content-Type": "application/json; charset=utf-8", "X-Upload-Content-Type": "application/octet-stream",
                                      "X-Upload-Content-Length": str(size)}, state["path"])
        where = headers.get("location", "")
        if not where:
            raise SftpError(FAILURE, "Google Drive gave no place to put the file", state["path"])
        body = temp.read() if size <= MEMORY_UPLOAD else temp
        self._call("PUT", where, body=body, headers={"Content-Type": "application/octet-stream"}, path=state["path"], want=(200, 201),
                   length=size)
        self._changed()
