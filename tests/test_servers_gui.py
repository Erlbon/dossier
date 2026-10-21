"""Servers in the window: the saved list on the Home page, the connect flow (host key, login, password), and working in a server's folders."""
import os

import pytest

pytest.importorskip("PyQt6")

from dossier.core import servers, sshlink  # noqa: E402
from dossier.core.sshlink import HostKey  # noqa: E402
from PyQt6.QtWidgets import QLabel  # noqa: E402

from dossier.gui.servers import ConnectionDialog, HostKeyDialog, PasswordDialog  # noqa: E402
from tests.sftp_server import find_sftp_server, find_sh, make_fake_ssh  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

KEY = HostKey("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl")
OTHER = HostKey("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIOtherKeyOtherKeyOtherKeyOtherKey12345678")
needs_server = pytest.mark.skipif(find_sftp_server() is None, reason="no sftp-server on this computer")


def msys(path) -> str:
    """A Windows path the Git build of sftp-server understands: ``/c/Users/...``."""
    text = str(path).replace(os.sep, "/")
    return "/" + text[0].lower() + text[2:] if len(text) > 2 and text[1] == ":" else text


@pytest.fixture
def lab(world, monkeypatch, tmp_path):
    """The window with a fake ssh serving a real sftp-server, a fixed host key, an in-memory password store and the dialogs answered."""
    win, d, left, right, tmp = world
    make_fake_ssh(tmp_path, monkeypatch, "serve")
    monkeypatch.setattr(sshlink, "scan_host_keys", lambda host, port=22, timeout=10: [KEY])
    store = {}
    monkeypatch.setattr(servers, "get_password", lambda c: store.get(c.authority(), ""))
    monkeypatch.setattr(servers, "set_password", lambda c, pw: store.__setitem__(c.authority(), pw) or True)
    monkeypatch.setattr(servers, "forget_password", lambda c: store.pop(c.authority(), None))
    win.store = store
    win.asked = {"host": [], "password": []}
    win.answers = {"host": True, "password": ("pw", False)}

    def ask_host(self, dlg):
        win.asked["host"].append(dlg)
        return win.answers["host"]

    def ask_password(self, dlg):
        win.asked["password"].append(dlg)
        answer = win.answers["password"]
        if answer is None:
            return False
        dlg.password_edit.setText(answer[0])
        dlg.keep.setChecked(answer[1])
        return True
    monkeypatch.setattr(type(win), "_ask_host_key", ask_host)
    monkeypatch.setattr(type(win), "_ask_password", ask_password)
    return win, d, left, right, tmp


def label_text(dlg) -> str:
    return " ".join(label.text() for label in dlg.findChildren(QLabel))


def home_row(win, panel, name):
    return next((r for r in range(panel.model.entry_count()) if panel.model.entry_at(r).name == name), -1)


def save(win, **kw):
    c = servers.Connection(kw.pop("name", "The NAS"), kw.pop("host", "nas.example.com"), kw.pop("user", "me"), **kw)
    win._save_connections(win.connections() + [c])
    return c


def wait(win, until, timeout=10.0):
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


# the saved list ----------------------------------------------------------------------------------------------------------------------
def test_adding_a_server_saves_it_and_shows_it_on_the_home_page_without_contacting_it(lab, monkeypatch):
    win, d, left, right, tmp = lab
    dlg_seen = []

    def answer(self, dlg):
        dlg_seen.append(dlg)
        dlg.name.setText("The NAS")
        dlg.host.setText("nas.example.com")
        dlg.user.setText("me")
        return True
    monkeypatch.setattr(type(win), "_ask_server", answer)
    win.add_server()
    assert [c.name for c in win.connections()] == ["The NAS"] and win.connections()[0].read_only is True
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    names = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    assert "Servers" in names and "The NAS" in names and "Add a server..." in names
    entry = win.left.model.entry_at(home_row(win, win.left, "The NAS"))
    assert entry.kind == "server" and entry.status == "unchecked" and entry.path == "sftp://me@nas.example.com/"
    win.add_server()                                                             # the same server again
    assert any("already on the Home page" in t for _title, t in d.infos) and len(win.connections()) == 1


def test_the_connection_dialog_checks_its_fields_and_keeps_the_choices(lab):
    win, *_ = lab
    dlg = ConnectionDialog(win)
    dlg._accept()
    assert "give the connection a name" in dlg.problem.text() and dlg.result() == 0
    dlg.name.setText("N")
    dlg.host.setText("bad host")
    dlg._accept()
    assert "host is a name" in dlg.problem.text()
    dlg.host.setText("nas")
    dlg.port.setValue(2222)
    dlg.user.setText("me")
    dlg.read_only.setChecked(False)
    dlg.remember.setChecked(True)
    c = dlg.connection()
    assert (c.host, c.port, c.user, c.read_only, c.save_password) == ("nas", 2222, "me", False, True) and c.authority() == "me@nas:2222"
    edit = ConnectionDialog(win, c)
    assert edit.host.text() == "nas" and edit.port.value() == 2222 and edit.connection().id == c.id


