"""Servers in the window: the saved connections, the connect flow (host key, login, session), and the Home page's Servers section.

Nothing is contacted until the owner opens a server. Then, in order, and each step on a thread with a Cancel:

1. the server's host keys are fetched; a key never seen is shown with its fingerprint and needs the owner's approval, and a key that is
   different from the approved one is a loud warning (the sign of a man in the middle) that blocks the connection;
2. the login is tried with what is already at hand (a saved password, else the user's keys and the ssh-agent);
3. only if the server refuses that is a password asked for, with the choice of keeping it in the system's password store.

The connection is then a session of the SFTP file system, and the panel opens the server's folder like any other. A new connection is
read-only until the owner switches that off for it.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QSpinBox, QVBoxLayout)

from ..core import davclient, ftpclient, servers, sshlink
from ..core.home import ADD_SERVER, ServerItem
from ..core.sftpfs import Session, scheme_of, split_path
from .background import run_in_background

SETTINGS_KEY = "servers/list"


class ConnectionDialog(QDialog):
    def __init__(self, parent, conn: Optional[servers.Connection] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit the Server" if conn else "Add a Server")
        self.setMinimumWidth(520)
        c = conn or servers.Connection("", "")
        self.base = c
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(c.name)
        self.name.setPlaceholderText("for example  The NAS")
        self.protocol = QComboBox()
        for key, text in servers.PROTOCOLS:
            self.protocol.addItem(text, key)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(c.protocol)))
        self.host = QLineEdit(c.host)
        self.host.setPlaceholderText("files.example.com  or  192.168.1.20")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(c.port)
        self.user = QLineEdit(c.user)
        self.key_file = QLineEdit(c.key_file)
        self.key_file.setPlaceholderText("empty: your usual keys and the ssh-agent")
        browse = QPushButton("Browse...")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_file, 1)
        key_row.addWidget(browse)
        self.start_dir = QLineEdit(c.start_dir)
        self.start_dir.setPlaceholderText("empty: the folder the server opens on login")
        self.read_only = QCheckBox("Read-only: nothing on the server can be changed from Dossier")
        self.read_only.setChecked(c.read_only)
        self.remember = QCheckBox("Keep the password in the system's password store (otherwise it is asked for when needed)")
        self.remember.setChecked(c.save_password)
        self.type_note = QLabel()
        self.type_note.setWordWrap(True)
        self.secure = QCheckBox("Encrypted (HTTPS)")
        self.secure.setChecked(c.secure)
        self._form, self._key_row = form, key_row
        self._last_default = servers.default_port(c.protocol, c.secure)
        self.protocol.currentIndexChanged.connect(self._type_changed)
        self.secure.toggled.connect(self._type_changed)
        self.host.editingFinished.connect(self._host_typed)
        form.addRow("Name", self.name)
        form.addRow("Type", self.protocol)
        form.addRow("", self.type_note)
        form.addRow("Host", self.host)
        form.addRow("", self.secure)
        form.addRow("Port", self.port)
        form.addRow("User", self.user)
        form.addRow("Key file", key_row)
        form.addRow("Start in", self.start_dir)
        form.addRow("", self.read_only)
        form.addRow("", self.remember)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        self._type_changed()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _type_changed(self, *_args) -> None:
        kind = self.protocol.currentData()
        notes = {"scp": "Works through a shell on the server (ls, dd, mv...), so it is slower than SFTP: use it only when the server "
                        "has no SFTP service.",
                 "webdav": "A web folder: Nextcloud and ownCloud (https://host/remote.php/dav/files/you), a NAS, Apache, nginx. You can "
                           "paste the whole address into Host.",
                 "ftp": "Plain FTP sends the password and the files as readable text. Keep Encrypted (FTPS) ticked when the server "
                        "offers it. You can paste a whole address (ftp://host/folder or ftps://host/folder) into Host."}
        self.type_note.setText(notes.get(kind, ""))
        dav = kind == "webdav"
        web = kind in ("webdav", "ftp")
        self.secure.setText("Encrypted (FTPS)" if kind == "ftp" else "Encrypted (HTTPS)")
        self._form.setRowVisible(self.secure, web)
        self._form.setRowVisible(self._key_row, not web)
        if self.port.value() == self._last_default:                      # a port nobody changed follows the type
            self.port.setValue(servers.default_port(kind, self.secure.isChecked()))
        self._last_default = servers.default_port(kind, self.secure.isChecked())
        self.start_dir.setPlaceholderText("the folder on the server that is the top for this connection, for example /remote.php/dav/files/me"
                                          if dav else "empty: the folder the server opens on login")
        self.remember.setText("Keep the password in the system's password store (otherwise it is asked for when needed)")
        self.note.setText("This connection is NOT encrypted: a password and every file travel as plain text. Use it only inside a network "
                          "you trust." if web and not self.secure.isChecked() else
                          ("Nothing is contacted until you open the server. A certificate that is not from a known authority is shown to you "
                           "and asked about." if web else
                           "Nothing is contacted until you open the server. The first time, you are shown the server's key and asked whether "
                           "to trust it."))

    def _host_typed(self) -> None:
        """A whole web address in the Host box fills the other boxes."""
        parsed = servers.from_url(self.host.text())
        if parsed is None:
            return
        self.protocol.setCurrentIndex(self.protocol.findData(parsed["protocol"]))
        self.secure.setChecked(parsed["secure"])
        self.host.setText(parsed["host"])
        self.port.setValue(parsed["port"])
        if parsed["user"] and not self.user.text().strip():
            self.user.setText(parsed["user"])
        if parsed["base"] and not self.start_dir.text().strip():
            self.start_dir.setText(parsed["base"])
        if not self.name.text().strip():
            self.name.setText(parsed["host"])

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Choose a private key file", self.key_file.text())
        if path:
            self.key_file.setText(os.path.normpath(path))

    def connection(self) -> servers.Connection:
        return servers.Connection(self.name.text().strip(), self.host.text().strip(), self.user.text().strip(), int(self.port.value()),
                                  self.protocol.currentData(), self.key_file.text().strip(), self.start_dir.text().strip(),
                                  self.read_only.isChecked(), self.remember.isChecked(), self.base.id, self.secure.isChecked(),
                                  self.base.cert if (self.host.text().strip(), int(self.port.value()), self.secure.isChecked()) ==
                                  (self.base.host, self.base.port, self.base.secure) else "")

    def _accept(self) -> None:
        why = self.connection().problem()
        if why:
            self.problem.setText(f"Cannot save: {why}.")
            return
        self.accept()


class PasswordDialog(QDialog):
    def __init__(self, parent, conn: servers.Connection, message: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Log in to {conn.name}")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message or f"{conn.authority()} wants a password (or the passphrase of your key)."))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_edit)
        self.keep = QCheckBox("Keep it in the system's password store")
        self.keep.setChecked(conn.save_password)
        layout.addWidget(self.keep)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Log in", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password_edit.setFocus()

    def password(self) -> str:
        return self.password_edit.text()

    def remember(self) -> bool:
        return self.keep.isChecked()


class HostKeyDialog(QDialog):
    """A server's key, with its fingerprint, to be trusted or not. ``state`` is ``unknown`` or ``changed``."""

    def __init__(self, parent, host: str, port: int, keys: list, state: str, old: Optional[list] = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Trust this server?" if state == "unknown" else "The server's key has changed")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        shown = "\n".join(f"{k.type}   {k.fingerprint}" for k in keys[:4])
        if state == "unknown":
            text = (f"You have not connected to {host}:{port} before. Its key is:\n\n{shown}\n\nCompare the fingerprint with the one the "
                    "server's owner gives you. Trust it only if it is the same.")
        else:
            was = "\n".join(f"{k.type}   {k.fingerprint}" for k in (old or [])[:4])
            text = (f"WARNING: the key of {host}:{port} is not the one you trusted before.\n\nBefore:\n{was}\n\nNow:\n{shown}\n\n"
                    "This happens when the server was reinstalled. It also happens when somebody sits between you and the server and "
                    "reads everything, passwords included. Do not continue unless you know why it changed.")
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(label.textInteractionFlags() | label.textInteractionFlags().TextSelectableByMouse)
        layout.addWidget(label)
        buttons = QDialogButtonBox()
        self.cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.trust = buttons.addButton("Trust and connect" if state == "unknown" else "Replace the old key and connect",
                                       QDialogButtonBox.ButtonRole.AcceptRole)
        self.trust.setAutoDefault(False)
        self.cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CertificateDialog(QDialog):
    """The certificate a web server shows, with its fingerprint, to be trusted or not. ``state`` is ``unknown`` or ``changed``."""

    def __init__(self, parent, host: str, port: int, fingerprint: str, state: str, old: str = "") -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Trust this certificate?" if state == "unknown" else "The server's certificate has changed")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        nl = chr(10)
        if state == "unknown":
            text = (f"The certificate of {host}:{port} was not issued by an authority this computer knows (it may be the server's own)."
                    f"{nl}{nl}Its fingerprint:{nl}{fingerprint}{nl}{nl}Compare it with the one the server's owner gives you. Trust it only "
                    "if it is the same. From then on the connection is made only to a server that shows exactly this certificate.")
        else:
            text = (f"WARNING: the certificate of {host}:{port} is not the one you approved.{nl}{nl}Before:{nl}{old}{nl}{nl}Now:{nl}{fingerprint}"
                    f"{nl}{nl}A server that was given a new certificate looks like this. So does somebody who sits between you and the "
                    "server and reads everything, passwords included. Do not continue unless you know why it changed.")
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(label.textInteractionFlags() | label.textInteractionFlags().TextSelectableByMouse)
        layout.addWidget(label)
        buttons = QDialogButtonBox()
        self.cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.trust = buttons.addButton("Trust and connect" if state == "unknown" else "Trust the new certificate and connect",
                                       QDialogButtonBox.ButtonRole.AcceptRole)
        self.trust.setAutoDefault(False)
        self.cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ServersMixin:
    """Part of ``MainWindow``."""

    # the saved list -----------------------------------------------------------------------------------------------------------------
    def connections(self) -> list:
        return servers.from_json(self.settings.value(SETTINGS_KEY, ""))

    def _save_connections(self, items: list) -> None:
        if items:
            self.settings.setValue(SETTINGS_KEY, servers.to_json(items))
        else:
            self.settings.remove(SETTINGS_KEY)
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()

    def connection_for(self, path_or_authority: str) -> Optional[servers.Connection]:
        if "://" in path_or_authority:
            return servers.find(self.connections(), split_path(path_or_authority)[0], scheme_of(path_or_authority))
        return servers.find(self.connections(), path_or_authority)

    def server_fs(self, conn: servers.Connection):
        """The file system that holds the sessions of this kind of connection."""
        return {"scp": self.fs.scp, "webdav": self.fs.dav, "ftp": self.fs.ftp}.get(conn.protocol, self.fs.sftp)

    def server_connected(self, conn: servers.Connection) -> bool:
        return self.server_fs(conn).connected(conn.authority())

    def server_items(self) -> list:
        return [ServerItem(c.name, c.url("/"), c.describe(), self.server_connected(c)) for c in self.connections()]

    def ssh_folder(self) -> str:
        return os.path.join(os.path.dirname(self.settings.fileName()), "ssh")

    def known_hosts(self) -> sshlink.KnownHosts:
        return sshlink.KnownHosts(os.path.join(self.ssh_folder(), "known_hosts"))

    # the dialogs (seams for tests) ------------------------------------------------------------------------------------------------------
    def _ask_server(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_password(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_host_key(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_certificate(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    # adding, editing, removing ------------------------------------------------------------------------------------------------------------
    def add_server(self) -> None:
        dlg = ConnectionDialog(self)
        if not self._ask_server(dlg):
            return
        new = dlg.connection()
        items = self.connections()
        if servers.find(items, new.authority(), new.protocol) is not None:
            self.dialogs.info("Add a Server", f"{new.authority()} is already on the Home page.")
            return
        self._save_connections(items + [new])
        self._say(f"Added {new.name} to the Home page")

    def edit_server(self, conn: servers.Connection) -> None:
        dlg = ConnectionDialog(self, conn)
        if not self._ask_server(dlg):
            return
        changed = dlg.connection()
        if (changed.authority(), changed.protocol) != (conn.authority(), conn.protocol) and self.server_connected(conn):
            self.server_fs(conn).drop(conn.authority())
        if not changed.save_password:
            servers.forget_password(conn)
        self._save_connections([changed if c.id == conn.id else c for c in self.connections()])
        session = self.server_fs(changed).sessions.get(changed.authority())
        if session is not None:
            session.read_only = changed.read_only                    # the switch takes effect at once

    def remove_server(self, conn: servers.Connection) -> None:
        if not self.dialogs.confirm("Remove the Server", f"Remove {conn.name} from the Home page?\n\nThe server itself is not touched. "
                                    "Its saved password, if any, is forgotten.", "Remove"):
            return
        self.disconnect_server(conn)
        servers.forget_password(conn)
        self._save_connections([c for c in self.connections() if c.id != conn.id])
        self._say(f"Removed {conn.name} from the Home page")

    # opening and connecting ------------------------------------------------------------------------------------------------------------------
    def _home_server_action(self, path: str) -> bool:
        if path == ADD_SERVER:
            self.add_server()
            return True
        return False

    def open_server(self, path: str, new_tab: bool = False, panel=None) -> None:
        """A server of the Home page was opened: connect if need be, then show its folder."""
        if self._closing:
            return
        panel = panel or self.active
        conn = self.connection_for(path)
        if conn is None:
            self._say("This server is not in the saved list")
            return

        def go(session: Session) -> None:
            target = conn.url("/" if conn.protocol == "webdav" else (conn.start_dir or session.home))   # a web folder's base is its top
            panel.new_tab(target) if new_tab else panel.set_folder(target)
        self.connect_server(conn, go)

    def _connect_needed(self, path: str, panel) -> None:
        """A panel asked for a folder of a server that is not connected: connect, then ask again."""
        if self._closing:                                       # the window is closing and has dropped its connections on purpose
            return
        conn = self.connection_for(path)
        if conn is None:
            self._say(f"Not connected: add {split_path(path)[0]} on the Home page first")
            return
        self.connect_server(conn, lambda session: panel.set_folder(path))

    def connect_server(self, conn: servers.Connection, then: Callable[[Session], None]) -> None:
        existing = self.server_fs(conn).sessions.get(conn.authority())
        if existing is not None and existing.alive:
            existing.read_only = conn.read_only
            then(existing)
            return
        if conn.protocol in ("webdav", "ftp"):
            saved = servers.get_password(conn) if conn.save_password else ""
            self._try_dav(conn, saved, then, asked=bool(saved))
            return

        def scan(progress, cancel):
            progress(0, 0)
            keys = sshlink.scan_host_keys(conn.host, conn.port)
            kh = self.known_hosts()
            return keys, kh.check(conn.host, conn.port, keys), kh.lookup(conn.host, conn.port)

        run_in_background(self, self.cmd_runner, f"Looking for {conn.host}", scan,
                          on_result=lambda found: self._host_key_checked(conn, found, then), tracked=self._size_jobs,
                          indeterminate=True, failed_title="Connect")

    def _host_key_checked(self, conn, found, then) -> None:
        keys, state, old = found
        if state != "known":
            dlg = HostKeyDialog(self, conn.host, conn.port, keys, state, old)
            if not self._ask_host_key(dlg):
                self._say("Not connected: the server's key was not trusted")
                return
            kh = self.known_hosts()
            if state == "changed":
                kh.remove(conn.host, conn.port)
            kh.add(conn.host, conn.port, keys)
        saved = servers.get_password(conn) if conn.save_password else ""
        self._try_login(conn, saved, then, asked=bool(saved))

    def _try_login(self, conn, password: str, then, asked: bool, remember: bool = False) -> None:
        def login(progress, cancel):
            progress(0, 0)
            try:
                link = sshlink.connect(conn, password, os.path.join(self.ssh_folder(), "known_hosts"), self.ssh_folder())
            except sshlink.ConnectError as e:
                if e.kind == "auth":
                    return "auth", str(e)
                raise
            try:
                home = link.client.realpath(".")
            except OSError:
                home = "/"
            return "ok", (link, home)

        def finished(result) -> None:
            kind, payload = result
            if kind == "ok":
                link, home = payload
                self._connected(conn, link, home, password, remember, then)
                return
            if asked:                                             # a password was tried and refused: say so, offer once more
                self.dialogs.info("Connect", payload)
                if not self.dialogs.confirm("Connect", "Try another password?", "Try again"):
                    return
            dlg = PasswordDialog(self, conn, "" if not asked else f"{conn.authority()}: the login was refused. Password:")
            if not self._ask_password(dlg):
                self._say("Not connected")
                return
            self._try_login(conn, dlg.password(), then, True, dlg.remember())

        run_in_background(self, self.cmd_runner, f"Connecting to {conn.host}", login, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Connect")

    # WebDAV: no host key, but a certificate; the login is the web's -------------------------------------------------------------------------
    def _try_dav(self, conn, password: str, then, asked: bool, remember: bool = False) -> None:
        def login(progress, cancel):
            progress(0, 0)
            maker = ftpclient.FtpClient if conn.protocol == "ftp" else davclient.DavClient
            client = maker(conn.host, conn.port, conn.secure, conn.user, password, conn.cert)
            try:
                client.connect()
            except davclient.CertificateError as e:
                client.close()
                return "cert", e
            except davclient.AuthError as e:
                client.close()
                return "auth", str(e)
            except Exception:
                client.close()
                raise
            return "ok", client

        def finished(result) -> None:
            kind, payload = result
            if kind == "ok":
                self._connected_dav(conn, payload, password, remember, then)
            elif kind == "cert":
                self._certificate_asked(conn, payload, password, then, asked, remember)
            else:
                if asked and password:                              # a password was tried and refused: say so, offer once more
                    self.dialogs.info("Connect", payload)
                    if not self.dialogs.confirm("Connect", "Try another password?", "Try again"):
                        return
                note = "" if conn.secure else f" {conn.authority()} is not encrypted: the password is sent as plain text."
                message = f"{conn.authority()}: the login was refused. Password:" if (asked and password) else f"{conn.authority()}: log in.{note}"
                dlg = PasswordDialog(self, conn, message)
                if not self._ask_password(dlg):
                    self._say("Not connected")
                    return
                self._try_dav(conn, dlg.password(), then, True, dlg.remember())

        run_in_background(self, self.cmd_runner, f"Connecting to {conn.host}", login, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Connect")

    def _certificate_asked(self, conn, error, password: str, then, asked: bool, remember: bool) -> None:
        if not error.fingerprint:
            self.dialogs.info("Connect", str(error))
            return
        dlg = CertificateDialog(self, conn.host, conn.port, error.fingerprint, "changed" if error.changed else "unknown", conn.cert)
        if not self._ask_certificate(dlg):
            self._say("Not connected: the server's certificate was not trusted")
            return
        updated = servers.Connection(**{**conn.__dict__, "cert": error.fingerprint})
        self._save_connections([updated if c.id == conn.id else c for c in self.connections()])
        self._try_dav(updated, password, then, asked, remember)

    def _connected_dav(self, conn, client, password: str, remember: bool, then) -> None:
        base = "/" + conn.start_dir.strip("/") if conn.protocol == "webdav" and conn.start_dir.strip("/") else ""
        session = Session(conn.authority(), client, read_only=conn.read_only, home=getattr(client, "home", "/") if conn.protocol == "ftp" else "/",
                          base=base, scheme=conn.protocol)
        self.server_fs(conn).add_session(session)
        if password and remember and not conn.save_password:
            if servers.set_password(conn, password):
                self._save_connections([servers.Connection(**{**c.__dict__, "save_password": True}) if c.id == conn.id else c
                                        for c in self.connections()])
            else:
                self._say("The password could not be stored: this computer has no password store")
        self._say(f"Connected to {conn.name}" + (" (read-only)" if conn.read_only else ""))
        if not getattr(client, "exact_listings", True):                  # said once, in words, because the status line is soon overwritten
            self.dialogs.info("Connect", f"{conn.name} cannot give exact listings (it has no MLSD). Sizes and times are read from its text "
                                         "listing and may be wrong; names with unusual characters may not show correctly.")
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()
        then(session)

    def _connected(self, conn, link, home: str, password: str, remember: bool, then) -> None:
        session = Session(conn.authority(), link.client, read_only=conn.read_only, home=home, scheme=conn.protocol)
        self.server_fs(conn).add_session(session)
        self._links[(conn.protocol, conn.authority())] = link
        if password:
            if remember and not conn.save_password:
                if servers.set_password(conn, password):
                    self._save_connections([servers.Connection(**{**c.__dict__, "save_password": True}) if c.id == conn.id else c
                                            for c in self.connections()])
                else:
                    self._say("The password could not be stored: this computer has no password store")
        self._say(f"Connected to {conn.name}" + (" (read-only)" if conn.read_only else ""))
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()
        then(session)

    def disconnect_server(self, conn: servers.Connection) -> None:
        authority = conn.authority()
        if not self.server_connected(conn):
            return
        root = f"{conn.protocol}://{authority}"
        for panel in (self.left, self.right):                   # a panel standing in the server goes back to the Home page
            if panel.path.startswith(root + "/") or panel.path == root:
                panel.set_folder("home://")
        self.server_fs(conn).drop(authority)
        self._links.pop((conn.protocol, authority), None)
        self._say(f"Disconnected from {conn.name}")
        for panel in (self.left, self.right):
            if panel.is_home:
                panel.refresh()

    def disconnect_active_server(self) -> None:
        path = self.active.path
        conn = self.connection_for(path) if path.startswith(("sftp://", "scp://", "webdav://", "ftp://")) else None
        if conn is None:
            self._say("This panel is not on a server")
            return
        self.disconnect_server(conn)

    def disconnect_all_servers(self) -> None:
        for fs in (self.fs.sftp, self.fs.scp, self.fs.dav, self.fs.ftp):
            for authority in list(fs.sessions):
                fs.drop(authority)
        self._links.clear()
