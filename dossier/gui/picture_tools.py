"""What the two picture viewers (View as Glass and pictures in F3) share beyond the picture widget itself:

- reading a picture with its EXIF and, for an animated GIF or WebP, its bytes to play (94A): ``read_picture``;
- reading the next and the previous picture ahead and keeping the last few in memory, at most ``CACHE_BYTES`` (92A): ``ReadAhead``;
- the facts card at the top right (90A): ``FactsCard``;
- Delete to the Recycle Bin (88A), keeping a turn in a JPEG (89A) and Open With / Edit Pictures With (95B): ``PictureActions``, a part
  of each viewer window. The window gives ``paths``, ``index``, the picture widget and a way to say things.

The disk is read and written on threads only (the window's thread never touches it)."""
from __future__ import annotations

import os
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QColor, QImage, QImageReader
from PyQt6.QtWidgets import QLabel, QMenu, QMessageBox, QWidget

from ..core import exif as exif_mod
from ..core import tools, viewmodes
from ..core.drives import no_recycle_bin
from ..core.exif import Exif, read_exif
from ..core.platform import open_with_command
from ..core.sizefmt import human_size
from ..core.trash import TITLE as TRASH_TITLE
from ..core.worker import Job, JobRunner, JobState
from . import theme

CACHE_BYTES = 300 * 1024 * 1024          # the pictures kept in memory for instant stepping (92A)
MOVING = (b"GIF8", b"RIFF")              # a GIF or a WebP may move (94A)


@dataclass
class Picture:
    image: QImage                        # the first frame, upright by its EXIF
    exif: Optional[Exif] = None
    size: int = 0                        # bytes of the file
    movie: bytes = b""                   # the whole file, when it is an animated GIF or WebP
    kind: str = ""                       # the format its first bytes show (png, jpeg...)

    def cost(self) -> int:
        return self.image.sizeInBytes() + len(self.movie)


def is_animated(data: bytes) -> bool:
    """Whether a GIF's or a WebP's bytes hold more than one frame."""
    if data[:4] not in MOVING or (data[:4] == b"RIFF" and data[8:12] != b"WEBP"):
        return False
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    return reader.supportsAnimation() and reader.imageCount() != 1


