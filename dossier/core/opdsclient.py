"""An OPDS book catalogue (Calibre, Calibre-Web, Kavita, Komga, COPS and others) as folders and files.

The start of the catalogue is the "Start in" address of the connection (``/opds``, ``/api/opds/<key>``...). A feed's navigation entries are
folders; its acquisition entries are files, one for each format (``Title.epub``, ``Title.pdf``). Pages of a long feed are followed up to a
limit. Only links to the same server are followed: a link to another computer is left out, since the connection (and its login) is this
server's.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from .catalogclient import CatalogClient, Node, safe_name
from .opds import Feed, FeedError, classify, extension_for, parse_feed
from .sftp_proto import FAILURE, SftpError

ACCEPT = "application/atom+xml;profile=opds-catalog, application/opds+json, application/atom+xml, application/json;q=0.5, */*;q=0.1"
MAX_PAGES = 40
MAX_ENTRIES = 5000
DEFAULT_START = "/opds"


class OpdsClient(CatalogClient):
    def _root(self) -> Node:
        return Node("dir", self.start or DEFAULT_START)

    def _feed(self, target: str) -> Feed:
        reply = self.request("GET", target, headers={"Accept": ACCEPT}, quoted=True)
        try:
            return parse_feed(reply.body)
        except FeedError as e:
            raise SftpError(FAILURE, str(e))

    def _resolve(self, href: str, base: str):
        """The request target (path and query) of ``href`` as seen from the feed at ``base``; None for another computer."""
        joined = urlparse(urljoin(f"http://{self.host}{base if base.startswith('/') else '/' + base}", href))
        if joined.hostname and joined.hostname.lower() != self.host.lower():
            return None
        return (joined.path or "/") + (f"?{joined.query}" if joined.query else "")

    def _children(self, node: Node) -> list:
        out, key, pages = [], node.key, 0
        while key and pages < MAX_PAGES and len(out) < MAX_ENTRIES:
            feed = self._feed(key)
            pages += 1
            for entry in feed.entries:
                downloads, folders = classify(entry)
                title = entry.title or (folders[0].title if folders else "") or "untitled"
                seen = set()
                for link in downloads:
                    target = self._resolve(link.href, key)
                    mime = link.type.split(";")[0].strip().lower()
                    if target is None or (mime, target) in seen:
                        continue
                    seen.add((mime, target))
                    ext = extension_for(link.type, link.href)
                    name = safe_name(title)
                    name = name if not ext or name.lower().endswith(ext.lower()) else name + ext
                    out.append((name, Node("file", target, link.length, entry.updated, mime)))
                if not downloads and folders:
                    target = self._resolve(folders[0].href, key)
                    if target is not None:
                        out.append((safe_name(title), Node("dir", target, 0, entry.updated)))
            key = self._resolve(feed.next, key) if feed.next else ""
        return out

    def _target(self, node: Node) -> str:
        return node.key