def test_editing_and_removing_a_server_forget_what_must_be_forgotten(lab, monkeypatch):
    win, d, left, right, tmp = lab
    c = save(win, save_password=True)
    win.store[c.authority()] = "secret"
    monkeypatch.setattr(type(win), "disconnect_server", lambda self, conn: None)
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (dlg.remember.setChecked(False), True)[1])
    win.edit_server(c)
    assert win.connections()[0].save_password is False and c.authority() not in win.store
    win.store[c.authority()] = "again"
    d.confirm_answer = False
    win.remove_server(c)
    assert len(win.connections()) == 1
    d.confirm_answer = True
    win.remove_server(c)
    assert win.connections() == [] and c.authority() not in win.store


# connecting ------------------------------------------------------------------------------------------------------------------------
@needs_server
def test_a_first_connection_asks_about_the_key_remembers_it_and_opens_the_servers_folder(lab, tmp_path):
    win, d, left, right, tmp = lab
    folder = tmp_path / "serverfiles"
    folder.mkdir()
    (folder / "hello.txt").write_text("hi")
    c = save(win, start_dir=msys(folder), read_only=True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url(msys(folder)) and win.left.model.row_of("hello.txt") >= 0)
    assert len(win.asked["host"]) == 1 and win.asked["host"][0].state == "unknown" and KEY.fingerprint in label_text(win.asked["host"][0])
    assert win.known_hosts().check("nas.example.com", 22, [KEY]) == "known"
    assert win.fs.sftp.connected(c.authority()) and "Connected to The NAS" in win.status.text()
    assert win.asked["password"] == []                                         # the keys were enough: no password was asked


@needs_server
def test_a_known_key_is_not_asked_about_again_and_a_changed_key_blocks_until_replaced(lab, tmp_path):
    win, d, left, right, tmp = lab
    folder = tmp_path / "files"
    folder.mkdir()
    c = save(win, start_dir=msys(folder))
    win.known_hosts().add("nas.example.com", 22, [OTHER])                        # a different key was approved before
    win.answers["host"] = False
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.asked["host"])
    assert win.asked["host"][0].state == "changed" and win.asked["host"][0].cancel.isDefault()
    pump(win)
    assert not win.fs.sftp.connected(c.authority()) and win.known_hosts().check("nas.example.com", 22, [OTHER]) == "known"
    win.answers["host"] = True                                                   # now the owner agrees the server was reinstalled
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.sftp.connected(c.authority()))
    assert win.known_hosts().check("nas.example.com", 22, [KEY]) == "known" and win.known_hosts().check("nas.example.com", 22, [OTHER]) == "changed"
    win.disconnect_server(c)
    win.asked["host"].clear()
    win.open_server(c.url("/"), False, win.left)                                 # known now: no question
    wait(win, lambda: win.fs.sftp.connected(c.authority()))
    assert win.asked["host"] == []


@needs_server
def test_a_refused_login_asks_for_a_password_and_can_keep_it(lab, tmp_path, monkeypatch):
    win, d, left, right, tmp = lab
    make_fake_ssh(tmp_path, monkeypatch, "needs_password")
    folder = tmp_path / "pwfiles"
    folder.mkdir()
    c = save(win, start_dir=msys(folder))
    win.answers["password"] = ("pw", True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.sftp.connected(c.authority()))
    assert len(win.asked["password"]) == 1
    assert win.store[c.authority()] == "pw" and win.connections()[0].save_password is True


@needs_server
def test_a_wrong_password_says_so_and_cancelling_leaves_nothing_connected(lab, tmp_path, monkeypatch):
    win, d, left, right, tmp = lab
    make_fake_ssh(tmp_path, monkeypatch, "needs_password")
    c = save(win)
    win.answers["password"] = ("wrong", False)
    d.confirm_answer = False
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: any("refused the login" in t for _title, t in d.infos))
    assert not win.fs.sftp.connected(c.authority()) and win.store == {}
    win.answers["password"] = None
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: "Not connected" in win.status.text())


@needs_server
def test_a_saved_password_is_used_without_asking(lab, tmp_path, monkeypatch):
    win, d, left, right, tmp = lab
    make_fake_ssh(tmp_path, monkeypatch, "needs_password")
    folder = tmp_path / "saved"
    folder.mkdir()
    c = save(win, start_dir=msys(folder), save_password=True)
    win.store[c.authority()] = "pw"
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.sftp.connected(c.authority()))
    assert win.asked["password"] == []


@needs_server
def test_typing_the_address_of_a_saved_server_that_is_not_connected_connects_first(lab, tmp_path):
    win, d, left, right, tmp = lab
    folder = tmp_path / "typed"
    folder.mkdir()
    (folder / "x.txt").write_text("x")
    c = save(win)
    win.right.set_folder(c.url(msys(folder)))
    wait(win, lambda: win.right.path == c.url(msys(folder)) and win.right.model.row_of("x.txt") >= 0)
    unknown = "sftp://me@elsewhere.example.com/x"
    win.right.set_folder(unknown)
    pump(win)
    assert "add me@elsewhere.example.com on the Home page first" in win.status.text()


