"""A Subsonic-compatible music server (Navidrome, Airsonic, Gonic, Subsonic...) as folders and files.

The tree is ``Artists / artist / album / tracks`` and ``Playlists / playlist / tracks``. A track's file is the original file (the server's
``download`` call), so a copy is the same file the server holds. The login is the Subsonic one: every request carries the user name, a
random salt and ``md5(password + salt)``; the password itself is never sent. Over plain HTTP that token can still be copied by someone who
listens in, so the connection says when it is not encrypted.

Servers differ a little; a list of one thing may come as the thing itself, and a missing field is left out, never an error.
"""
from __future__ import annotations

import errno
import hashlib
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from .catalogclient import CatalogClient, Node, safe_name
from .davclient import AuthError
from .opds import EXTENSIONS
from .sftp_proto import FAILURE, NO_SUCH_FILE, SftpError, error_for

API_VERSION = "1.16.1"
AUTH_CODES = (40, 41, 42, 43, 44)           # wrong user or password, token login not supported, not allowed...


def as_list(value) -> list:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def _when(text) -> float:
    try:
        stamp = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return 0.0


def _int(value) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


class SubsonicClient(CatalogClient):
    def _api_target(self, name: str, **params) -> str:
        salt = secrets.token_hex(6)
        token = hashlib.md5((self.password + salt).encode("utf-8")).hexdigest()
        query = {"u": self.user, "t": token, "s": salt, "v": API_VERSION, "c": "Dossier", "f": "json", **params}
        return f"{self.start}/rest/{name}.view?{urlencode(query)}"

    def _call(self, name: str, **params) -> dict:
        reply = self.request("GET", self._api_target(name, **params), quoted=True)
        try:
            doc = json.loads(reply.body)["subsonic-response"]
            status = doc.get("status")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SftpError(FAILURE, "the server did not answer like a Subsonic server (is the address right?)")
        if status != "ok":
            error = doc.get("error") if isinstance(doc.get("error"), dict) else {}
            message = str(error.get("message") or "the server refused the request")
            if error.get("code") in AUTH_CODES:
                raise AuthError(errno.EACCES, message)
            if error.get("code") == 70:
                raise error_for(NO_SUCH_FILE, message)
            raise SftpError(FAILURE, message)
        return doc

    def connect(self) -> None:
        self._call("ping")
        super().connect()

    # the tree ---------------------------------------------------------------------------------------------------------------------
    def _root(self) -> Node:
        return Node("dir", "root")

    def _children(self, node: Node) -> list:
        kind, _colon, ident = node.key.partition(":")
        if node.key == "root":
            return [("Artists", Node("dir", "artists")), ("Playlists", Node("dir", "playlists"))]
        if node.key == "artists":
            out = []
            for index in as_list(self._call("getArtists").get("artists", {}).get("index")):
                for artist in as_list(index.get("artist")):
                    out.append((safe_name(artist.get("name"), "unknown artist"), Node("dir", "artist:" + str(artist.get("id")))))
            return out
        if kind == "artist":
            out = []
            for album in as_list(self._call("getArtist", id=ident).get("artist", {}).get("album")):
                title = str(album.get("name") or album.get("title") or "unknown album")
                year = album.get("year")
                out.append((safe_name(f"{title} ({year})" if year else title), Node("dir", "album:" + str(album.get("id")), 0,
                                                                                    _when(album.get("created")))))
            return out
        if kind == "album":
            return self._songs(as_list(self._call("getAlbum", id=ident).get("album", {}).get("song")), with_artist=False)
        if node.key == "playlists":
            return [(safe_name(p.get("name"), "playlist"), Node("dir", "playlist:" + str(p.get("id")), 0, _when(p.get("changed"))))
                    for p in as_list(self._call("getPlaylists").get("playlists", {}).get("playlist"))]
        if kind == "playlist":
            return self._songs(as_list(self._call("getPlaylist", id=ident).get("playlist", {}).get("entry")), with_artist=True)
        return []

    @staticmethod
    def _songs(songs: list, with_artist: bool) -> list:
        discs = {_int(s.get("discNumber")) for s in songs} - {0}
        out = []
        for i, song in enumerate(songs, 1):
            title = str(song.get("title") or "untitled")
            track = _int(song.get("track"))
            if with_artist:
                number = f"{i:02d} "                                  # a playlist is in its own order, not the albums'
                title = f"{song.get('artist')} - {title}" if song.get("artist") else title
            else:
                number = (f"{_int(song.get('discNumber'))}-" if len(discs) > 1 else "") + (f"{track:02d} " if track else "")
            mime = str(song.get("contentType") or "")
            suffix = str(song.get("suffix") or "").lstrip(".") or EXTENSIONS.get(mime, "").lstrip(".")
            name = safe_name(number + title) + ("." + suffix if suffix else "")
            out.append((name, Node("file", str(song.get("id")), _int(song.get("size")), _when(song.get("created")), mime)))
        return out

    def _target(self, node: Node) -> str:
        return self._api_target("download", id=node.key)
