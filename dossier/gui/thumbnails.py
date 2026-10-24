"""Thumbnails for the icon view: made on worker threads, kept in memory, shown when they are ready.

The window thread never reads a picture. ``Thumbnails.get`` returns what is already made (or None) and ``request`` queues the work;
a few threads decode and scale (QImage is safe off the window thread, QPixmap is not), and each result is turned into a pixmap on the
window thread, where a ``ready(path)`` signal tells the model to redraw that one item. Only the items the view asks for are made, so a
folder of thousands costs what is on screen. Network drives and video are off until the owner switches them on in Settings.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Optional

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import QApplication

from ..core import covers

CACHE_ITEMS = 800
CACHE_BYTES = 96 * 1024 * 1024                      # and never more than this much picture memory: 800 huge thumbnails would be about 200 MB
THREADS = 4
STEPS = (64, 96, 128, 192, 256)                     # the thumbnail sizes: small, medium, large, extra large, huge
SIZE_NAMES = {64: "Small", 96: "Medium", 128: "Large", 192: "Extra Large", 256: "Huge"}


def scaled(image: QImage, px: int) -> QImage:
    """``image`` fitted inside a ``px`` square, smooth, never enlarged."""
    if image.isNull():
        return image
    if image.width() > px or image.height() > px:
        return image.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return image


def read_file(path: str, px: int) -> QImage:
    """Decode an image file straight to a thumbnail size (the decoder scales while reading where the format allows)."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)                       # a photo taken upright shows upright
    size = reader.size()
    if size.isValid() and (size.width() > px or size.height() > px):
        size.scale(QSize(px, px), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    return scaled(image, px)


def read_bytes(data: bytes, px: int) -> QImage:
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    return scaled(reader.read(), px)


def make(kind: str, path: str, px: int, ffmpeg: str = "") -> Optional[QImage]:
    """The thumbnail of one item, or None when it has no picture. Runs on a worker thread."""
    found = covers.picture_for(kind, path, ffmpeg, px)
    if found is None:
        return None
    image = read_file(found[1], px) if found[0] == "file" else read_bytes(found[1], px)
    return None if image.isNull() else image


class _Done(QObject):
    done = pyqtSignal(str, object)                      # (key, QImage or None), emitted from the worker thread


class _Job(QRunnable):
    def __init__(self, key: str, kind: str, path: str, px: int, ffmpeg: str, signals: _Done) -> None:
        super().__init__()
        self.key, self.kind, self.path, self.px, self.ffmpeg, self.signals = key, kind, path, px, ffmpeg, signals

    def run(self) -> None:
        try:
            image = make(self.kind, self.path, self.px, self.ffmpeg)
        except Exception:   # noqa: BLE001 -- a picture that cannot be made is just a missing picture
            image = None
        self.signals.done.emit(self.key, image)


class Thumbnails(QObject):
    ready = pyqtSignal(str)                             # a path whose thumbnail is now available (or known to be missing)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(THREADS)
        self._signals = _Done(self)
        self._signals.done.connect(self._finished)
        self._cache: OrderedDict = OrderedDict()         # key -> QPixmap, or None for "has no picture"
        self._bytes = 0                                  # what the pixmaps in the cache take
        self._pending: dict = {}                         # key -> path
        app = QApplication.instance()
        self.ratio = (app.devicePixelRatio() if app is not None else 1.0) or 1.0     # screen pixels per logical pixel
        self.on_network = False                          # make thumbnails for files on network drives too
        self.video = False                               # grab a frame from videos (needs ffmpeg)
        self.ffmpeg = ""

    # asking ----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def key(path: str, mtime: float, size: int, px: int) -> str:
        return f"{px}|{int(mtime)}|{size}|{path}"

    def wanted(self, kind: str, network: bool) -> bool:
        """Whether this kind of item gets a thumbnail under the current settings."""
        if not kind or (network and not self.on_network):
            return False
        return not (kind == "video" and not (self.video and self.ffmpeg))

    def get(self, key: str):
        """``(known, pixmap)``: known is False while the thumbnail has not been tried; the pixmap is None for an item with no picture."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return True, self._cache[key]
        return False, None

    def request(self, key: str, kind: str, path: str, px: int) -> None:
        if key in self._cache or key in self._pending:
            return
        self._pending[key] = path
        self.pool.start(_Job(key, kind, path, max(16, int(px * self.ratio)), self.ffmpeg, self._signals))

    def clear(self) -> None:
        self._cache.clear()
        self._bytes = 0

    # results ---------------------------------------------------------------------------------------------------------------
    def _finished(self, key: str, image) -> None:
        path = self._pending.pop(key, "")
        pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) and not image.isNull() else None
        if pixmap is not None:
            pixmap.setDevicePixelRatio(self.ratio)                # made at screen resolution, drawn at the size asked for
        self._bytes -= self._size_of(self._cache.pop(key, None))
        self._cache[key] = pixmap
        self._bytes += self._size_of(pixmap)
        while len(self._cache) > 1 and (len(self._cache) > CACHE_ITEMS or self._bytes > CACHE_BYTES):
            self._bytes -= self._size_of(self._cache.popitem(last=False)[1])           # the least recently used go first
        if path:
            self.ready.emit(path)

    @staticmethod
    def _size_of(pixmap) -> int:
        """The memory a cached picture takes, in bytes (a pixmap's size is in screen pixels, four bytes each)."""
        return 0 if pixmap is None else pixmap.width() * pixmap.height() * 4

    def idle(self) -> bool:
        return not self._pending

    def shutdown(self) -> None:
        self.pool.clear()
        self.pool.waitForDone(2000)


def nearest_step(px: int) -> int:
    return min(STEPS, key=lambda s: abs(s - px))


def step_by(px: int, direction: int) -> int:
    i = STEPS.index(nearest_step(px))
    return STEPS[max(0, min(len(STEPS) - 1, i + direction))]
