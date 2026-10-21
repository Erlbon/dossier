"""WebDAV servers in the window: the dialog, the login, the certificate question and working in a web folder."""
import pytest

pytest.importorskip("PyQt6")

from dossier.core import servers  # noqa: E402
from dossier.gui import servers as gui_servers  # noqa: E402
from dossier.gui.servers import CertificateDialog, ConnectionDialog  # noqa: E402
from tests.dav_server import DavServer, make_certificate  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import label_text, lab, save, wait  # noqa: E402,F401


@pytest.fixture
def dav(lab, tmp_path):
    win, d, left, right, tmp = lab
    root = tmp_path / "webroot"
    root.mkdir()
    started = []

    def start(**kw):
        server = DavServer(str(root), **kw)
        started.append(server)
        return server
    win.dav_root, win.dav_start = root, start
    yield win, d, left, right, tmp
    for s in started:
        s.stop()


def save_dav(win, server, **kw):
    kw.setdefault("name", "Web folder")
    kw.setdefault("host", "127.0.0.1")
    kw.setdefault("secure", False)
    return save(win, protocol="webdav", port=server.port, user=kw.pop("user", ""), **kw)


def test_the_dialog_takes_a_whole_web_address_and_follows_the_secure_switch(lab):
    win, *_ = lab
    dlg = ConnectionDialog(win)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("webdav"))
    assert dlg.port.value() == 443 and not dlg._form.isRowVisible(dlg._key_row) and dlg._form.isRowVisible(dlg.secure)
    dlg.secure.setChecked(False)
    assert dlg.port.value() == 80 and "NOT encrypted" in dlg.note.text()
    dlg.secure.setChecked(True)
    dlg.host.setText("https://me@cloud.example.com:8443/remote.php/dav/files/me/")
    dlg.host.editingFinished.emit()
    c = dlg.connection()
    assert (c.protocol, c.host, c.port, c.secure, c.user, c.start_dir, c.name) == (
        "webdav", "cloud.example.com", 8443, True, "me", "/remote.php/dav/files/me", "cloud.example.com")
    assert c.authority() == "me@cloud.example.com:8443" and c.url("/x") == "webdav://me@cloud.example.com:8443/x"
    plain = servers.Connection("p", "h", port=80, protocol="webdav", secure=False)
    assert plain.authority() == "h" and "not encrypted" in plain.describe()
    assert servers.from_url("gopher://x") is None and servers.from_url("not a url") is None


def test_a_pinned_certificate_is_kept_only_while_the_address_is_the_same(lab):
    win, *_ = lab
    c = servers.Connection("w", "h.example.com", port=443, protocol="webdav", cert="SHA256:abc")
    same = ConnectionDialog(win, c)
    assert same.connection().cert == "SHA256:abc"
    same.host.setText("other.example.com")
    assert same.connection().cert == ""


def test_a_web_folder_without_a_login_opens_and_lists(dav):
    win, d, left, right, tmp = dav
    server = win.dav_start()
    (win.dav_root / "hello.txt").write_text("hi")
    c = save_dav(win, server, read_only=True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url("/") and win.left.model.row_of("hello.txt") >= 0)
    assert win.fs.dav.connected(c.authority()) and not win.fs.sftp.connected(c.authority()) and win.asked["host"] == []
    assert c.url("/").startswith("webdav://127.0.0.1:")


def test_a_login_is_asked_for_after_the_server_refuses_and_can_be_kept(dav):
    win, d, left, right, tmp = dav
    server = win.dav_start(users={"me": "pw"}, auth="basic")
    (win.dav_root / "a.txt").write_text("a")
    c = save_dav(win, server, user="me")
    win.answers["password"] = ("pw", True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.dav.connected(c.authority()))
    assert len(win.asked["password"]) == 1 and win.store[c.authority()] == "pw"
    assert "not encrypted" in label_text(win.asked["password"][0])               # plain HTTP: the owner is told the password travels openly
    win.disconnect_server(c)
    win.asked["password"].clear()
    win.open_server(c.url("/"), False, win.left)                                  # now the kept password is used without a question
    wait(win, lambda: win.fs.dav.connected(c.authority()))
    assert win.asked["password"] == []


def test_a_wrong_password_is_said_and_cancelling_leaves_nothing_connected(dav):
    win, d, left, right, tmp = dav
    server = win.dav_start(users={"me": "pw"}, auth="digest")
    c = save_dav(win, server, user="me")
    win.answers["password"] = ("wrong", False)
    d.confirm_answer = False
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: any("wrong" in t for _title, t in d.infos))
    assert not win.fs.dav.connected(c.authority()) and win.store == {}


def test_a_certificate_of_the_servers_own_is_shown_pinned_and_a_changed_one_blocks(dav, tmp_path, monkeypatch):
    win, d, left, right, tmp = dav
    made = make_certificate(tmp_path)
    if made is None:
        pytest.skip("no openssl on this computer")
    cert, key, fingerprint = made
    server = win.dav_start(certfile=cert, keyfile=key)
    (win.dav_root / "s.txt").write_text("s")
    c = save_dav(win, server, secure=True)
    asked, answer = [], {"yes": False}

    def ask(self, dlg):
        asked.append(dlg)
        return answer["yes"]
    monkeypatch.setattr(gui_servers.ServersMixin, "_ask_certificate", ask)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: asked)
    assert isinstance(asked[0], CertificateDialog) and asked[0].state == "unknown" and fingerprint in label_text(asked[0])
    assert asked[0].cancel.isDefault()
    pump(win)
    assert not win.fs.dav.connected(c.authority()) and win.connections()[0].cert == ""         # refused: nothing is remembered
    answer["yes"] = True
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.dav.connected(c.authority()))
    assert win.connections()[0].cert == fingerprint
    win.disconnect_server(c)
    asked.clear()
    win.open_server(c.url("/"), False, win.left)                                                # pinned: no question
    wait(win, lambda: win.fs.dav.connected(c.authority()))
    assert asked == []
    win.disconnect_server(c)
    win._save_connections([servers.Connection(**{**win.connections()[0].__dict__, "cert": "SHA256:" + "B" * 43})])
    answer["yes"] = False
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: asked)
    assert asked[0].state == "changed" and "WARNING" in label_text(asked[0])


def test_the_base_folder_is_the_top_of_a_web_connection_and_writes_need_the_switch(dav, monkeypatch):
    win, d, left, right, tmp = dav
    server = win.dav_start()
    (win.dav_root / "files").mkdir()
    (win.dav_root / "files" / "inside.txt").write_text("in")
    (win.dav_root / "outside.txt").write_text("out")
    c = save_dav(win, server, start_dir="/files", read_only=True)
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.right.path == c.url("/") and win.right.model.row_of("inside.txt") >= 0)
    assert win.right.model.row_of("outside.txt") < 0                              # the server's top is the base folder
    (left / "up.txt").write_text("up")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("up.txt") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("up.txt"), 0))
    win._set_active(win.left)
    win.copy()
    pump(win)
    assert not (win.dav_root / "files" / "up.txt").exists()                        # read-only: refused
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (dlg.read_only.setChecked(False), True)[1])
    win.edit_server(win.connections()[0])
    win.copy()
    wait(win, lambda: (win.dav_root / "files" / "up.txt").exists())
    assert (win.dav_root / "files" / "up.txt").read_text() == "up" and not (win.dav_root / "up.txt").exists()
