"""Edit > Paste Picture or Text as New File..., Ctrl+V with no files on the clipboard, and dropping a picture or text on a panel.

The clipboard (or the drop) holds content, not files. After asking for a name (suggested from the time, with the extension the kind needs)
the window encodes the picture or text and writes the file on a thread with ``core/newfile.py``, which never replaces an existing file.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from ..core import newfile
from .background import run_in_background
from .dragdrop import content_of

IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPG", ".jpeg": "JPG", ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP"}


def encode(kind: str, payload, name: str) -> bytes:
    """The bytes of a file called ``name`` for a picture (in the format its extension names, PNG otherwise) or for text (UTF-8)."""
    if kind == newfile.TEXT:
        return str(payload).encode("utf-8")
    if kind == newfile.LINK:
        return newfile.link_file(str(payload))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = payload if isinstance(payload, QImage) else QImage(payload)
    if not image.save(buffer, IMAGE_FORMATS.get(os.path.splitext(name)[1].lower(), "PNG")):
        raise OSError("the picture could not be encoded as " + name)
    return bytes(buffer.data())


class NewFromContentMixin:
    """Part of ``MainWindow``."""

    def clipboard_content(self) -> Optional[tuple]:
        return content_of(QApplication.clipboard().mimeData())

    def paste_content(self) -> bool:
        """Ctrl+V with no files on the clipboard: a picture or text there becomes a new file in the active panel's folder.
        Returns False when the clipboard holds neither."""
        found = self.clipboard_content()
        if found is None:
            return False
        self._new_file_from_content(found[0], found[1], self.active.path)
        return True

    def paste_as_new_file(self) -> None:
        if self._home_blocked("Paste"):
            return
        if not self.paste_content():
            self._say("The clipboard holds no picture or text to make a file of")

    def _new_file_from_content(self, kind: str, payload, folder: str) -> None:
        if not self.fs.is_writable(folder) or folder.startswith("zip://"):
            self._say("A file cannot be made here: this place is read-only (an open archive, a catalogue, or the Home page)")
            return
        suggested = newfile.suggested_name(kind, datetime.now(), str(payload) if kind == newfile.LINK else "")
        while True:
            answer = self.dialogs.ask_text("Paste as New File", f"Name for the new {newfile.WORDS[kind]} file in {folder}:", suggested)
            if not answer:
                return
            try:
                name = newfile.clean_name(answer, kind)
                break
            except ValueError as e:
                self.dialogs.info("Paste as New File", f"{answer}: {e}")
                suggested = answer

        def work(progress, cancel):
            return newfile.write_new_file(self.fs, folder, name, encode(kind, payload, name))

        def finished(path) -> None:
            if path is None:
                return
            made = self.fs.basename(path)
            for panel in (self.left, self.right):
                if not panel.is_home and panel.path == folder:
                    panel.set_folder(panel.path, select=made)
            self._say(f"Made {made}")
        run_in_background(self, self.cmd_runner, "Making the file", work, on_result=finished, tracked=self._size_jobs,
                          failed_title="Paste as New File")
