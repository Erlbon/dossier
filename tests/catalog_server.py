"""An in-process HTTP server that behaves like an OPDS catalogue and a Subsonic music server, for the tests. Plain HTTP on 127.0.0.1."""
import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USER, PASSWORD = "reader", "s3cret"

BOOKS = {                                       # id -> (title, bytes)
    "1": ("The Sea Wolf", b"EPUB-OF-THE-SEA-WOLF" * 400),
    "2": ("Moby: or, the Whale", b"PDF-OF-MOBY" * 300),
    "3": ("Same Title", b"first" * 50),
    "4": ("Same Title", b"second" * 50),
}
SONGS = {                                       # id -> (title, track, disc, artist, bytes)
    "s1": ("Opening", 1, 1, "The Band", b"MP3-ONE" * 500),
    "s2": ("Second Song", 2, 1, "The Band", b"MP3-TWO" * 500),
    "s3": ("Back Again", 1, 2, "The Band", b"MP3-THREE" * 500),
}

ATOM = '<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:dcterms="http://purl.org/dc/terms/">'


def feed(title: str, entries: str, extra: str = "") -> bytes:
    return (ATOM + f"<title>{title}</title>{extra}{entries}</feed>").encode()


def nav(title: str, href: str) -> str:
    return (f'<entry><title>{title}</title><updated>2026-01-02T03:04:05Z</updated>'
            f'<link rel="subsection" href="{href}" type="application/atom+xml;profile=opds-catalog;kind=navigation"/></entry>')


