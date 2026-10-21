"""What may be shown of a Markdown file, and what may be done with its links (spec V4: the safe subset).

Raw HTML in a Markdown file is shown as text, never as markup: a ``<script>``, a ``<form>`` or an ``<img>`` that points somewhere
stays a harmless string. (Code blocks and code spans are left alone, so their ``<`` stays a ``<``; the autolink ``<https://...>`` keeps
working.) Links are limited to ``http``, ``https``, ``mailto`` and paths on this computer; anything else (``javascript:``, ``file:``
on another host, ``data:``...) is refused. A file over 256 KB is not rendered: it is shown as its source.
Qt-free; the window draws it.
"""
from __future__ import annotations

import os
import re
from typing import Optional
from urllib.parse import unquote, urlparse

MAX_RENDER = 256 * 1024
WEB = ("http", "https")
_FENCE = re.compile(r"^(?P<mark>`{3,}|~{3,})[^\n]*\n.*?^(?P=mark)[ \t]*$", re.S | re.M)
_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^\s<>]+)>")


def too_big(size: int) -> bool:
    return size > MAX_RENDER


def _escape_plain(text: str) -> str:
    keep = {}

    def hold(m: "re.Match") -> str:
        key = f"\x00{len(keep)}\x00"
        keep[key] = m.group(0)
        return key
    text = _AUTOLINK.sub(hold, text)
    text = text.replace("<", "&lt;")
    for key, original in keep.items():
        text = text.replace(key, original)
    return text


def escape_html(markdown: str) -> str:
    """The Markdown with every raw ``<`` turned into ``&lt;`` outside code, so the renderer shows HTML as text."""
    out = []
    pos = 0
    for fence in _FENCE.finditer(markdown):
        out.append(_escape_spans(markdown[pos:fence.start()]))
        out.append(fence.group(0))
        pos = fence.end()
    out.append(_escape_spans(markdown[pos:]))
    return "".join(out)


def _escape_spans(text: str) -> str:
    out = []
    pos = 0
    for span in _SPAN.finditer(text):
        out.append(_escape_plain(text[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(_escape_plain(text[pos:]))
    return "".join(out)


def classify_link(url: str, base_dir: str = "") -> tuple:
    """``(kind, target)``: ``web`` (http or https), ``mail``, ``file`` (a path on this computer, made absolute against ``base_dir``),
    ``anchor`` (a heading in the same file) or ``("", "")`` for a link that is refused."""
    url = (url or "").strip()
    if not url:
        return "", ""
    if url.startswith("#"):
        return "anchor", url[1:]
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if len(scheme) == 1 and url[1:2] in (":",):                     # C:\folder\file: a drive letter, not a scheme
        return "file", url
    if scheme in WEB and parsed.netloc:
        return "web", url
    if scheme == "mailto" and parsed.path:
        return "mail", url
    if scheme == "file" and not parsed.netloc:
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return "file", os.path.normpath(path)
    if scheme:
        return "", ""                                               # javascript:, data:, ftp:, anything else
    path = unquote(parsed.path)
    if not path:
        return "", ""
    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
    return "file", os.path.normpath(full)


def local_target(url: str, base_dir: str) -> Optional[str]:
    kind, target = classify_link(url, base_dir)
    return target if kind == "file" else None
