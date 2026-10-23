"""Dragging files between the panels, inside a panel, and to and from other programs (Explorer, Nautilus).

What travels is a list of paths. Inside Dossier they travel exactly (any file system, an archive member too) in our own format; for
files on a drive they also travel as the usual file URLs, so Explorer and other programs can take them and Dossier can take what they
drop. The decision between move and copy is made at the drop, from the keys held down, and (if no key decides) from the drives: one
drive moves, two drives copy.
"""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

from PyQt6.QtCore import QByteArray, QMetaType, QMimeData, QUrl
from PyQt6.QtGui import QImage

from ..core import newfile
from ..core.platform import has_scheme, path_key

MIME = "application/x-dossier-paths"
URI_LIST = "text/uri-list"


class LazyFilesMime(QMimeData):
    """The data of a drag whose items are not files on a drive (inside an archive, on a server). Other programs ask for file URLs; the
    items are copied to a temporary folder only when one of them asks (at the drop), so a drag that ends inside Dossier, where our own
    list is used, never copies anything. ``stage_fn()`` returns the local paths (or an empty list if it could not)."""

    def __init__(self, stage_fn: Callable[[], list]) -> None:
        super().__init__()
        self._stage = stage_fn
        self._urls: Optional[list] = None

    def _staged(self) -> list:
        if self._urls is None:
            try:
                self._urls = [QUrl.fromLocalFile(p) for p in self._stage()]
            except Exception:                                  # noqa: BLE001 -- the other program gets nothing, never a crash here
                self._urls = []
        return self._urls

    def formats(self) -> list:
        found = super().formats()
        return found if URI_LIST in found else found + [URI_LIST]

    def hasFormat(self, mimetype: str) -> bool:
        return mimetype == URI_LIST or super().hasFormat(mimetype)

    def retrieveData(self, mimetype: str, preferred_type):
        if mimetype != URI_LIST:
            return super().retrieveData(mimetype, preferred_type)
        urls = self._staged()
        if preferred_type.id() == QMetaType.Type.QByteArray.value:
            return QByteArray(b"\r\n".join(u.toEncoded().data() for u in urls))
        return urls


def make_mime(paths: list, source: str, stage_fn: Optional[Callable[[], list]] = None) -> QMimeData:
    """The data of a drag: our own list (``source`` names the panel it came from), and file URLs for what lives on a drive. Items that
    do not live on a drive (an archive member, a server's file) get URLs too when ``stage_fn`` is given: it copies them out on demand."""
    real = [p for p in paths if not has_scheme(p)]
    on_drive = bool(real) and len(real) == len(paths)
    data = LazyFilesMime(stage_fn) if stage_fn is not None and not on_drive else QMimeData()
    data.setData(MIME, QByteArray(json.dumps({"source": source, "paths": list(paths)}).encode("utf-8")))
    if on_drive:
        data.setUrls([QUrl.fromLocalFile(p) for p in paths])
    data.setText("\n".join(paths))
    return data


def read_paths(data: QMimeData) -> tuple:
    """``(paths, source)`` of what is being dragged: ours exactly, or file URLs from another program (source ``None``)."""
    if data.hasFormat(MIME):
        try:
            doc = json.loads(bytes(data.data(MIME)).decode("utf-8"))
            return [str(p) for p in doc.get("paths", [])], doc.get("source")
        except (ValueError, UnicodeDecodeError):
            return [], None
    if data.hasUrls():
        return [os.path.normpath(u.toLocalFile()) for u in data.urls() if u.isLocalFile()], None
    return [], None


def content_of(data: QMimeData) -> Optional[tuple]:
    """``(kind, payload)`` of what a drop or the clipboard carries when it is not files: a picture (a ``QImage``) or some text (a ``str``).
    None when it holds files (those are handled as files), our own list, or nothing usable."""
    if data is None or data.hasFormat(MIME):
        return None
    if data.hasUrls():                                         # files are files; a link from a browser becomes a shortcut file
        web = [u for u in data.urls() if not u.isLocalFile() and u.scheme() in ("http", "https", "ftp")]
        if len(web) == len(data.urls()) and web:
            return newfile.LINK, web[0].toString()
        return None
    if data.hasImage():
        value = data.imageData()
        image = value if isinstance(value, QImage) else QImage(value)
        if not image.isNull():
            return newfile.IMAGE, image
    if data.hasText() and data.text().strip():
        return newfile.TEXT, data.text()
    return None


def can_drop(paths: list, dest: str, sep: str = os.sep) -> bool:
    """Whether dropping ``paths`` into the folder ``dest`` makes sense. Judged from the names alone (no disk): not onto an item
    itself, not into a folder inside what is dragged."""
    if not paths or not dest:
        return False
    d = path_key(dest).rstrip(sep + "/")
    for p in paths:
        k = path_key(p).rstrip(sep + "/")
        if d == k or d.startswith(k + sep) or d.startswith(k + "/"):
            return False
    return True


def all_in_folder(paths: list, dest: str, fs_dirname) -> bool:
    """Every dragged item already lies directly in ``dest`` (dropping them there would move nothing)."""
    key = path_key(dest).rstrip(os.sep + "/")
    return all(path_key(fs_dirname(p)).rstrip(os.sep + "/") == key for p in paths)


def label(paths: list) -> str:
    return os.path.basename(paths[0].rstrip("/" + chr(92))) if len(paths) == 1 else f"{len(paths)} items"
