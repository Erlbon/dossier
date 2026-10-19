"""Files on the system clipboard, the way Explorer, Nautilus and Dolphin put them there.

A copy puts the file URLs on the clipboard; a cut adds the "move, don't copy" hint each desktop uses:
Windows ``Preferred DropEffect`` (4 bytes, 2 = move), GNOME ``x-special/gnome-copied-files`` (first line
``cut`` or ``copy``) and KDE ``application/x-kde-cutselection`` (``1``). Reading understands all three, so
Dossier pastes what Explorer copied and Explorer pastes what Dossier copied.

Items that are not real files (a memory file system, a scheme path) cannot be named by a URL; they live in
an in-process copy only, which is also what the tests use.
"""
from __future__ import annotations

import os
import struct
from typing import Optional

from PyQt6.QtCore import QByteArray, QMimeData, QUrl
from PyQt6.QtWidgets import QApplication

from ..core.platform import has_scheme

WIN_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
GNOME = "x-special/gnome-copied-files"
KDE_CUT = "application/x-kde-cutselection"
DROP_COPY, DROP_MOVE = 1, 2

_inner: Optional[tuple] = None        # (paths, cut, mime data we put there): for items a URL cannot name


def put(paths: list, cut: bool) -> None:
    """Copy or cut ``paths`` to the clipboard."""
    global _inner
    paths = list(paths)
    data = QMimeData()
    real = [p for p in paths if not has_scheme(p)]
    if real and len(real) == len(paths):
        urls = [QUrl.fromLocalFile(p) for p in paths]
        data.setUrls(urls)
        data.setData(WIN_EFFECT, QByteArray(struct.pack("<I", DROP_MOVE if cut else DROP_COPY)))
        lines = "\n".join(u.toString() for u in urls)
        data.setData(GNOME, QByteArray((("cut" if cut else "copy") + "\n" + lines).encode("utf-8")))
        if cut:
            data.setData(KDE_CUT, QByteArray(b"1"))
    data.setText("\n".join(paths))                      # pasting into a text field gives the paths
    QApplication.clipboard().setMimeData(data)
    _inner = (paths, cut, data)


def get() -> tuple:
    """(paths, cut) from the clipboard; ([], False) when it holds no files."""
    data = QApplication.clipboard().mimeData()
    if data is None:
        return [], False
    if _inner is not None and data is _inner[2]:        # our own, untouched: exact paths, any file system
        return list(_inner[0]), _inner[1]
    paths = [os.path.normpath(u.toLocalFile()) for u in data.urls() if u.isLocalFile()] if data.hasUrls() else []
    if not paths:
        return [], False
    return paths, _is_cut(data)


def _is_cut(data) -> bool:
    if data.hasFormat(WIN_EFFECT):
        raw = bytes(data.data(WIN_EFFECT))
        if len(raw) >= 4:
            return bool(struct.unpack("<I", raw[:4])[0] & DROP_MOVE) and not struct.unpack("<I", raw[:4])[0] & DROP_COPY
    if data.hasFormat(GNOME):
        return bytes(data.data(GNOME)).split(b"\n", 1)[0].strip() == b"cut"
    if data.hasFormat(KDE_CUT):
        return bytes(data.data(KDE_CUT)).strip() == b"1"
    return False


def clear_if_ours(paths: list) -> None:
    """After a cut was pasted the clipboard no longer names files that exist."""
    global _inner
    now, cut = get()
    if cut and now == list(paths):
        QApplication.clipboard().clear()
        _inner = None
