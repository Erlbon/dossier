"""Dragging files between the panels, inside a panel, and to and from other programs (Explorer, Nautilus).

What travels is a list of paths. Inside Dossier they travel exactly (any file system, an archive member too) in our own format; for
files on a drive they also travel as the usual file URLs, so Explorer and other programs can take them and Dossier can take what they
drop. The decision between move and copy is made at the drop, from the keys held down, and (if no key decides) from the drives: one
drive moves, two drives copy.
"""
from __future__ import annotations

import json
import os
from PyQt6.QtCore import QByteArray, QMimeData, QUrl

from ..core.platform import has_scheme, path_key

MIME = "application/x-dossier-paths"


def make_mime(paths: list, source: str) -> QMimeData:
    """The data of a drag: our own list (``source`` names the panel it came from), and file URLs for what lives on a drive."""
    data = QMimeData()
    data.setData(MIME, QByteArray(json.dumps({"source": source, "paths": list(paths)}).encode("utf-8")))
    real = [p for p in paths if not has_scheme(p)]
    if real and len(real) == len(paths):
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
