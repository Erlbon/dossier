"""``dossier quit`` (also ``dossier exit`` and ``dossier --quit``): close every running Dossier of this user, as File > Quit (Ctrl+Q)
does, without a question. The window with its viewers and notepads, the stand-alone notepad (``dossier edit``) and the stand-alone
picture viewer (``dossier view``) each listen for it. A Dossier with unsaved text in a notepad does not close: it answers why, and the
command says so and ends with exit code 1. A copy or move that is running stops as with Ctrl+Q and is offered again at the next start.

The installer asks this before it replaces Dossier's files in an update (the family's update contract, ``UpdateQuitArgs``), so a running
Dossier saves its panels and closes itself instead of being closed by force.

Each listening Dossier writes a small file in ``running`` beside its settings file (one per user and settings file, as the notepad's
single-instance name): the name of its local server. ``quit_running`` reads them, asks each one, and removes the ones nobody answers on
(a Dossier that died)."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import time
from typing import Callable, Optional

from PyQt6.QtCore import QCoreApplication, QObject, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

WORDS = ("quit", "exit", "--quit")
SINCE = "2026-11-20#08"   # the first build that knows it: the installer asks only copies this new (installer/dossier.iss, InstalledKnowsQuit)
ANSWER_MS = 3000          # how long a running Dossier has to answer
CLOSE_MS = 15000          # how long the command waits for the ones that said yes to be gone (a copy stops between chunks first)


def running_dir(settings_file: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings_file)), "running")


def _name(settings_file: str, key: str) -> str:
    who = f"{getpass.getuser()}|{os.path.normcase(os.path.abspath(settings_file))}"
    return "dossier-quit-" + hashlib.sha1(who.encode("utf-8")).hexdigest()[:12] + "-" + key


class QuitListener(QObject):
    """Part of a running Dossier: answers ``dossier quit``. ``busy()`` gives why it cannot close now ("" when it can); ``close()``
    closes it. The answer goes out before it closes."""

    def __init__(self, owner: QObject, settings_file: str, kind: str, busy: Callable[[], str], close: Callable[[], None]) -> None:
        super().__init__(owner)
        self.kind, self.busy, self.close = kind, busy, close
        self.key = f"{os.getpid()}-{id(self):x}"
        self.folder = running_dir(settings_file)
        self.file = os.path.join(self.folder, self.key)
        self.name = _name(settings_file, self.key)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self.name)
        self.listening = self.server.listen(self.name)
        if self.listening:
            self.server.newConnection.connect(self._connected)
            try:
                os.makedirs(self.folder, exist_ok=True)
                with open(self.file, "w", encoding="utf-8") as f:
                    json.dump({"name": self.name, "kind": kind, "pid": os.getpid()}, f)
            except OSError:
                pass
        owner.destroyed.connect(lambda _o=None, f=self.file: _remove(f))
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def stop(self) -> None:
        _remove(self.file)
        try:
            self.server.close()
        except RuntimeError:
            pass

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._read(c))
            self._read(conn)

    def _read(self, conn) -> None:
        if not conn.canReadLine():
            return
        word = bytes(conn.readLine()).decode("utf-8", "replace").strip()
        if word != "quit":
            conn.disconnectFromServer()
            return
        reason = self.busy()
        conn.write(json.dumps({"kind": self.kind, "pid": os.getpid(), "closing": not reason, "reason": reason}).encode() + b"\n")
        conn.disconnectFromServer()                      # sends what is written first, then closes
        if not reason:
            QTimer.singleShot(0, self._close_now)

    def _close_now(self) -> None:
        self.stop()
        self.close()


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _ask(name: str) -> Optional[dict]:
    """Ask the Dossier on ``name`` to quit; its answer, or None when nobody answers."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(ANSWER_MS):
        return None
    socket.write(b"quit\n")
    end = time.monotonic() + ANSWER_MS / 1000
    while socket.bytesToWrite() > 0 and time.monotonic() < end:
        socket.waitForBytesWritten(20)
        QCoreApplication.processEvents()                 # (a Dossier in this same process, as in the tests, reads here)
    data = b""
    while b"\n" not in data and time.monotonic() < end:
        QCoreApplication.processEvents()                 # a Dossier in this same process (the tests) answers here
        socket.waitForReadyRead(20)
        data += bytes(socket.readAll())                  # also what came before it hung up
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            break
    data += bytes(socket.readAll())
    socket.abort()
    try:
        return json.loads(data.decode("utf-8").splitlines()[0])
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def quit_running(settings_file: str, close_ms: int = CLOSE_MS) -> list:
    """Ask every running Dossier of this settings file to quit. A list of answers (``kind``, ``pid``, ``closing``, ``reason``, and
    ``gone``: whether it had closed before ``close_ms`` ran out). Files nobody answers on are removed."""
    folder = running_dir(settings_file)
    try:
        keys = sorted(os.listdir(folder))
    except OSError:
        return []
    answers, waiting = [], []
    for key in keys:
        path = os.path.join(folder, key)
        try:
            with open(path, encoding="utf-8") as f:
                name = json.load(f)["name"]
        except (OSError, ValueError, KeyError, TypeError):
            _remove(path)
            continue
        answer = _ask(name)
        if answer is None:
            _remove(path)                                # a Dossier that died: nobody listens there
            continue
        answer["gone"] = False
        answers.append(answer)
        if answer.get("closing"):
            waiting.append((answer, path))
    end = time.monotonic() + close_ms / 1000
    while waiting and time.monotonic() < end:
        QCoreApplication.processEvents()
        for item in list(waiting):
            if not os.path.exists(item[1]):
                item[0]["gone"] = True
                waiting.remove(item)
        time.sleep(0.02)
    return answers


def unsaved_in(windows: list) -> list:
    """The file names with unsaved text in these notepad windows (a tabbed window's tabs, or a single notepad)."""
    names = []
    for win in windows:
        try:
            pages = win.pages() if hasattr(win, "pages") else [win]
            names += [os.path.basename(p.doc.path) or "an unnamed text" for p in pages if p.is_modified()]
        except RuntimeError:                             # a window already gone
            continue
    return names


LABELS = {"window": "Dossier", "notepad": "Dossier's notepad", "viewer": "Dossier's picture viewer"}


def main(settings_path: Optional[str] = None, out=print) -> int:
    """The command: say what closed and what did not. Exit code 0 when everything closed (or nothing ran), 1 when one stayed open."""
    from .app_settings import open_settings
    app = QCoreApplication.instance() or QCoreApplication(["dossier"])          # noqa: F841 (the local sockets need one)
    settings = open_settings(settings_path)
    answers = quit_running(settings.fileName())
    if not answers:
        out("No Dossier is running.")
        return 0
    code = 0
    for a in answers:
        label = LABELS.get(a.get("kind"), "Dossier")
        if not a.get("closing"):
            code = 1
            out(f"{label} stays open: {a.get('reason')}.")
        elif a.get("gone"):
            out(f"{label} closed.")
        else:
            code = 1
            out(f"{label} was asked to close but is still running.")
    return code
