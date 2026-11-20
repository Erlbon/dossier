"""``dossier edit``: the notepad on its own, with no file manager window behind it.

    dossier edit file [file...]

It is the same editor F4 opens (``gui/notepad.py``): the same encoding guess, line breaks and safe save. All the files go into one
window, each in its own tab. It is a program of its own and there is only one of it per user: a second ``dossier edit x`` (or a second
double-click in Explorer) hands its files to the running notepad, which opens them as new tabs and comes to the front, and the second
program ends. A file that does not exist opens as an empty text that is saved to that name (the file is made at the first Save, so closing
without saving leaves nothing behind); the folder it names must exist. Closing the last tab ends the program. The theme is what was
chosen in Settings, as for ``dossier view``.

``open_notepads`` is the one place that starts the standalone notepad (card 70).
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
import threading
import time
from typing import Callable, Optional

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

USAGE = "dossier edit file [file...]"
HANDOVER_WAIT_MS = 500            # how long a second start waits for the running notepad to take its files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dossier edit", description="Edit text files in Dossier's notepad, without the file manager.",
                                     epilog="A file that does not exist opens as an empty text and is made when you save.")
    parser.add_argument("paths", nargs="+", metavar="file", help="a text file; each one opens in its own tab")
    return parser


def document_for(path: str):
    """``(Document, note)`` for a path: the file as F4 reads it, or for a missing file an empty text that will be saved there.
    Raises the errors ``load_document`` raises (OSError, FileTooLarge, BinaryFile, EncodingProblem); a missing folder is an OSError."""
    from ..core.textedit import Document, load_document
    if not os.path.exists(path):
        folder = os.path.dirname(path) or "."
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"The folder {folder} does not exist")
        return Document(path, "", "utf-8"), "New file: it is made when you save"
    if os.path.isdir(path):
        raise IsADirectoryError(f"{path} is a folder, not a file")
    return load_document(path), ""


def load_documents(paths: list) -> tuple:
    """``(loaded, problems)``: ``loaded`` is a list of ``(path, Document, note)``, ``problems`` a list of texts for the files that
    could not be read. Reads the disk, so it is called on a thread once the window is up."""
    from ..core.textedit import BinaryFile, EncodingProblem, FileTooLarge
    loaded: list = []
    problems: list = []
    for given in paths:
        path = os.path.abspath(given)
        try:
            doc, note = document_for(path)
        except FileTooLarge as e:
            problems.append(f"{path}: {e}. Use dossier view to read it.")
            continue
        except BinaryFile:
            problems.append(f"{path} looks like a binary file, not text.")
            continue
        except (OSError, EncodingProblem) as e:
            problems.append(f"{path} could not be opened: {getattr(e, 'strerror', None) or e}")
            continue
        loaded.append((path, doc, note))
    return loaded, problems


def server_name_for(settings) -> str:
    """The name the running notepad listens on: one per user and per settings file, so two users, or a test profile, never meet."""
    key = f"{getpass.getuser()}|{os.path.normcase(os.path.abspath(str(settings.fileName())))}"
    return "dossier-notepad-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def hand_over(name: str, paths: list, wait_ms: int = HANDOVER_WAIT_MS) -> bool:
    """Give the files (as absolute paths) to the notepad listening on ``name``. False when nobody answers (none runs, or a stale name)."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(wait_ms):
        return False
    socket.write(json.dumps([os.path.abspath(p) for p in paths]).encode("utf-8") + bytes([10]))
    end = time.monotonic() + wait_ms / 1000
    while socket.bytesToWrite() > 0 and time.monotonic() < end:
        socket.waitForBytesWritten(20)
        QCoreApplication.processEvents()                   # (a notepad in this same process, as in the tests, reads here)
    if socket.bytesToWrite() > 0:
        return False                                       # a notepad that takes nothing is not running
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(wait_ms)
    return True


