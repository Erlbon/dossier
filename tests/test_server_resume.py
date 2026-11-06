"""A big copy to or from an SFTP, SCP or FTP server that broke off goes on where it stopped (decided 2026-11-06, option M), as one
between local disks always did: the part file and its note stay, and the next try checks the stretch before the stopping point against
the original and continues from there. A server cannot cut a file, so an upload goes on from the part's end; a download into a local
part steps back a little, as before. Tested against real servers: OpenSSH's sftp-server, a POSIX shell (SCP) and the test FTP server."""
import os

import pytest

from dossier.core import ftpclient as fc
from dossier.core import sftp_proto as sp
from dossier.core import transfer
from dossier.core.sftpfs import Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem
from tests.ftp_server import FtpServer
from tests.sftp_server import LocalServer, find_sftp_server
from tests.test_shellclient import SH, msys

AUTH = "me@nas.example.com"
SIZE = 3 * 1024 * 1024
BACK = 64 * 1024
local = LocalFileSystem()


@pytest.fixture(autouse=True)
def small_numbers(monkeypatch):
    monkeypatch.setattr(transfer, "RESUME_MIN", 1024 * 1024)
    monkeypatch.setattr(transfer, "RESUME_BACK", BACK)
    monkeypatch.setattr(transfer, "RESUME_CHECK", 16 * 1024)


@pytest.fixture(params=["sftp", "scp", "ftp"])
def server(request, tmp_path):
    """``(file system, url of a name on the server, the local folder the server keeps its files in)``."""
    folder = tmp_path / "server"
    folder.mkdir()
    if request.param == "sftp":
        exe = find_sftp_server()
        if exe is None:
            pytest.skip("no sftp-server on this computer")
        s = LocalServer(exe, str(folder))
        client = sp.SftpClient(s.reader, s.writer, s.stop)
        stop = client.close
        base, session_base = "", s.path("").rstrip("/")
    elif request.param == "scp":
        if SH is None:
            pytest.skip("no POSIX shell on this computer")
        import subprocess
        import sys
        from dossier.core import shellclient as sc
        p = subprocess.Popen([SH], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        client = sc.ShellClient(p.stdout, p.stdin, p.kill)
        stop = client.close
        base, session_base = msys(folder), ""
    else:
        s = FtpServer(str(folder))
        client = fc.FtpClient("127.0.0.1", s.port, secure=False)
        client.connect()

        def stop():
            client.close()
            s.stop()
        base, session_base = "", ""
    fs = SftpFileSystem(request.param)
    fs.add_session(Session(AUTH, client, read_only=False, scheme=request.param, base=session_base))
    yield fs, (lambda name: make_path(AUTH, base.rstrip("/") + "/" + name, request.param)), folder
    stop()


def breaking_at(limit):
    """A progress report that cuts the connection once ``limit`` bytes are through, as a network that goes away does."""
    state = {"cut": False}

    def progress(done, total):
        if not state["cut"] and done >= limit:
            state["cut"] = True
            raise ConnectionResetError("the connection to the server was lost")
    return progress


def test_an_upload_that_broke_off_goes_on_from_the_end_of_the_part_on_the_server(server, tmp_path):
    fs, url, folder = server
    data = os.urandom(SIZE)
    (tmp_path / "big.bin").write_bytes(data)
    src, dst = str(tmp_path / "big.bin"), url("big.bin")
    with pytest.raises(OSError):
        transfer.copy_file(local, src, fs, dst, progress=breaking_at(1024 * 1024))
    left = (folder / ("big.bin" + transfer.PART_SUFFIX)).stat().st_size
    assert left >= 1024 * 1024 and (folder / ("big.bin" + transfer.PART_SUFFIX + ".json")).exists()
    seen = []
    transfer.copy_file(local, src, fs, dst, progress=lambda d, t: seen.append(d))
    assert seen[0] == left                                              # went on from the end of what the server had, not from 0
    assert (folder / "big.bin").read_bytes() == data
    assert sorted(os.listdir(folder)) == ["big.bin"]                    # no part and no note left behind


def test_a_download_that_broke_off_goes_on_from_where_the_local_part_is_sound(server, tmp_path):
    fs, url, folder = server
    data = os.urandom(SIZE)
    (folder / "big.bin").write_bytes(data)
    src, dst = url("big.bin"), str(tmp_path / "big.bin")
    with pytest.raises(OSError):
        transfer.copy_file(fs, src, local, dst, progress=breaking_at(1024 * 1024))
    left = os.path.getsize(dst + transfer.PART_SUFFIX)
    seen = []
    transfer.copy_file(fs, src, local, dst, progress=lambda d, t: seen.append(d))
    assert seen[0] == left - BACK                                       # a local part is cut back a little and checked
    assert open(dst, "rb").read() == data and not transfer.resumed_part(dst)


def test_a_part_on_the_server_that_does_not_match_any_more_is_not_trusted(server, tmp_path):
    fs, url, folder = server
    data = os.urandom(SIZE)
    (tmp_path / "big.bin").write_bytes(data)
    src, dst = str(tmp_path / "big.bin"), url("big.bin")
    with pytest.raises(OSError):
        transfer.copy_file(local, src, fs, dst, progress=breaking_at(1024 * 1024))
    part = folder / ("big.bin" + transfer.PART_SUFFIX)
    part.write_bytes(bytes(part.stat().st_size))                         # the same length, other bytes
    seen = []
    transfer.copy_file(local, src, fs, dst, progress=lambda d, t: seen.append(d))
    assert seen[0] <= 1024 * 1024 and (folder / "big.bin").read_bytes() == data     # started over: the first report is the first chunk


def test_a_cancelled_upload_leaves_nothing_on_the_server(server, tmp_path):
    from dossier.core.progress import Cancelled, CancelToken
    fs, url, folder = server
    (tmp_path / "big.bin").write_bytes(os.urandom(SIZE))
    token = CancelToken()

    def cancel_half_way(done, total):
        if done >= 1024 * 1024:
            token.cancel()
    with pytest.raises(Cancelled):
        transfer.copy_file(local, str(tmp_path / "big.bin"), fs, url("big.bin"), progress=cancel_half_way, cancel=token)
    assert os.listdir(folder) == []


def test_webdav_and_google_drive_do_not_claim_to_append():
    for scheme in ("webdav", "gdrive", "opds", "subsonic"):
        assert not SftpFileSystem(scheme).can_append(make_path(AUTH, "/x", scheme))
    assert all(SftpFileSystem(s).can_append(make_path(AUTH, "/x", s)) for s in ("sftp", "scp", "ftp"))
