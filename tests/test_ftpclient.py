"""The FTP and FTPS client against an in-process FTP server: listings of every kind, transfers, the connection limit, TLS with a pinned
certificate, and the ordinary plans through it."""
import os

import pytest

from dossier.core import davclient as dc
from dossier.core import ftpclient as fc
from dossier.core.drives import is_network_path
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import Resolution, execute, plan_copy, plan_delete, plan_move
from dossier.core.sftp_proto import SftpError, SftpReadFile, SftpWriteFile
from dossier.core.sftpfs import Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem
from tests.dav_server import make_certificate
from tests.ftp_server import FtpServer


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "ftp"
    root.mkdir()
    made = []

    def start(**kw):
        server = FtpServer(str(root), **kw)
        server.root_path = root
        made.append(server)
        return server
    yield start
    for s in made:
        s.stop()


def client_for(server, **kw):
    kw.setdefault("secure", False)
    c = fc.FtpClient("127.0.0.1", server.port, **kw)
    c.connect()
    return c


# the parsers ---------------------------------------------------------------------------------------------------------------------------
def test_an_mlsd_time_is_utc_and_may_have_a_fraction():
    assert fc.mlsd_time("20231115120000") == 1700049600 and fc.mlsd_time("20231115120000.123") == 1700049600
    assert fc.mlsd_time("garbage") == 0


def test_facts_become_attributes_and_a_folders_own_entries_are_skipped():
    attrs, _t = fc._attrs_from_facts({"type": "file", "size": "12", "modify": "20231115120000", "unix.mode": "0640"})
    assert attrs.is_file and attrs.size == 12 and attrs.mtime == 1700049600 and attrs.perm & 0o777 == 0o640
    attrs, _t = fc._attrs_from_facts({"type": "dir", "modify": "20231115120000"})
    assert attrs.is_dir
    assert fc._attrs_from_facts({"type": "cdir"}) is None and fc._attrs_from_facts({"type": "pdir"}) is None


def test_unix_and_dos_list_lines_are_read_and_anything_else_is_not():
    now = 1_760_000_000
    name, a = fc.parse_list_line("drwxr-xr-x   2 ftp ftp        4096 Jan  5  2023 My Folder", now)
    assert name == "My Folder" and a.is_dir
    name, a = fc.parse_list_line("-rw-r--r--   1 ftp ftp        1234 Oct  9 07:00 notes.txt", now)
    assert name == "notes.txt" and a.size == 1234 and a.is_file
    name, a = fc.parse_list_line("10-20-23  02:15PM       <DIR>          Program Files", now)
    assert name == "Program Files" and a.is_dir and a.mtime == 1697811300
    name, a = fc.parse_list_line("10-20-23  02:15AM              5678 data.bin", now)
    assert name == "data.bin" and a.size == 5678 and a.is_file
    assert fc.parse_list_line("total 24", now) is None and fc.parse_list_line("", now) is None


def test_the_servers_replies_become_the_exceptions_the_program_knows():
    import ftplib
    assert isinstance(fc._error(ftplib.error_perm("550 No such file or directory"), "/x"), FileNotFoundError)
    assert isinstance(fc._error(ftplib.error_perm("550 Permission denied"), "/x"), PermissionError)
    assert isinstance(fc._error(ftplib.error_perm("530 Login incorrect"), ""), fc.LoginError)
    assert isinstance(fc._error(ftplib.error_perm("550 Directory not empty"), "/x"), OSError)
    assert isinstance(fc._error(ftplib.error_temp("421 Too many connections"), ""), ConnectionError)
    assert isinstance(fc._error(EOFError(), ""), ConnectionError)


# the file calls ------------------------------------------------------------------------------------------------------------------------
def test_connecting_learns_the_features_the_home_folder_and_a_wrong_password_is_refused(served):
    s = served(users={"me": "pw"})
    c = client_for(s, user="me", password="pw")
    assert c.exact_listings and "MLST" in c.features and "MFMT" in c.features and c.home == "/"
    for bad in (fc.FtpClient("127.0.0.1", s.port, False, "me", "wrong"), fc.FtpClient("127.0.0.1", s.port, False, "nobody", "x")):
        with pytest.raises(PermissionError):
            bad.connect()


def test_an_anonymous_login_needs_no_user(served):
    s = served()
    (s.root_path / "public.txt").write_bytes(b"p")
    c = client_for(s)
    assert [n.name for n in c.listdir("/")] == ["public.txt"] and "USER anonymous" in s.log


