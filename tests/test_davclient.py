"""The WebDAV client against an in-process server: the protocol, the logins, the certificate pinning, and the ordinary plans through it."""
import os
import shutil

import pytest

from dossier.core import davclient as dc
from dossier.core.drives import is_network_path
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import Resolution, execute, plan_copy, plan_delete, plan_move
from dossier.core.sftp_proto import SftpError, SftpReadFile, SftpWriteFile
from dossier.core.sftpfs import Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem, NotWritable
from tests.dav_server import DavServer, make_certificate


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "dav"
    root.mkdir()
    made = []

    def start(**kw):
        server = DavServer(str(root), **kw)
        made.append(server)
        server.root_path = root
        return server
    yield start
    for s in made:
        s.stop()


def client_for(server, **kw):
    kw.setdefault("secure", False)
    c = dc.DavClient("127.0.0.1", server.port, **kw)
    return c


# the pieces -----------------------------------------------------------------------------------------------------------------------------
def test_the_digest_formula_matches_the_example_of_the_rfc():
    challenge = {"realm": "testrealm@host.com", "nonce": "dcd98b7102dd2f0e8b11d0f600bfb0c093", "qop": "auth", "opaque": "5ccc069c403ebaf9f0171e9517f40e41"}
    header = dc.digest_response("Mufasa", "Circle Of Life", "GET", "/dir/index.html", challenge, 1, "0a4f113b")
    assert 'response="6629fae49393a05397450978507c4ef1"' in header and "qop=auth" in header and "nc=00000001" in header


def test_a_challenge_is_taken_apart():
    c = dc.parse_challenge('Digest realm="a b", nonce="xyz", qop="auth,auth-int", algorithm=SHA-256, stale=true')
    assert c["scheme"] == "digest" and c["realm"] == "a b" and c["nonce"] == "xyz" and c["algorithm"] == "SHA-256" and c["stale"] == "true"
    assert dc.parse_challenge('Basic realm="x"')["scheme"] == "basic"


def test_a_multistatus_is_read_with_names_sizes_times_and_folders():
    xml = b"""<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">
      <D:response><D:href>/files/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
      <D:response><D:href>http://host:8080/files/a%20b%C3%A6.txt</D:href><D:propstat><D:prop><D:resourcetype/><D:getcontentlength>12</D:getcontentlength>
        <D:getlastmodified>Wed, 15 Nov 2023 12:00:00 GMT</D:getlastmodified></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
      <D:response><D:href>/files/sub/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
      <D:response><D:href>/files/odd</D:href><D:propstat><D:prop><D:getcontentlength>5</D:getcontentlength></D:prop><D:status>HTTP/1.1 404 Not Found</D:status></D:propstat></D:response>
    </D:multistatus>"""
    rows = dict(dc._parse_multistatus(xml))
    assert set(rows) == {"/files", "/files/a bæ.txt", "/files/sub", "/files/odd"}
    f = rows["/files/a bæ.txt"]
    assert f.size == 12 and f.is_file and f.mtime == 1700049600
    assert rows["/files/sub"].is_dir and rows["/files"].is_dir and rows["/files/odd"].size == 0       # a 404 property is not believed


def test_a_reply_with_a_document_type_or_broken_xml_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><x>&b;</x>'
    with pytest.raises(SftpError):
        dc._parse_multistatus(bomb)
    with pytest.raises(SftpError):
        dc._parse_multistatus(b"<not closed")


# against the server ------------------------------------------------------------------------------------------------------------------------
def test_listing_stat_mkdir_rename_and_remove(served):
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
    with pytest.raises(FileNotFoundError):
        c.listdir("/nope")
    c.mkdir("/new")
    assert (root / "new").is_dir()
    with pytest.raises(FileExistsError):
        c.mkdir("/new")
    with pytest.raises(FileNotFoundError):
        c.mkdir("/missing/inner")
    (root / "d.txt").write_bytes(b"d")
    with pytest.raises(FileExistsError):
        c.rename("/f.txt", "/d.txt")
    c.rename("/f.txt", "/d.txt", overwrite=True)
    assert (root / "d.txt").read_bytes() == b"12345" and not (root / "f.txt").exists()
    c.remove("/d.txt")
    c.rmdir("/new")
    assert not (root / "d.txt").exists() and not (root / "new").exists()
    c.set_mtime("/sub", 1)                                                      # does nothing, and does not fail


