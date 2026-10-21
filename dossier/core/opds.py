"""Reading an OPDS catalogue: the Atom feeds of OPDS 1.x and the JSON feeds of OPDS 2.0, as plain data. Qt-free, no network.

``parse_feed(data)`` gives a ``Feed``: its title, the address of the next page, and its entries; an entry has a title and links (address, what
the link is for, what kind of file it points to). ``classify`` says which links of an entry are downloads (acquisitions) and which lead to
another feed (navigation). A reply that holds a document type declaration is refused (the XML "billion laughs" attack).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree

ATOM = "{http://www.w3.org/2005/Atom}"
ACQUISITION = "http://opds-spec.org/acquisition"
SKIPPED = ("/buy", "/borrow", "/subscribe", "/sample", "/preview")           # not a download of the book itself
NAVIGATION_TYPES = ("atom+xml", "opds+json", "opds-catalog")
EXTENSIONS = {"application/epub+zip": ".epub", "application/pdf": ".pdf", "application/x-mobipocket-ebook": ".mobi",
              "application/vnd.amazon.ebook": ".azw3", "application/x-cbz": ".cbz", "application/vnd.comicbook+zip": ".cbz",
              "application/x-cbr": ".cbr", "application/vnd.comicbook-rar": ".cbr", "application/fb2+zip": ".fb2.zip",
              "application/x-fictionbook+xml": ".fb2", "text/plain": ".txt", "text/html": ".html", "application/zip": ".zip",
              "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4b": ".m4b", "audio/ogg": ".ogg", "audio/flac": ".flac",
              "application/audiobook+zip": ".audiobook", "application/lpf+zip": ".lpf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_FEED = 16 * 1024 * 1024


class FeedError(ValueError):
    """The reply is not a feed this program can read."""


@dataclass
class Link:
    href: str
    rel: str = ""
    type: str = ""
    title: str = ""
    length: int = 0


@dataclass
class FeedEntry:
    title: str
    links: list = field(default_factory=list)
    updated: float = 0.0


@dataclass
class Feed:
    title: str = ""
    next: str = ""
    entries: list = field(default_factory=list)


def _when(text: str) -> float:
    try:
        stamp = datetime.fromisoformat((text or "").strip().replace("Z", "+00:00"))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return 0.0


def _length(text) -> int:
    try:
        return max(int(str(text).strip()), 0)
    except (TypeError, ValueError):
        return 0


def parse_feed(data: bytes) -> Feed:
    if len(data) > MAX_FEED:
        raise FeedError("the catalogue's reply is too big")
    head = data[:2048].lstrip()
    if head[:1] in (b"{", b"["):
        return _parse_json(data)
    return _parse_atom(data)


def _parse_atom(data: bytes) -> Feed:
    if b"<!doctype" in data[:4096].lower() or b"<!entity" in data[:65536].lower():
        raise FeedError("the catalogue's reply was refused (it holds a document type declaration)")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as e:
        raise FeedError(f"the catalogue's reply is not a feed ({e})")
    if root.tag != f"{ATOM}feed":
        raise FeedError("the address is not an OPDS catalogue (it did not answer with an Atom feed)")
    feed = Feed(title=(root.findtext(f"{ATOM}title") or "").strip())
    for link in root.findall(f"{ATOM}link"):
        if link.get("rel") == "next" and link.get("href"):
            feed.next = link.get("href")
    for entry in root.findall(f"{ATOM}entry"):
        links = [Link(l.get("href", ""), l.get("rel", ""), l.get("type", ""), l.get("title", ""),
                      _length(l.get("length") or l.get("{http://purl.org/dc/terms/}extent")))
                 for l in entry.findall(f"{ATOM}link") if l.get("href")]
        feed.entries.append(FeedEntry((entry.findtext(f"{ATOM}title") or "").strip(), links, _when(entry.findtext(f"{ATOM}updated") or "")))
    return feed


def _json_links(items) -> list:
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("href"), str):
            rel = item.get("rel", "")
            rel = rel[0] if isinstance(rel, list) and rel else rel
            props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            out.append(Link(item["href"], str(rel or ""), str(item.get("type") or ""), str(item.get("title") or ""),
                            _length(item.get("length") or props.get("length"))))
    return out


def _parse_json(data: bytes) -> Feed:
    try:
        doc = json.loads(data)
    except ValueError as e:
        raise FeedError(f"the catalogue's reply is not a feed ({e})")
    if not isinstance(doc, dict):
        raise FeedError("the address is not an OPDS catalogue")
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    feed = Feed(title=str(meta.get("title") or ""))
    for link in _json_links(doc.get("links")):
        if link.rel == "next":
            feed.next = link.href

    def navigation(items) -> None:
        for link in _json_links(items):
            feed.entries.append(FeedEntry(link.title or link.href, [Link(link.href, "subsection", link.type or "application/opds+json")]))

    def publications(items) -> None:
        for pub in items if isinstance(items, list) else []:
            if not isinstance(pub, dict):
                continue
            pmeta = pub.get("metadata") if isinstance(pub.get("metadata"), dict) else {}
            title = pmeta.get("title")
            title = title if isinstance(title, str) else (next(iter(title.values()), "") if isinstance(title, dict) else "")
            links = [Link(l.href, l.rel if l.rel.startswith("http://opds-spec.org/") else ACQUISITION, l.type, l.title, l.length)
                     for l in _json_links(pub.get("links")) if "image" not in l.rel and "thumbnail" not in l.rel and l.rel != "self"]
            feed.entries.append(FeedEntry(str(title or ""), links, _when(str(pmeta.get("modified") or pmeta.get("published") or ""))))

    navigation(doc.get("navigation"))
    publications(doc.get("publications"))
    for group in doc.get("groups") if isinstance(doc.get("groups"), list) else []:
        if isinstance(group, dict):
            navigation(group.get("navigation"))
            publications(group.get("publications"))
    return feed


def classify(entry: FeedEntry) -> tuple:
    """``(downloads, folders)`` of an entry: its acquisition links and its links to other feeds."""
    downloads = [l for l in entry.links if l.rel.startswith(ACQUISITION) and not any(s in l.rel for s in SKIPPED)]
    folders = [l for l in entry.links if not l.rel.startswith(ACQUISITION) and l.rel != "self"
               and any(t in l.type.lower() for t in NAVIGATION_TYPES)]
    return downloads, folders


def extension_for(mime: str, href: str = "") -> str:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in EXTENSIONS:
        return EXTENSIONS[mime]
    tail = href.split("?")[0].rsplit("/", 1)[-1]
    return "." + tail.rsplit(".", 1)[1][:8] if "." in tail else ""