def test_listing_stat_mkdir_rename_remove_and_the_modified_time(served):
    s = served()
    root = s.root_path
    (root / "sub").mkdir()
    (root / "f.txt").write_bytes(b"12345")
    os.utime(root / "f.txt", (1_700_000_000, 1_700_000_000))
    c = client_for(s)
    names = {n.name: n.attrs for n in c.listdir("/")}
    assert set(names) == {"sub", "f.txt"} and names["sub"].is_dir and names["f.txt"].size == 5 and names["f.txt"].mtime == 1_700_000_000
    assert c.stat("/f.txt").size == 5 and c.stat("/sub").is_dir and c.stat("/").is_dir
    with pytest.raises(FileNotFoundError):
        c.stat("/nope")
    c.mkdir("/new")
    assert (root / "new").is_dir()
    with pytest.raises(OSError):
        c.mkdir("/new")
    (root / "d.txt").write_bytes(b"d")
    c.rename("/f.txt", "/d.txt", overwrite=True)
    assert (root / "d.txt").read_bytes() == b"12345" and not (root / "f.txt").exists()
    c.set_mtime("/d.txt", 1_600_000_000)
    assert int((root / "d.txt").stat().st_mtime) == 1_600_000_000
    c.remove("/d.txt")
    c.rmdir("/new")
    assert not (root / "d.txt").exists() and not (root / "new").exists()
    (root / "full").mkdir()
    (root / "full" / "x").write_bytes(b"x")
    with pytest.raises(OSError):
        c.rmdir("/full")


def test_a_file_goes_there_and_back_and_a_straight_read_is_one_transfer(served):
    s = served()
    c = client_for(s)
    data = os.urandom(3 * 1024 * 1024 + 17)
    f = SftpWriteFile(c, "/big.bin")
    f.write(data[:1_000_000])
    f.write(data[1_000_000:])
    f.close()
    assert (s.root_path / "big.bin").read_bytes() == data
    s.log.clear()
    g = SftpReadFile(c, "/big.bin", len(data))
    assert g.read() == data
    g.close()
    assert s.commands().count("RETR") == 1                                         # read ahead in one transfer, not a command per block
    g = SftpReadFile(c, "/big.bin", len(data))
    g.seek(2_000_001)
    assert g.read(7) == data[2_000_001:2_000_008]
    assert any(line.startswith("REST 2000001") for line in s.log)                 # a jump asks the server to start there
    g.seek(5)
    assert g.read(3) == data[5:8]
    g.seek(-5, 2)
    assert g.read() == data[-5:]
    g.close()


def test_names_with_spaces_and_unicode_survive(served):
    s = served()
    c = client_for(s)
    for name in ("a b.txt", "æøå ☃.txt", "100% real.txt"):
        f = SftpWriteFile(c, "/" + name)
        f.write(b"x")
        f.close()
        assert (s.root_path / name).read_bytes() == b"x", name
    assert {n.name for n in c.listdir("/")} == {"a b.txt", "æøå ☃.txt", "100% real.txt"}


def test_an_exclusive_write_refuses_an_existing_file(served):
    s = served()
    (s.root_path / "e.txt").write_bytes(b"e")
    c = client_for(s)
    with pytest.raises(OSError):
        SftpWriteFile(c, "/e.txt", exclusive=True)
    SftpWriteFile(c, "/fresh.txt", exclusive=True).close()
    assert (s.root_path / "fresh.txt").exists()


@pytest.mark.parametrize("dos", [False, True])
def test_a_server_without_mlsd_is_read_from_its_text_listing_and_says_so(served, dos):
    s = served(mlsd=False, dos_list=dos)
    (s.root_path / "dir").mkdir()
    (s.root_path / "one.txt").write_bytes(b"12345")
    c = client_for(s)
    assert not c.exact_listings
    names = {n.name: n.attrs for n in c.listdir("/")}
    assert set(names) == {"dir", "one.txt"} and names["dir"].is_dir and names["one.txt"].size == 5
    assert c.stat("/one.txt").size == 5 and c.stat("/dir").is_dir
    with pytest.raises(FileNotFoundError):
        c.stat("/missing")


def test_a_server_without_mfmt_just_keeps_its_own_dates(served):
    s = served(mfmt=False)
    (s.root_path / "f").write_bytes(b"f")
    c = client_for(s)
    c.set_mtime("/f", 1_600_000_000)                                               # nothing to do, nothing fails
    assert int((s.root_path / "f").stat().st_mtime) != 1_600_000_000


def test_transfers_use_connections_of_their_own_a_few_at_a_time_and_listing_goes_on_meanwhile(served):
    s = served()
    for i in range(8):
        (s.root_path / f"f{i}.bin").write_bytes(os.urandom(300_000))
    c = client_for(s)
    handle = SftpReadFile(c, "/f0.bin", 300_000)
    handle.read(1000)                                                               # a transfer is open and half read ...
    assert len(c.listdir("/")) == 8                                                # ... and the folder can be listed at the same time
    handle.close()
    import threading
    errors = []

    def copy(i):
        try:
            g = SftpReadFile(c, f"/f{i}.bin", 300_000)
            data = g.read()
            g.close()
            w = SftpWriteFile(c, f"/g{i}.bin")
            w.write(data)
            w.close()
        except Exception as e:   # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=copy, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and all((s.root_path / f"g{i}.bin").read_bytes() == (s.root_path / f"f{i}.bin").read_bytes() for i in range(8))
    assert s.peak_clients <= 1 + 2 + 2                                              # the main connection, two readers, two writers
    assert s.commands().count("USER") <= 6                                           # connections were reused, not made for every file


