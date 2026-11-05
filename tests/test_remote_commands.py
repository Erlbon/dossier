"""Card 34 of the functionality review of 2026-11-05: "Allow commands on this server" makes checksums and copies within one SFTP or SCP
server run there (sha256sum, cp), with fixed commands and every name quoted, falling back to the ordinary way when they cannot."""
import hashlib
import os
import time

import pytest

from dossier.core import checksums, manifest, remote_commands, servers, sshlink, transfer
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.sftpfs import Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem
from tests.test_shellclient import SH, msys, shell  # noqa: F401 -- the fixture is used by name

needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX shell on this computer")
AUTH = "me@nas.example.com"


@pytest.fixture
def server(shell, tmp_path):
    """A server reached through a shell (an SCP connection), with commands allowed: the shell is its own command channel."""
    fs = SftpFileSystem("scp")
    fs.add_session(Session(AUTH, shell, read_only=False, scheme="scp", commands=shell))
    router = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    router.scp = fs
    router.url = lambda *parts: make_path(AUTH, "/".join([shell.root.rstrip("/"), *parts]), "scp")
    return router


def spy(monkeypatch, name):
    calls = []
    real = getattr(remote_commands, name)
    monkeypatch.setattr(remote_commands, name, lambda *a: calls.append(a) or real(*a))
    return calls


@needs_sh
def test_a_checksum_is_worked_out_on_the_server(server, tmp_path, monkeypatch):
    data = os.urandom(70_000)
    (tmp_path / "a.bin").write_bytes(data)
    calls = spy(monkeypatch, "sha256")
    result = checksums.hash_file(server, server.url("a.bin"))
    assert result.digests == {"sha256": hashlib.sha256(data).hexdigest()} and result.size == len(data) and calls


@needs_sh
def test_a_copy_within_the_server_runs_there_and_keeps_the_time(server, tmp_path, monkeypatch):
    (tmp_path / "src.bin").write_bytes(b"x" * 300_000)
    when = int(time.time()) - 3600                       # recent: a shell's ls gives such a time to the minute (an old one only its day)
    os.utime(tmp_path / "src.bin", (when, when))
    calls = spy(monkeypatch, "copy")
    transfer.copy_file(server, server.url("src.bin"), server, server.url("copy.bin"))
    assert calls and (tmp_path / "copy.bin").read_bytes() == b"x" * 300_000
    assert abs(os.stat(tmp_path / "copy.bin").st_mtime - when) < 60
    assert not [p for p in os.listdir(tmp_path) if ".part" in p or "dossier" in p.lower()]      # no part file left behind


@needs_sh
def test_a_name_can_never_become_a_command(server, tmp_path):
    name = "a $(touch pwned) `touch pwned2`; touch pwned3 'q'.txt"
    (tmp_path / name).write_bytes(b"data")
    assert checksums.hash_file(server, server.url(name)).digests["sha256"] == hashlib.sha256(b"data").hexdigest()
    transfer.copy_file(server, server.url(name), server, server.url("b.txt"))
    assert (tmp_path / "b.txt").read_bytes() == b"data"
    assert not [p for p in os.listdir(tmp_path) if p.startswith("pwned")]


@needs_sh
def test_a_manifest_of_a_server_folder_is_hashed_there(server, tmp_path, monkeypatch):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "x.txt").write_bytes(b"xyz")
    calls = spy(monkeypatch, "sha256")
    items = manifest.build(server, server.url("d"))
    assert [(i.rel, i.digest) for i in items] == [("x.txt", hashlib.sha256(b"xyz").hexdigest())] and calls


@needs_sh
def test_without_the_switch_or_the_command_it_goes_the_ordinary_way(server, tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"abc")
    session = server.scp.sessions[AUTH]
    session.commands = None
    calls = spy(monkeypatch, "sha256")
    assert checksums.hash_file(server, server.url("a.txt")).digests["sha256"] == hashlib.sha256(b"abc").hexdigest() and not calls
    session.commands = session.client
    monkeypatch.setattr(remote_commands, "copy", lambda shell, a, b: False)       # cp missing or refused: the bytes go the long way
    transfer.copy_file(server, server.url("a.txt"), server, server.url("b.txt"))
    assert (tmp_path / "b.txt").read_bytes() == b"abc"


def test_the_switch_is_kept_and_only_ssh_servers_have_it():
    sftp = servers.Connection("NAS", "nas", "me", allow_commands=True)
    dav = servers.Connection("Cloud", "dav.example.com", "me", protocol="webdav", allow_commands=True)
    back = servers.from_json(servers.to_json([sftp, dav]))
    assert [c.allow_commands for c in back] == [True, False]


def test_a_shell_for_commands_is_opened_only_when_allowed(monkeypatch):
    class FakeLink:
        commands = None
    opened = []
    monkeypatch.setattr(sshlink, "connect", lambda c, *a, **k: opened.append(c.protocol) or "shell-link")
    link = FakeLink()
    sshlink.add_commands(servers.Connection("NAS", "nas", "me"), link, "", "kh", "folder")
    assert link.commands is None and opened == []
    sshlink.add_commands(servers.Connection("NAS", "nas", "me", allow_commands=True), link, "", "kh", "folder")
    assert link.commands == "shell-link" and opened == ["scp"]                     # a second ssh, with a shell instead of SFTP
    scp_link = FakeLink()
    sshlink.add_commands(servers.Connection("Old", "old", "me", protocol="scp", allow_commands=True), scp_link, "", "kh", "folder")
    assert scp_link.commands is scp_link and opened == ["scp"]                     # an SCP connection is a shell already

    def refuse(*a, **k):
        raise sshlink.ConnectError("no shell for this account")
    monkeypatch.setattr(sshlink, "connect", refuse)
    link = FakeLink()
    sshlink.add_commands(servers.Connection("NAS", "nas", "me", allow_commands=True), link, "", "kh", "folder")
    assert link.commands is None                                                   # no shell: the ordinary way, no error