# working in a server's folders -------------------------------------------------------------------------------------------------------
@needs_server
def test_copying_to_a_read_write_server_and_the_read_only_switch(lab, tmp_path, monkeypatch):
    win, d, left, right, tmp = lab
    folder = tmp_path / "up"
    folder.mkdir()
    c = save(win, start_dir=msys(folder), read_only=True)
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.right.path == c.url(msys(folder)))
    (left / "a.txt").write_text("alpha")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.txt") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win._set_active(win.left)
    win.copy()
    pump(win)
    assert not (folder / "a.txt").exists()                                       # read-only: refused, nothing copied
    assert any("read-only" in t.lower() or "cannot be written" in t.lower() or "read only" in t.lower() for _title, t in d.infos)
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (dlg.read_only.setChecked(False), True)[1])
    win.edit_server(win.connections()[0])
    win.copy()
    wait(win, lambda: (folder / "a.txt").exists())
    assert (folder / "a.txt").read_text() == "alpha"


@needs_server
def test_the_context_menu_of_a_server_and_disconnecting_returns_the_panel_to_the_home_page(lab, tmp_path):
    win, d, left, right, tmp = lab
    folder = tmp_path / "ctx"
    folder.mkdir()
    c = save(win, start_dir=msys(folder))
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    row = home_row(win, win.left, "The NAS")
    texts = lambda: [a.text() for a in win.build_context_menu(win.left, row).actions() if not a.isSeparator()]       # noqa: E731
    assert texts()[0] == "Connect" and "Edit..." in texts() and "Remove from the Home Page" in texts()
    disconnect = next(a for a in win.build_context_menu(win.left, row).actions() if a.text() == "Disconnect")
    assert not disconnect.isEnabled()
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.fs.sftp.connected(c.authority()) and win.right.path.startswith("sftp://"))
    assert texts()[0] == "Open" and next(a for a in win.build_context_menu(win.left, row).actions() if a.text() == "Disconnect").isEnabled()
    win.disconnect_active_server() if win.active.path.startswith("sftp://") else win.disconnect_server(c)
    wait(win, lambda: not win.fs.sftp.connected(c.authority()) and win.right.is_home)
    win.disconnect_active_server()
    assert "not on a server" in win.status.text()


def test_the_dialogs_for_a_password_and_a_host_key_are_safe_by_default(lab):
    win, *_ = lab
    c = servers.Connection("N", "h", "me")
    p = PasswordDialog(win, c)
    assert p.password_edit.echoMode().name == "Password" and not p.remember()
    unknown = HostKeyDialog(win, "h", 22, [KEY], "unknown")
    assert unknown.cancel.isDefault() and KEY.fingerprint in label_text(unknown)
    changed = HostKeyDialog(win, "h", 22, [KEY], "changed", [OTHER])
    text = label_text(changed)
    assert "WARNING" in text and OTHER.fingerprint in text and KEY.fingerprint in text and changed.cancel.isDefault()
    assert "Replace the old key" in changed.trust.text()


def test_closing_ends_every_session(lab):
    win, d, left, right, tmp = lab
    from dossier.core.sftp_proto import SftpClient
    from dossier.core.sftpfs import Session
    closed = []

    class Pipe:
        def read(self, n):
            return b""

        def write(self, d):
            pass

        def flush(self):
            pass
    client = SftpClient.__new__(SftpClient)
    client.closed = False
    client.close = lambda: closed.append(True) or setattr(client, "closed", True)
    win.fs.sftp.add_session(Session("me@x", client))
    win.disconnect_all_servers()
    assert closed == [True] and not win.fs.sftp.sessions


@pytest.mark.skipif(find_sh() is None, reason="no POSIX shell on this computer")
def test_a_server_of_the_scp_kind_connects_through_a_shell_and_its_folders_are_listed(lab, tmp_path, monkeypatch):
    win, d, left, right, tmp = lab
    make_fake_ssh(tmp_path, monkeypatch, "shell")
    folder = tmp_path / "boxfiles"
    folder.mkdir()
    (folder / "readme.txt").write_text("hi")
    c = save(win, name="Old box", host="old.example.com", user="root", protocol="scp", start_dir=msys(folder), read_only=False)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url(msys(folder)) and win.left.model.row_of("readme.txt") >= 0)
    assert c.url("/").startswith("scp://") and win.fs.scp.connected(c.authority()) and not win.fs.sftp.connected(c.authority())
    assert win.server_connected(c) and "Connected to Old box" in win.status.text()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("readme.txt"), 0))
    win.copy()                                                                   # to the other panel (a local folder)
    pump(win)
    wait(win, lambda: (right / "readme.txt").exists())
    assert (right / "readme.txt").read_text() == "hi"
    win.disconnect_server(c)
    assert not win.server_connected(c)