def test_closing_ends_every_connection_and_a_closed_client_refuses(served):
    s = served()
    c = client_for(s)
    c.close()
    with pytest.raises(ConnectionError):
        c.stat("/x")


# FTPS ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def secure(tmp_path, served):
    made = make_certificate(tmp_path)
    if made is None:
        pytest.skip("no openssl on this computer")
    cert, key, fingerprint = made
    return served(certfile=cert, keyfile=key, require_reuse=True), fingerprint


def test_an_unknown_certificate_is_refused_with_its_fingerprint_and_a_pinned_one_works_with_session_reuse(secure):
    server, fingerprint = secure
    c = fc.FtpClient("127.0.0.1", server.port, secure=True)
    with pytest.raises(dc.CertificateError) as e:
        c.connect()
    assert e.value.fingerprint == fingerprint and not e.value.changed
    ok = fc.FtpClient("127.0.0.1", server.port, secure=True, pinned=fingerprint)
    ok.connect()
    (server.root_path / "t.txt").write_bytes(b"tls")
    assert [n.name for n in ok.listdir("/")] == ["t.txt"] and ok.peer_fingerprint == fingerprint
    f = SftpWriteFile(ok, "/up.bin")
    f.write(b"u" * 100_000)
    f.close()                                                                         # the server refuses a data connection that does not resume the session
    assert (server.root_path / "up.bin").read_bytes() == b"u" * 100_000
    g = SftpReadFile(ok, "/up.bin", 100_000)
    assert g.read() == b"u" * 100_000
    g.close()


def test_a_changed_certificate_stops_the_connection(secure):
    server, fingerprint = secure
    other = fc.FtpClient("127.0.0.1", server.port, secure=True, pinned="SHA256:" + "A" * 43)
    with pytest.raises(dc.CertificateError) as e:
        other.connect()
    assert e.value.changed and e.value.fingerprint == fingerprint


# with the ordinary plans ------------------------------------------------------------------------------------------------------------------
AUTH = "me@ftp.example.com"


@pytest.fixture
def router(served):
    s = served(users={"me": "pw"})
    client = client_for(s, user="me", password="pw")
    fs = SftpFileSystem("ftp")
    fs.add_session(Session(AUTH, client, read_only=False, scheme="ftp"))
    r = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    r.ftp = fs
    r.server = s
    return r


def url(path="/"):
    return make_path(AUTH, path, "ftp")


def test_ftp_paths_belong_to_their_own_system_and_have_no_recycle_bin(router):
    assert router.fs_for(url("/a")) is router.ftp and is_network_path(url("/a"))


def test_a_tree_goes_to_the_server_and_back_and_deletes_are_permanent(router, tmp_path):
    src = tmp_path / "src"
    (src / "docs" / "deep").mkdir(parents=True)
    (src / "docs" / "one.txt").write_bytes(b"1" * 1000)
    (src / "docs" / "deep" / "two.bin").write_bytes(os.urandom(300_000))
    plan = plan_copy(router, [str(src / "docs")], url("/"))
    assert plan.executable
    assert not execute(plan, router, trasher=lambda p: None).failed
    root = router.server.root_path
    assert (root / "docs" / "deep" / "two.bin").read_bytes() == (src / "docs" / "deep" / "two.bin").read_bytes()
    back = tmp_path / "back"
    back.mkdir()
    assert not execute(plan_copy(router, [url("/docs")], str(back)), router, trasher=lambda p: None).failed
    assert (back / "docs" / "one.txt").read_bytes() == b"1" * 1000
    dplan = plan_delete(router, [url("/docs")])
    assert not dplan.ops[0].to_trash and any("no recycle bin" in w for w in dplan.warnings)
    assert not execute(dplan, router, trasher=lambda p: None).failed and not (root / "docs").exists()


def test_replacing_a_file_and_moving_to_and_from_the_server(router, tmp_path):
    root = router.server.root_path
    (root / "f.txt").write_bytes(b"old")
    local = tmp_path / "f.txt"
    local.write_bytes(b"new")
    plan = plan_copy(router, [str(local)], url("/")).resolve(Resolution.OVERWRITE, router)
    assert not execute(plan, router, trasher=lambda p: None).failed
    assert (root / "f.txt").read_bytes() == b"new" and not any(n.endswith(".dossier-old") for n in os.listdir(root))
    moving = tmp_path / "m.txt"
    moving.write_bytes(b"m")
    assert not execute(plan_move(router, [str(moving)], url("/")), router, trasher=lambda p: None).failed
    assert (root / "m.txt").read_bytes() == b"m" and not moving.exists()
    router.mkdir(url("/sub"))
    assert not execute(plan_move(router, [url("/m.txt")], url("/sub")), router, trasher=lambda p: None).failed
    assert (root / "sub" / "m.txt").read_bytes() == b"m"