class NotepadSession(QObject):
    """What lives as long as the standalone notepad window: the server that takes files from later starts, and the loading of them."""

    _loaded = pyqtSignal(object, object)

    def __init__(self, host, settings, dialogs, problem: Callable[[str], None]) -> None:
        super().__init__(host)
        self.host = host
        self.settings = settings
        self.dialogs = dialogs
        self.problem = problem
        self.server: Optional[QLocalServer] = None
        self._buffers: dict = {}
        self._loaded.connect(self._add)

    def listen(self, name: str) -> bool:
        """Start taking files on ``name``. A name left by a notepad that died is removed first (the caller found nobody on it)."""
        QLocalServer.removeServer(name)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(name):
            self.server = None
            return False
        self.server.newConnection.connect(self._connected)
        return True

    def close_server(self) -> None:
        if self.server is not None:
            self.server.close()

    def _connected(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            self._buffers[conn] = bytearray()
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(lambda c=conn: self._finish(c))
            self._read(conn)

    def _read(self, conn) -> None:
        buf = self._buffers.get(conn)
        if buf is None:
            return
        buf += bytes(conn.readAll())
        if bytes([10]) in buf:
            self._finish(conn)

    def _finish(self, conn) -> None:
        buf = self._buffers.pop(conn, None)
        if buf is None:
            return
        try:
            paths = [p for p in json.loads(bytes(buf).decode("utf-8")) if isinstance(p, str)]
        except (ValueError, UnicodeDecodeError):
            paths = []
        conn.disconnectFromServer()
        conn.deleteLater()
        if paths:
            self.open_paths(paths)

    def open_paths(self, paths: list) -> None:
        """Open files as new tabs (the ones already open are only brought forward). The files are read on a thread."""
        paths = [os.path.abspath(p) for p in paths]
        fresh = []
        for p in paths:
            page = self.host.page_for(p)
            if page is not None:
                self.host.show_page(page)
            else:
                fresh.append(p)
        if not fresh:
            return

        def work() -> None:
            result = load_documents(fresh)
            try:
                self._loaded.emit(*result)
            except RuntimeError:                       # the window is gone
                pass
        threading.Thread(target=work, daemon=True).start()

    def _add(self, loaded: list, problems: list) -> None:
        for text in problems:
            self.problem(text)
        add_documents(self.host, loaded, self.settings, self.dialogs)
        if loaded:
            self.host.show_page(self.host.current_page())


def add_documents(host, loaded: list, settings, dialogs) -> int:
    """Add a tab for each ``(path, Document, note)`` in ``loaded``; a file open in a tab already is not added twice."""
    from .notepad import new_page
    added = 0
    for path, doc, note in loaded:
        if host.page_for(path) is not None:
            continue
        page = new_page(doc, dialogs, settings)
        host.add_page(page)
        if note:
            page.message.setText(note)
        added += 1
    return added


def open_notepads(paths: list, settings, dialogs, problem: Callable[[str], None], windows: list, *,
                  server_name: Optional[str] = None) -> int:
    """Start the standalone notepad for ``paths``. With a ``server_name`` it is a single instance: if a notepad already listens on that
    name the files are handed to it (it opens them as tabs and comes to the front) and nothing is opened here (``windows`` stays
    empty); otherwise this one opens a window with a tab per file and listens on the name, taking over a stale one.
    ``problem(text)`` says why a file was not opened. Returns how many files were opened or handed over."""
    try:
        from .notepad import NotepadTabs
    except ImportError:
        problem("The editor needs the PyQt6-QScintilla package: pip install PyQt6-QScintilla")
        return 0
    if server_name and hand_over(server_name, paths):
        return len(paths)
    loaded, problems = load_documents(paths)
    for text in problems:
        problem(text)
    if not loaded:
        return 0
    host = NotepadTabs()
    host.session = NotepadSession(host, settings, dialogs, problem)
    add_documents(host, loaded, settings, dialogs)
    windows.append(host)
    host.closed.connect(lambda w: windows.remove(w) if w in windows else None)
    host.closed.connect(lambda _w: host.session.close_server())
    if server_name and not host.session.listen(server_name):
        problem("Later files will open in new windows: the notepad could not listen for them.")
    from .quit_command import QuitListener, unsaved_in

    def busy() -> str:
        names = unsaved_in([host])
        return f"it has unsaved changes in {', '.join(names)}" if names else ""
    host.quit_listener = QuitListener(host, settings.fileName(), "notepad", busy, host.close)     # dossier quit
    host.show()
    return len(loaded)


def main(args: list, *, settings_path: Optional[str] = None, show: bool = True,
         problem: Optional[Callable[[str], None]] = None, windows: Optional[list] = None,
         server_name: Optional[str] = None) -> int:
    ns = build_parser().parse_args(args)
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from ..core.platform import set_app_id
    from .app_settings import open_settings
    from .appicon import app_icon
    from .dialogs import Dialogs
    from .theme import ThemeManager

    set_app_id("Erlbon.Dossier.Notepad")
    app = QApplication.instance() or QApplication(["dossier"])
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())
    settings = open_settings(settings_path)
    manager = ThemeManager(app, str(settings.value("view/scheme", "auto")))
    if problem is None:
        def problem(text: str) -> None:
            QMessageBox.warning(None, "Dossier notepad", text)
    held = windows if windows is not None else []
    if server_name is None and show:
        server_name = server_name_for(settings)
    if not open_notepads(ns.paths, settings, Dialogs(None), problem, held, server_name=server_name):
        return 2
    if not held:
        return 0                                                          # the files went to the notepad that is already running
    held[0]._theme = manager                                              # kept alive as long as the window
    if not show:
        return 0
    from .app import leave
    return leave(app.exec())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
