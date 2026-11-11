"""A structured listing of a .torrent file for the viewer's Spreadsheet grid: what it holds and where it points, read only.

Two sheets. "Files": every file with its path, size and exact byte count (a padding file of a v2 or hybrid torrent says so).
"Info": the name, the info-hash (SHA-1 of the bencoded ``info`` dictionary, and SHA-256 for a v2 torrent), the magnet link they make,
every tracker and web seed, who made it and when, the comment, the piece size and count, private or not. The info-hash is what
identifies the torrent everywhere (clients, trackers, logs), so it is computed from the file's own bytes, not trusted from a field.

Only the standard library; Qt-free. The decoder is strict and bounded: a damaged or hostile file is an error, never a hang.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional
from urllib.parse import quote

from .officedoc import DocumentError
from .officesheet import MAX_CELLS, Sheet, _Grid
from .sizefmt import human_size

TORRENT_EXTENSIONS = (".torrent",)
MAX_TORRENT = 64 * 1024 * 1024
MAX_DEPTH = 64


class _Decoder:
    """Bencode: integers ``i42e``, strings ``4:spam``, lists ``l...e``, dictionaries ``d...e``. Remembers where the top-level
    ``info`` value starts and ends, so the info-hash is taken over exactly those bytes."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.info_span: Optional[tuple] = None

    def value(self, i: int, depth: int = 0):
        if depth > MAX_DEPTH:
            raise DocumentError("The torrent file is nested too deeply")
        d = self.data
        if i >= len(d):
            raise DocumentError("The torrent file is cut short")
        c = d[i:i + 1]
        if c == b"i":
            end = d.index(b"e", i)
            return int(d[i + 1:end]), end + 1
        if c.isdigit():
            colon = d.index(b":", i)
            n = int(d[i:colon])
            start = colon + 1
            if start + n > len(d):
                raise DocumentError("The torrent file is cut short")
            return d[start:start + n], start + n
        if c == b"l":
            out, i = [], i + 1
            while d[i:i + 1] != b"e":
                v, i = self.value(i, depth + 1)
                out.append(v)
            return out, i + 1
        if c == b"d":
            out, i = {}, i + 1
            while d[i:i + 1] != b"e":
                k, i = self.value(i, depth + 1)
                if not isinstance(k, bytes):
                    raise DocumentError("The torrent file is damaged")
                start = i
                v, i = self.value(i, depth + 1)
                if depth == 0 and k == b"info":
                    self.info_span = (start, i)
                out[k] = v
            return out, i + 1
        raise DocumentError("This is not a torrent file inside, whatever its name says")