def test_a_folder_that_is_not_empty_is_never_deleted_in_one_go(served):
    s = served()
    (s.root_path / "full").mkdir()
    (s.root_path / "full" / "x.txt").write_bytes(b"x")
    c = client_for(s)
    with pytest.raises(OSError):
        c.rmdir("/full")
    assert (s.root_path / "full" / "x.txt").exists()                            # the server would have deleted everything in it


def test_a_file_goes_there_and_back_with_ranges_and_a_big_one_in_blocks(served):
    s = served()
    c = client_for(s)
    data = os.urandom(3 * 1024 * 1024 + 17)
    f = SftpWriteFile(c, "/big.bin")
    f.write(data[:1_000_000])
    f.write(data[1_000_000:])
    f.close()
    assert (s.root_path / "big.bin").read_bytes() == data
    g = SftpReadFile(c, "/big.bin", len(data))
    assert g.read() == data
    g.seek(2_000_001)
    assert g.read(7) == data[2_000_001:2_000_008]
    g.seek(-5, 2)
    assert g.read() == data[-5:]
    g.close()
    assert any(h.get("Range") for m, p, h in s.log if m == "GET")


def test_a_server_that_ignores_ranges_still_gives_the_right_bytes(served):
    s = served(ranges=False)
    (s.root_path / "r.bin").write_bytes(bytes(range(200)))
    c = client_for(s)
    g = SftpReadFile(c, "/r.bin", 200)
    g.seek(50)
    assert g.read(10) == bytes(range(50, 60))
    g.close()


def test_names_with_spaces_unicode_and_url_characters_survive(served):
    s = served()
    c = client_for(s)
    for name in ("a b.txt", "æøå ☃.txt", "100% real.txt", "q#y&z+w=v;x,y.txt", "it's (1).txt"):
        f = SftpWriteFile(c, "/" + name)
        f.write(b"x")
        f.close()
        assert (s.root_path / name).read_bytes() == b"x", name
    assert {n.name for n in c.listdir("/")} == {"a b.txt", "æøå ☃.txt", "100% real.txt", "q#y&z+w=v;x,y.txt", "it's (1).txt"}
    assert c.stat("/100% real.txt").size == 1


def test_an_exclusive_write_refuses_an_existing_file(served):
    s = served()
    (s.root_path / "e.txt").write_bytes(b"e")
    c = client_for(s)
    with pytest.raises(OSError):
        SftpWriteFile(c, "/e.txt", exclusive=True)
    SftpWriteFile(c, "/fresh.txt", exclusive=True).close()
    assert (s.root_path / "fresh.txt").exists()


def test_a_folder_asked_for_without_its_slash_and_hrefs_with_the_host_in_them_are_handled(served):
    s = served(redirect_dirs=True, absolute_hrefs=True)
    (s.root_path / "dir").mkdir()
    (s.root_path / "dir" / "in.txt").write_bytes(b"in")
    c = client_for(s)
    assert c.stat("/dir").is_dir
    assert [n.name for n in c.listdir("/dir")] == ["in.txt"]


def test_the_connection_is_kept_and_a_dropped_one_is_made_again(served):
    s = served()
    c = client_for(s)
    c.stat("/")
    first = c._conn
    c.stat("/")
    assert c._conn is first and len(s.log) == 2
    c._conn.sock.close()                                                         # the server (or a firewall) dropped it
    assert c.stat("/").is_dir
    c.close()
    with pytest.raises(ConnectionError):
        c.stat("/")


# logins ------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("scheme", ["basic", "digest"])
def test_a_login_is_made_when_the_server_asks_and_a_wrong_password_is_refused(served, scheme):
    s = served(users={"me": "secret"}, auth=scheme)
    (s.root_path / "x.txt").write_bytes(b"x")
    good = client_for(s, user="me", password="secret")
    assert [n.name for n in good.listdir("/")] == ["x.txt"]
    good.stat("/x.txt")                                                          # the second request is sent with the login at once
    assert all("Authorization" in h for m, p, h in s.log[2:])
    for bad in (client_for(s, user="me", password="wrong"), client_for(s)):
        with pytest.raises(PermissionError):
            bad.stat("/")