def read_picture(path: str) -> Picture:
    """The picture at ``path`` with its EXIF and size; for an animated GIF or WebP also its bytes. On a thread; a null image when the
    file cannot be decoded."""
    from .image_view import read_image
    image = read_image(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    movie = b""
    if not image.isNull() and size and path.lower().endswith((".gif", ".webp")):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            data = b""
        movie = data if is_animated(data) else b""
    return Picture(image, read_exif(path), size, movie, viewmodes.image_kind(viewmodes.read_head(path), path))


class ReadAhead:
    """The pictures read so far, the most recently used last, at most ``budget`` bytes; and the reading of the neighbours of the one
    shown, on a thread of its own, so the picture asked for is never kept waiting behind one read ahead (92A)."""

    def __init__(self, dispatch, budget: int = CACHE_BYTES, reader: Callable[[str], Picture] = read_picture) -> None:
        self._runner = JobRunner(dispatch)
        self._read = reader
        self.budget = budget
        self._kept: OrderedDict = OrderedDict()
        self._bytes = 0
        self._pending: set = set()
        self.closed = False

    def get(self, path: str) -> Optional[Picture]:
        picture = self._kept.get(path)
        if picture is not None:
            self._kept.move_to_end(path)
        return picture

    def put(self, path: str, picture: Picture) -> None:
        if picture is None or picture.image.isNull():
            return
        self.drop(path)
        self._kept[path] = picture
        self._bytes += picture.cost()
        while len(self._kept) > 1 and self._bytes > self.budget:
            _p, old = self._kept.popitem(last=False)                    # the least recently used go first
            self._bytes -= old.cost()

    def drop(self, path: str) -> None:
        old = self._kept.pop(path, None)
        if old is not None:
            self._bytes -= old.cost()

    def kept(self) -> list:
        return list(self._kept)

    def used(self) -> int:
        return self._bytes

    def read_ahead(self, paths: list) -> None:
        """Read these pictures (the next and the previous) unless they are kept or being read already."""
        for path in paths:
            if self.closed or not path or path in self._kept or path in self._pending:
                continue
            self._pending.add(path)

            def work(progress, cancel, path=path):
                return self._read(path)

            def finished(job: Job, path=path) -> None:
                self._pending.discard(path)
                if not self.closed and job.state is JobState.DONE and job.result is not None:
                    self.put(path, job.result)

            self._runner.submit("Read ahead", work, on_done=finished)

    def idle(self) -> bool:
        return not self._pending

    def close(self) -> None:
        self.closed = True
        self._kept.clear()
        self._bytes = 0
        self._runner.shutdown(wait=False, cancel_futures=True)


class FactsCard(QLabel):
    """The small glass card at the top right with a photo's few facts (90A): name, dimensions and size, date taken, camera and lens,
    exposure. It stays while the owner steps through the pictures."""

    MARGIN = 18

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("factscard")
        fg = QColor(theme.current()["fg"])
        self.setStyleSheet(f"QLabel#factscard {{ background: rgba({fg.red()}, {fg.green()}, {fg.blue()}, 38); color: {fg.name()};"
                           f" border-radius: 14px; padding: 10px 16px; font-size: 14px; }}")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lines: list = []
        self.hide()

    def show_facts(self, lines: list) -> None:
        from html import escape
        self.lines = list(lines)
        if not lines:
            self.setText("")
        else:
            rest = "".join(f"<br>{escape(x)}" for x in lines[1:])
            self.setText(f"<b>{escape(lines[0])}</b>{rest}")
        self.adjustSize()
        self.place()

    def place(self) -> None:
        host = self.parentWidget()
        margin = max(self.MARGIN, host.height() // 40)
        self.move(max(0, host.width() - self.width() - margin), margin)
        self.raise_()


def facts_for(path: str, picture: Optional[Picture]) -> list:
    if picture is None:
        return [os.path.basename(path)]
    return exif_mod.photo_facts(os.path.basename(path), picture.image.width(), picture.image.height(),
                                human_size(picture.size) if picture.size else "", picture.exif)


def default_launcher(program: str, path: str) -> None:
    """Start ``program`` with the picture (95B), as a tools-bar tool is started."""
    tools.launch(tools.Tool(os.path.basename(program), program, "{file}"), [path], os.path.dirname(path), "")


def default_open_with(menu: QMenu, path: str) -> None:
    """Open With for a viewer that has no Dossier window behind it (``dossier view``): the system's own chooser on Windows, the
    programs the system names for the type on the Mac and Linux."""
    from ..core.open_with import SystemPrograms
    programs = SystemPrograms()
    if programs.system == "linux":
        programs.load_now()
    for p in programs.for_file(path):
        menu.addAction(p.name + (" (default)" if p.default else "")).triggered.connect(
            lambda _c=False, p=p: tools.launch(tools.Tool(p.name, p.path, "{files}"), [path], os.path.dirname(path), ""))
    chooser = open_with_command(path)
    if chooser is not None:
        if menu.actions():
            menu.addSeparator()
        menu.addAction("Choose Another Program...").triggered.connect(lambda _c=False: subprocess.Popen(chooser))


def retry_while_busy(path: str, act: Callable[[], None]) -> None:
    """``act()`` on the file at ``path``, tried again for about a second while it fails: Windows refuses to delete or replace a file
    that is open, and the picture may be being read ahead on another thread just then (or looked at by a virus scanner)."""
    for wait in (0.05, 0.1, 0.15, 0.2, 0.25, 0.25, 0):
        try:
            act()
            return
        except exif_mod.NotWritable:
            raise
        except OSError:
            if not wait or not os.path.exists(path):
                raise
            time.sleep(wait)


EDITOR_KEY = "viewer/picture_editor"     # Settings > Opening Files > Edit Pictures With (95B)


class PictureActions:
    """Part of a viewer window: Delete (88A), keeping a turn (89A), Open With and E (95B). The window has ``paths``, ``index``,
    ``_runner`` (a ``JobRunner``), ``cache`` (a ``ReadAhead``) and these:
    ``_picture_view()`` the ``ImageView``; ``_tell(text)`` says something for a few seconds; ``_after_delete()`` shows what is at
    ``index`` now (or closes when nothing is left); ``_picture_settings`` a QSettings or None."""

    def setup_picture_actions(self, settings=None, trasher: Optional[Callable] = None, ask: Optional[Callable] = None,
                              open_with: Optional[Callable] = None, launcher: Optional[Callable] = None,
                              changed: Optional[Callable] = None) -> None:
        from ..core.ops import default_trash
        self._picture_settings = settings
        self._trasher = trasher or default_trash
        self._ask = ask or self._ask_box
        self._open_with = open_with or default_open_with
        self._launcher = launcher or default_launcher
        self._file_changed = changed or (lambda path: None)        # the window behind: the panel's thumbnail is old now
        self._deleting: set = set()
        self._said_look_only = False
        self._said_kept = False

    def _ask_box(self, title: str, text: str, ok_label: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=self)
        ok = box.addButton(ok_label, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is ok

    # 88A: Delete -----------------------------------------------------------------------------------------------------------------
    def delete_picture(self) -> None:
        """The picture to the Recycle Bin, no question, and the next one shown. A drive with no bin asks first and says it is for
        good. Dossier's undo does not cover it; Put Back in the Recycle Bin place does."""
        if not self.paths:
            return
        path = self.paths[self.index]
        if path in self._deleting:
            return
        name = os.path.basename(path)
        if no_recycle_bin(path):
            if not self._ask("Delete", f"{name} is on a drive with no {TRASH_TITLE}, so it is deleted for good. It cannot be brought "
                                       "back.", "Delete for Good"):
                return
            remove, said = os.remove, f"{name} is deleted for good"
        else:
            remove, said = self._trasher, f"{name} is in the {TRASH_TITLE}"
        self._deleting.add(path)

        def work(progress, cancel):
            retry_while_busy(path, lambda: remove(path))

        def finished(job: Job) -> None:
            self._deleting.discard(path)
            if job.state is not JobState.DONE:
                self._tell(f"{name} could not be deleted: {getattr(job.error, 'strerror', None) or job.error}")
                return
            self.cache.drop(path)
            self._file_changed(path)
            if path in self.paths:
                at = self.paths.index(path)
                del self.paths[at]
                if at < self.index or self.index >= len(self.paths):
                    self.index = max(0, self.index - 1)
            self._after_delete()
            self._tell(said)

        self._runner.submit("Delete", work, on_done=finished)

    # 89A: a turn of a JPEG is kept in its EXIF ---------------------------------------------------------------------------------------
    def keep_turn(self, quarters: int) -> None:
        """Called after the picture was turned on screen: a JPEG gets the turn in its EXIF Orientation at once (the picture is not
        written again and the file keeps its date); any other kind is turned for looking only, which is said the first time."""
        if not self.paths:
            return
        path = self.paths[self.index]

        def work(progress, cancel):
            if not exif_mod.is_jpeg(path):
                return "look"
            before = read_exif(path).orientation
            retry_while_busy(path, lambda: exif_mod.write_orientation(path, exif_mod.turned(before, quarters)))
            return "kept"

        def finished(job: Job) -> None:
            name = os.path.basename(path)
            if job.state is not JobState.DONE:
                self._tell(f"The turn of {name} could not be kept, it is for looking only: "
                           f"{getattr(job.error, 'strerror', None) or job.error}")
                return
            if job.result == "look":
                if not self._said_look_only:
                    self._said_look_only = True
                    self._tell(f"Turned for looking only: only a JPEG keeps its turn, and {name} is not one")
                return
            self.cache.drop(path)                                           # read again, turned by its new EXIF
            self._file_changed(path)
            if not self._said_kept:
                self._said_kept = True
                self._tell(f"The turn is kept in {name}; its date is unchanged")

        self._runner.submit("Keep the turn", work, on_done=finished)

    # 95B: Open With and E -------------------------------------------------------------------------------------------------------------
    def picture_editor(self) -> str:
        s = self._picture_settings
        return str(s.value(EDITOR_KEY, "") or "") if s is not None else ""

    def edit_picture(self) -> None:
        """E: the picture in the program set in Settings > Opening Files > Edit Pictures With. The viewer stays open."""
        if not self.paths:
            return
        path = self.paths[self.index]
        program = self.picture_editor()
        if not program:
            self._tell("No program is set for E: choose one in Settings > Opening Files > Edit Pictures With")
            return
        try:
            self._launcher(program, path)
        except (OSError, tools.BadTool) as e:
            self._tell(f"Could not start {os.path.basename(program)}: {getattr(e, 'strerror', None) or e}")
            return
        self._tell(f"Opened {os.path.basename(path)} in {os.path.splitext(os.path.basename(program))[0]}")

    def add_picture_menu(self, menu: QMenu) -> None:
        """Open With (the same programs as the panel's Open With for this kind of file) and Edit in the program for E."""
        if not self.paths:
            return
        path = self.paths[self.index]
        sub = menu.addMenu("Open With")
        self._open_with(sub, path)
        sub.setEnabled(bool(sub.actions()))
        program = self.picture_editor()
        label = f"Edit in {os.path.splitext(os.path.basename(program))[0]}" if program else "Edit Pictures With: Not Set"
        act = menu.addAction(label + chr(9) + "E")
        act.setToolTip("" if program else "Settings > Opening Files > Edit Pictures With")
        act.triggered.connect(lambda _c=False: self.edit_picture())