def _text(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return "" if v is None else str(v)


def _pick(d: dict, key: bytes):
    """A field, preferring its ``.utf-8`` twin (older clients wrote names in the system's code page and the UTF-8 one beside it)."""
    return d.get(key + b".utf-8", d.get(key))


def _files(info: dict) -> list:
    """(path, bytes, padding) for every file."""
    name = _text(_pick(info, b"name"))
    if isinstance(info.get(b"files"), list):
        out = []
        for f in info[b"files"]:
            if not isinstance(f, dict):
                continue
            parts = _pick(f, b"path") or []
            path = "/".join(_text(p) for p in parts if isinstance(p, bytes))
            out.append((f"{name}/{path}", f.get(b"length", 0) if isinstance(f.get(b"length"), int) else 0,
                        b"p" in (f.get(b"attr") or b"") or path.startswith(".pad/")))
        return out
    if isinstance(info.get(b"file tree"), dict):                     # v2 only
        out = []

        def walk(node: dict, prefix: str, depth: int) -> None:
            if depth > MAX_DEPTH:
                return
            for key, child in node.items():
                if not isinstance(child, dict):
                    continue
                if key == b"" and isinstance(child.get(b"length"), int):
                    out.append((prefix, child[b"length"], b"p" in (child.get(b"attr") or b"")))
                else:
                    walk(child, f"{prefix}/{_text(key)}" if prefix else _text(key), depth + 1)
        walk(info[b"file tree"], name, 0)
        return out
    return [(name, info.get(b"length", 0) if isinstance(info.get(b"length"), int) else 0, False)]


def torrent_sheets(path: str) -> list:
    with open(path, "rb") as f:
        data = f.read(MAX_TORRENT + 1)
    if len(data) > MAX_TORRENT:
        raise DocumentError("The torrent file is too big to be one")
    decoder = _Decoder(data)
    try:
        meta, _end = decoder.value(0)
    except (ValueError, IndexError) as e:
        raise DocumentError("The torrent file is damaged") from e
    if not isinstance(meta, dict) or not isinstance(meta.get(b"info"), dict) or decoder.info_span is None:
        raise DocumentError("This is not a torrent file inside: it has no info part")
    info = meta[b"info"]
    raw_info = data[decoder.info_span[0]:decoder.info_span[1]]
    v2 = info.get(b"meta version") == 2
    hash_v1 = hashlib.sha1(raw_info).hexdigest() if (b"pieces" in info or not v2) else ""
    hash_v2 = hashlib.sha256(raw_info).hexdigest() if v2 else ""
    name = _text(_pick(info, b"name"))
    files = _files(info)
    total = sum(n for _, n, pad in files if not pad)

    budget = [MAX_CELLS]
    grid = _Grid(budget)
    for c, head in enumerate(("Path", "Size", "Bytes", "Note")):
        grid.put(0, c, head)
    for r, (p, n, pad) in enumerate(files, start=1):
        grid.put(r, 0, p)
        grid.put(r, 1, human_size(n))
        grid.put(r, 2, str(n))
        grid.put(r, 3, "padding" if pad else "")
    files_sheet = Sheet("Files", grid.rows(), grid.cut)

    trackers = []
    if meta.get(b"announce"):
        trackers.append(_text(meta[b"announce"]))
    for tier in meta.get(b"announce-list") or []:
        for t in tier if isinstance(tier, list) else []:
            if _text(t) not in trackers:
                trackers.append(_text(t))
    seeds = meta.get(b"url-list") or []
    seeds = [_text(s) for s in (seeds if isinstance(seeds, list) else [seeds])]
    magnet = []
    if hash_v1:
        magnet.append("xt=urn:btih:" + hash_v1)
    if hash_v2:
        magnet.append("xt=urn:btmh:1220" + hash_v2)
    magnet.append("dn=" + quote(name))
    magnet.extend("tr=" + quote(t, safe="") for t in trackers)
    created = meta.get(b"creation date")
    pieces = info.get(b"pieces")
    rows = [("Name", name),
            ("Info-hash (v1, SHA-1)", hash_v1), ("Info-hash (v2, SHA-256)", hash_v2),
            ("Magnet link", "magnet:?" + "&".join(magnet)),
            ("Files", f"{len(files):,}"), ("Total size", f"{human_size(total)} ({total:,} bytes)"),
            ("Piece size", human_size(info[b"piece length"]) if isinstance(info.get(b"piece length"), int) else ""),
            ("Pieces", f"{len(pieces) // 20:,}" if isinstance(pieces, bytes) else ""),
            ("Private", "yes" if info.get(b"private") == 1 else "no"),
            ("Created by", _text(meta.get(b"created by"))),
            ("Creation date", dt.datetime.fromtimestamp(created, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
             if isinstance(created, int) and 0 < created < 32503680000 else ""),
            ("Comment", _text(_pick(meta, b"comment"))),
            ("Source", _text(info.get(b"source"))),
            ("Version", "v2" if v2 and not hash_v1 else "hybrid (v1 and v2)" if v2 else "v1"),
            ("Encoding", _text(meta.get(b"encoding")))]
    rows += [("Tracker", t) for t in trackers] + [("Web seed", s) for s in seeds]
    info_grid = _Grid(budget)
    info_grid.put(0, 0, "Field")
    info_grid.put(0, 1, "Value")
    r = 1
    for field_name, value in rows:
        if value:
            info_grid.put(r, 0, field_name)
            info_grid.put(r, 1, value)
            r += 1
    return [files_sheet, Sheet("Info", info_grid.rows(), info_grid.cut)]