def test_the_password_is_sent_only_in_an_authorization_header(served):
    s = served(users={"me": "s3cr3t-pw"}, auth="basic")
    client_for(s, user="me", password="s3cr3t-pw").stat("/")
    assert all("s3cr3t-pw" not in p for _m, p, _h in s.log)


# certificates --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def secure(tmp_path, served):
    made = make_certificate(tmp_path)
    if made is None:
        pytest.skip("no openssl on this computer")
    cert, key, fingerprint = made
    server = served(certfile=cert, keyfile=key)
    return server, fingerprint


def test_an_unknown_certificate_is_refused_with_its_fingerprint_and_a_pinned_one_is_accepted(secure):
    server, fingerprint = secure
    c = dc.DavClient("127.0.0.1", server.port, secure=True)
    with pytest.raises(dc.CertificateError) as e:
        c.stat("/")
    assert e.value.fingerprint == fingerprint and not e.value.changed
    pinned = dc.DavClient("127.0.0.1", server.port, secure=True, pinned=fingerprint)
    assert pinned.stat("/").is_dir and pinned.peer_fingerprint == fingerprint
    assert dc.fetch_fingerprint("127.0.0.1", server.port) == fingerprint


def test_a_changed_certificate_stops_the_connection(secure):
    server, fingerprint = secure
    other = dc.DavClient("127.0.0.1", server.port, secure=True, pinned="SHA256:" + "A" * 43)
    with pytest.raises(dc.CertificateError) as e:
        other.stat("/")
    assert e.value.changed and e.value.fingerprint == fingerprint


# as a file system with the ordinary plans -------------------------------------------------------------------------------------------------------
AUTH = "me@files.example.com"


@pytest.fixture
def router(served):
    s = served()
    client = client_for(s)
    fs = SftpFileSystem("webdav")
    fs.add_session(Session(AUTH, client, read_only=False, scheme="webdav"))
    r = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    r.dav = fs
    r.server = s
    return r


def url(path="/"):
    return make_path(AUTH, path, "webdav")


def test_webdav_paths_belong_to_their_own_system_and_have_no_recycle_bin(router):
    assert router.fs_for(url("/a")) is router.dav and is_network_path(url("/a"))
    assert router.join(url("/a"), "b") == url("/a/b") and router.dirname(url("/a/b")) == url("/a")


def test_a_tree_goes_to_the_server_and_back_with_the_ordinary_plans_and_deletes_are_permanent(router, tmp_path):
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


def test_replacing_a_file_and_moving_between_here_and_the_server(router, tmp_path):
    root = router.server.root_path
    (root / "f.txt").write_bytes(b"old")
    local = tmp_path / "f.txt"
    local.write_bytes(b"new")
    plan = plan_copy(router, [str(local)], url("/")).resolve(Resolution.OVERWRITE, router)
    assert not execute(plan, router, trasher=lambda p: shutil.move(p, str(tmp_path / "bin"))).failed
    assert (root / "f.txt").read_bytes() == b"new" and not (tmp_path / "bin").exists()
    moving = tmp_path / "m.txt"
    moving.write_bytes(b"m")
    assert not execute(plan_move(router, [str(moving)], url("/")), router, trasher=lambda p: None).failed
    assert (root / "m.txt").read_bytes() == b"m" and not moving.exists()
    router.mkdir(url("/sub"))
    assert not execute(plan_move(router, [url("/m.txt")], url("/sub")), router, trasher=lambda p: None).failed
    assert (root / "sub" / "m.txt").read_bytes() == b"m" and not (root / "m.txt").exists()


def test_a_read_only_session_blocks_changes_before_they_start(router, tmp_path):
    router.dav.sessions[AUTH].read_only = True
    local = tmp_path / "u.txt"
    local.write_bytes(b"u")
    assert plan_copy(router, [str(local)], url("/")).blocking
    with pytest.raises(NotWritable):
        router.dav.open_write(url("/x"))
