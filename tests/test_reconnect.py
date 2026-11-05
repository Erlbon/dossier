"""Reconnect (copy plan step 1's gap, built 2026-11-05 for SFTP, SCP and FTP alike): a connection that dies mid-job is made again from the
saved login, never with a question, and a lost connection is a network error a copy waits for."""
import os

import pytest

from dossier.core import ftpclient as fc
from dossier.core import servers, sshlink
from dossier.core.ops import execute, is_network_error, plan_copy
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.sftpfs import NotConnected, Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem
from tests.ftp_server import FtpServer
from tests.test_shellclient import SH, msys, shell  # noqa: F401 -- the fixture is used by name

needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX shell on this computer")
AUTH = "me@nas.example.com"


def test_a_lost_connection_is_a_network_error_and_a_closed_one_is_not():
    assert is_network_error(ConnectionResetError("the connection to the server was lost"))
    assert not is_network_error(NotConnected(AUTH))


@needs_sh
def test_a_dead_session_is_made_again_and_keeps_its_read_only_switch(shell, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    fs = SftpFileSystem("scp")
    fs.add_session(Session(AUTH, shell, read_only=False, scheme="scp"))
    made = []

    def reconnect(authority):
        made.append(authority)
        return Session(authority, shell, read_only=True, scheme="scp")      # the switch comes from the session that died
    fs.reconnect = reconnect
    path = make_path(AUTH, shell.root.rstrip("/") + "/a.txt", "scp")
    fs.sessions[AUTH].client = _Dead()
    assert fs.stat(path).size == 1 and made == [AUTH]
    assert not fs.sessions[AUTH].read_only


@needs_sh
def test_no_saved_login_means_not_connected_and_a_network_still_away_is_waited_for(shell):
    fs = SftpFileSystem("scp")
    fs.add_session(Session(AUTH, _Dead(), read_only=False, scheme="scp"))
    path = make_path(AUTH, "/x", "scp")
    fs.reconnect = lambda authority: None
    with pytest.raises(NotConnected):
        fs.stat(path)

    def away(authority):
        raise ConnectionResetError("the network is still away")
    fs.reconnect = away
    with pytest.raises(ConnectionResetError) as e:
        fs.stat(path)
    assert is_network_error(e.value)


@needs_sh
def test_a_copy_goes_on_when_the_server_drops_half_way(shell, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(4):
        (src / f"f{i}.txt").write_text(f"file {i}")
    (tmp_path / "up").mkdir()
    sftp = SftpFileSystem("scp")
    sftp.add_session(Session(AUTH, shell, read_only=False, scheme="scp"))
    sftp.reconnect = lambda authority: Session(authority, shell, read_only=False, scheme="scp")
    router = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    router.scp = sftp
    dest = make_path(AUTH, shell.root.rstrip("/") + "/up", "scp")
    plan = plan_copy(router, [str(src / f"f{i}.txt") for i in range(4)], dest)
    from dossier.core.ops import ExecOptions
    seen = []

    def drop_after_two(op, number, count):
        seen.append(number)
        if number == 3:
            sftp.sessions[AUTH].client = _Dead()                             # the connection is gone before the third file
    result = execute(plan, router, options=ExecOptions(workers=1, on_item=drop_after_two))
    assert not result.failed and sorted(os.listdir(tmp_path / "up")) == [f"f{i}.txt" for i in range(4)]


def test_the_shared_reconnect_never_asks_and_tells_a_refused_login_from_a_network_down(monkeypatch):
    conn = servers.Connection("NAS", "nas", "me")

    def refused(*a, **k):
        raise sshlink.ConnectError("The server refused the login", kind="auth")
    monkeypatch.setattr(sshlink, "connect", refused)
    assert sshlink.reconnect_session(conn, "", "kh", "folder") is None

    def unreachable(*a, **k):
        raise sshlink.ConnectError("There is no route to the server")
    monkeypatch.setattr(sshlink, "connect", unreachable)
    with pytest.raises(ConnectionResetError):
        sshlink.reconnect_session(conn, "", "kh", "folder")


def test_ftp_logs_in_again_after_the_main_connection_was_lost(tmp_path):
    root = tmp_path / "ftp"
    root.mkdir()
    (root / "a.txt").write_text("a")
    server = FtpServer(str(root))
    try:
        c = fc.FtpClient("127.0.0.1", server.port, secure=False)
        c.connect()
        c._ftp = None                                                       # what a dropped main connection leaves behind
        assert [n.name for n in c.listdir("/")] == ["a.txt"]
    finally:
        server.stop()


class _Dead:
    """A client whose connection is gone."""
    closed = True

    def close(self):
        pass