def book(ident: str, ext: str = "epub", mime: str = "application/epub+zip", extra_link: str = "") -> str:
    title, data = BOOKS[ident]
    return (f'<entry><title>{title}</title><updated>2026-02-03T04:05:06Z</updated>'
            f'<link rel="http://opds-spec.org/acquisition" href="/books/{ident}.{ext}" type="{mime}" length="{len(data)}"/>{extra_link}</entry>')


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # helpers ---------------------------------------------------------------------------------------------------------------------
    def send(self, status: int, body: bytes = b"", ctype: str = "application/octet-stream", headers: dict = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_ranged(self, data: bytes, ignore_range: bool = False) -> None:
        wanted = self.headers.get("Range")
        if not wanted or ignore_range:
            self.send(200, data)
            return
        first, _dash, last = wanted.replace("bytes=", "").partition("-")
        first = int(first)
        if first >= len(data):
            self.send(416, b"", headers={"Content-Range": f"bytes */{len(data)}"})
            return
        last = min(int(last) if last else len(data) - 1, len(data) - 1)
        self.send(206, data[first:last + 1], headers={"Content-Range": f"bytes {first}-{last}/{len(data)}"})

    def authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic ") and base64.b64decode(header[6:]).decode() == f"{USER}:{PASSWORD}":
            return True
        self.send(401, b"login", headers={"WWW-Authenticate": 'Basic realm="books"'})
        return False

    def do_GET(self) -> None:            # noqa: N802
        url = urlparse(self.path)
        path, query = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        self.server.hits.append(self.path)
        if path.startswith("/rest/"):
            return self.subsonic(path[len("/rest/"):].removesuffix(".view"), query)
        if path.startswith("/books/"):
            if not self.authorised():
                return
            ident = path.rsplit("/", 1)[1].split(".")[0]
            if path.endswith("norange.epub"):
                return self.send_ranged(b"X" * 3000, ignore_range=True)
            if ident in BOOKS:
                return self.send_ranged(BOOKS[ident][1])
            return self.send(404, b"no")
        if path.startswith("/opds"):
            if not self.authorised():
                return
            return self.opds(path, query)
        self.send(404, b"no")

    do_HEAD = do_GET

    # OPDS ------------------------------------------------------------------------------------------------------------------------
    def opds(self, path: str, query: dict) -> None:
        atom = "application/atom+xml;profile=opds-catalog"
        if path in ("/opds", "/opds/"):
            return self.send(200, feed("Catalogue", nav("New books", "/opds/new") + nav("Many pages", "/opds/pages?page=1")
                                       + nav("Elsewhere", "http://other.example/opds") + nav("JSON catalogue", "/opds2")
                                       + book("1") + book("1", "pdf", "application/pdf") + book("2", "pdf", "application/pdf")
                                       + '<entry><title>No Range</title><link rel="http://opds-spec.org/acquisition" href="/books/norange.epub"'
                                         ' type="application/epub+zip"/></entry>'
                                       + '<entry><title>Not for sale</title><link rel="http://opds-spec.org/acquisition/buy" '
                                         'href="/buy/1" type="text/html"/></entry>'), atom)
        if path == "/opds/new":
            return self.send(200, feed("New", book("3") + book("4")), atom)
        if path == "/opds/pages":
            page = int(query.get("page", "1"))
            more = f'<link rel="next" href="/opds/pages?page={page + 1}"/>' if page < 3 else ""
            return self.send(200, feed(f"Page {page}", nav(f"Shelf {page}", f"/opds/shelf{page}"), more), atom)
        if path.startswith("/opds/shelf"):
            return self.send(200, feed("Shelf", book("1")), atom)
        if path == "/opds2":
            doc = {"metadata": {"title": "JSON"}, "links": [],
                   "navigation": [{"href": "/opds/new", "title": "New in JSON", "type": "application/opds+json"}],
                   "publications": [{"metadata": {"title": "A JSON Book", "modified": "2026-03-04T05:06:07Z"},
                                     "links": [{"rel": "http://opds-spec.org/acquisition", "href": "/books/1.epub",
                                                "type": "application/epub+zip", "properties": {"length": 8000}}, {"rel": "self", "href": "/x"}]}]}
            return self.send(200, json.dumps(doc).encode(), "application/opds+json")
        self.send(404, b"no")

    # Subsonic --------------------------------------------------------------------------------------------------------------------
    def subsonic(self, name: str, q: dict) -> None:
        def reply(**body):
            return self.send(200, json.dumps({"subsonic-response": {"status": "ok", "version": "1.16.1", **body}}).encode(), "application/json")

        def fail(code, message):
            return self.send(200, json.dumps({"subsonic-response": {"status": "failed", "error": {"code": code, "message": message}}}).encode(),
                             "application/json")
        if q.get("u") != USER or q.get("t") != hashlib.md5((PASSWORD + q.get("s", "")).encode()).hexdigest():
            return fail(40, "Wrong username or password")
        if name == "ping":
            return reply()
        if name == "getArtists":
            return reply(artists={"index": [{"name": "T", "artist": [{"id": "a1", "name": "The Band", "albumCount": 1}]},
                                            {"name": "A", "artist": {"id": "a2", "name": "AC/DC", "albumCount": 0}}]})
        if name == "getArtist":
            if q["id"] == "a1":
                return reply(artist={"id": "a1", "name": "The Band", "album": [{"id": "al1", "name": "First Album", "year": 1999,
                                                                               "created": "2020-01-02T03:04:05.000Z"}]})
            return reply(artist={"id": q["id"], "name": "AC/DC"})
        if name == "getAlbum":
            songs = [{"id": i, "title": t, "track": tr, "discNumber": d, "suffix": "mp3", "size": len(b), "contentType": "audio/mpeg",
                      "created": "2020-01-02T03:04:05Z", "artist": a} for i, (t, tr, d, a, b) in SONGS.items()]
            return reply(album={"id": "al1", "name": "First Album", "song": songs})
        if name == "getPlaylists":
            return reply(playlists={"playlist": {"id": "p1", "name": "Road / Trip"}})
        if name == "getPlaylist":
            return reply(playlist={"id": "p1", "entry": [{"id": "s2", "title": "Second Song", "artist": "The Band", "suffix": "mp3",
                                                         "size": len(SONGS["s2"][4])}]})
        if name == "download":
            if q["id"] not in SONGS:
                return fail(70, "Song not found")
            return self.send_ranged(SONGS[q["id"]][4])
        fail(0, "unknown call")


def start() -> tuple:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.hits = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
