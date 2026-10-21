"""FTP and FTPS servers in the window: the dialog, the login, the certificate question, the warning for a server without exact listings."""
import pytest

pytest.importorskip("PyQt6")

from dossier.core import servers  # noqa: E402
from dossier.gui import servers as gui_servers  # noqa: E402
from dossier.gui.servers import CertificateDialog, ConnectionDialog  # noqa: E402
from tests.dav_server import make_certificate  # noqa: E402
from tests.ftp_server import FtpServer  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import label_text, lab, save, wait  # noqa: E402,F401


@pytest.fixture
def ftp(lab, tmp_path):
    win, d, left, right, tmp = lab
    root = tmp_path / "ftproot"
    root.mkdir()
    started = []

    def start(**kw):
        server = FtpServer(str(root), **kw)
        started.append(server)
        return server
    win.ftp_root, win.ftp_start = root, start
    yield win, d, left, right, tmp
    for s in started:
        s.stop()


def save_ftp(win, server, **kw):
    kw.setdefault("name", "Old FTP")
    kw.setdefault("host", "127.0.0.1")
    kw.setdefault("secure", False)
    return save(win, protocol="ftp", port=server.port, user=kw.pop("user", ""), **kw)


def test_the_dialog_for_ftp_has_the_encryption_switch_and_takes_ftp_addresses(lab):
    win, *_ = lab
    dlg = ConnectionDialog(win)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("ftp"))
    assert dlg.port.value() == 21 and dlg._form.isRowVisible(dlg.secure) and not dlg._form.isRowVisible(dlg._key_row)
    assert dlg.secure.text() == "Encrypted (FTPS)" and "readable text" in dlg.type_note.text()
    dlg.secure.setChecked(False)
    assert dlg.port.value() == 21 and "NOT encrypted" in dlg.note.text()
    dlg.host.setText("ftps://me@files.example.com:2121/pub/stuff/")
    dlg.host.editingFinished.emit()
    c = dlg.connection()
    assert (c.protocol, c.host, c.port, c.secure, c.user) == ("ftp", "files.example.com", 2121, True, "me")
    assert c.describe().startswith("FTPS  me@files.example.com:2121") and c.url("/x") == "ftp://me@files.example.com:2121/x"
    plain = servers.Connection("p", "h", port=21, protocol="ftp", secure=False)
    assert plain.authority() == "h" and "not encrypted" in plain.describe() and plain.describe().startswith("FTP  ")
    assert servers.from_url("ftp://x.example.com/dir")["protocol"] == "ftp" and servers.from_url("ftp://x.example.com")["secure"] is False


def test_an_anonymous_ftp_folder_opens_and_lists(ftp):
    win, d, left, right, tmp = ftp
    server = win.ftp_start()
    (win.ftp_root / "readme.txt").write_text("hi")
    c = save_ftp(win, server, read_only=True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url("/") and win.left.model.row_of("readme.txt") >= 0)
    assert win.fs.ftp.connected(c.authority()) and not win.fs.dav.connected(c.authority()) and win.asked["password"] == []


def test_a_login_is_asked_for_and_can_be_kept_and_a_wrong_one_is_said(ftp):
    win, d, left, right, tmp = ftp
    server = win.ftp_start(users={"me": "pw"})
    (win.ftp_root / "a.txt").write_text("a")
    c = save_ftp(win, server, user="me")
    win.answers["password"] = ("wrong", False)
    d.confirm_answer = False
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: any("wrong" in t.lower() or "refused" in t.lower() or "incorrect" in t.lower() for _title, t in d.infos))
    assert not win.fs.ftp.connected(c.authority())
    d.infos.clear()
    win.answers["password"] = ("pw", True)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.ftp.connected(c.authority()))
    assert win.store[c.authority()] == "pw" and "not encrypted" in label_text(win.asked["password"][-1])


def test_a_server_without_mlsd_is_connected_with_a_warning_about_its_listings(ftp):
    win, d, left, right, tmp = ftp
    server = win.ftp_start(mlsd=False)
    (win.ftp_root / "old.txt").write_text("old")
    c = save_ftp(win, server)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.model.row_of("old.txt") >= 0)
    assert any("cannot give exact listings" in t and "may be wrong" in t for _title, t in d.infos)
    assert win.fs.ftp.sessions[c.authority()].client.exact_listings is False


def test_ftps_with_a_certificate_of_its_own_is_pinned_after_the_owner_agrees(ftp, tmp_path, monkeypatch):
    win, d, left, right, tmp = ftp
    made = make_certificate(tmp_path)
    if made is None:
        pytest.skip("no openssl on this computer")
    cert, key, fingerprint = made
    server = win.ftp_start(certfile=cert, keyfile=key, require_reuse=True)
    (win.ftp_root / "s.txt").write_text("s")
    c = save_ftp(win, server, secure=True)
    asked, answer = [], {"yes": False}

    def ask(self, dlg):
        asked.append(dlg)
        return answer["yes"]
    monkeypatch.setattr(gui_servers.ServersMixin, "_ask_certificate", ask)
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: asked)
    assert isinstance(asked[0], CertificateDialog) and asked[0].state == "unknown" and fingerprint in label_text(asked[0])
    pump(win)
    assert not win.fs.ftp.connected(c.authority()) and win.connections()[0].cert == ""
    answer["yes"] = True
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.ftp.connected(c.authority()))
    assert win.connections()[0].cert == fingerprint
    wait(win, lambda: win.left.model.row_of("s.txt") >= 0)
    win.disconnect_server(c)
    asked.clear()
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.fs.ftp.connected(c.authority()))
    assert asked == []


def test_copying_to_an_ftp_server_needs_the_read_only_switch_off(ftp, monkeypatch):
    win, d, left, right, tmp = ftp
    server = win.ftp_start()
    c = save_ftp(win, server, read_only=True)
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.right.path == c.url("/"))
    (left / "up.txt").write_text("up")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("up.txt") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("up.txt"), 0))
    win._set_active(win.left)
    win.copy()
    pump(win)
    assert not (win.ftp_root / "up.txt").exists()
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (dlg.read_only.setChecked(False), True)[1])
    win.edit_server(win.connections()[0])
    win.copy()
    def content():                                                                  # the server may still hold the file open for a moment
        try:
            return (win.ftp_root / "up.txt").read_text()
        except OSError:
            return None
    wait(win, lambda: content() == "up")
