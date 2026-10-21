"""OPDS book catalogues and Subsonic music servers as folders: parsing, the tree, downloads, login, and the read-only rule."""
import hashlib

import pytest

from dossier.core import opds
from dossier.core.catalogclient import safe_name, unique_names, Node
from dossier.core.davclient import AuthError
from dossier.core.opdsclient import OpdsClient
from dossier.core.sftp_proto import SftpError
from dossier.core.sftpfs import Session, SftpFileSystem
from dossier.core.subsonicclient import SubsonicClient
from dossier.core.vfs import NotWritable
from tests import catalog_server as cs


@pytest.fixture
def server():
    srv, port = cs.start()
    yield srv, port
    srv.shutdown()


def opds_client(port, password=cs.PASSWORD, start="/opds"):
    c = OpdsClient("127.0.0.1", port, False, cs.USER, password)
    c.set_start(start)
    return c


def subsonic_client(port, password=cs.PASSWORD):
    return SubsonicClient("127.0.0.1", port, False, cs.USER, password)


def names(client, path="/"):
    return [n.name for n in client.listdir(path)]


def read_all(client, path):
    handle = client.open(path, 1)
    try:
        out, offset = b"", 0
        while True:
            block = client.read_blocks(handle, offset, 4096, path)
            if not block:
                return out
            out += block
            offset += len(block)
    finally:
        client.close_handle(handle)


# parsing ---------------------------------------------------------------------------------------------------------------------------
def test_names_are_made_from_titles_and_never_repeat():
    assert safe_name('Moby: or, the "Whale"?') == "Moby_ or, the _Whale__"
    assert safe_name("   ") == "untitled" and len(safe_name("x" * 500)) <= 120
    out = unique_names([("Same.epub", Node("file", "a")), ("Same.epub", Node("file", "b")), ("same.epub", Node("file", "c")), ("dir", Node("dir", "d"))])
    assert list(out) == ["Same.epub", "Same (2).epub", "same (3).epub", "dir"]


def test_a_feed_with_a_doctype_is_refused_and_a_page_that_is_not_a_feed_is_said_so():
    with pytest.raises(opds.FeedError):
        opds.parse_feed(b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "b">]><feed xmlns="http://www.w3.org/2005/Atom"/>')
    with pytest.raises(opds.FeedError):
        opds.parse_feed(b"<html><body>login</body></html>")
    with pytest.raises(opds.FeedError):
        opds.parse_feed(b"not xml at all <")


def test_atom_and_json_feeds_give_the_same_kind_of_entries():
    atom = opds.parse_feed(cs.feed("T", cs.nav("Shelf", "/s") + cs.book("1") + '<link rel="next" href="/n"/>'))
    assert atom.title == "T" and atom.next == "/n" and len(atom.entries) == 2
    downloads, folders = opds.classify(atom.entries[1])
    assert [d.type for d in downloads] == ["application/epub+zip"] and downloads[0].length > 0 and not folders
    downloads, folders = opds.classify(atom.entries[0])
    assert not downloads and folders[0].href == "/s"
    j = opds.parse_feed(b'{"metadata":{"title":"J"},"navigation":[{"href":"/x","title":"Nav","type":"application/opds+json"}],'
                        b'"publications":[{"metadata":{"title":{"en":"Pub"}},"links":[{"rel":"http://opds-spec.org/acquisition/open-access",'
                        b'"href":"/b.epub","type":"application/epub+zip"},{"rel":"http://opds-spec.org/image","href":"/c.jpg"}]}]}')
    assert j.title == "J" and [e.title for e in j.entries] == ["Nav", "Pub"]
    assert [d.href for d in opds.classify(j.entries[1])[0]] == ["/b.epub"]


# OPDS ------------------------------------------------------------------------------------------------------------------------------
def test_an_opds_catalogue_lists_folders_and_one_file_per_format(server):
    _srv, port = server
    c = opds_client(port)
    c.connect()
    got = names(c)
    assert got[:4] == ["New books", "Many pages", "JSON catalogue", "The Sea Wolf.epub"]       # "Elsewhere" is another computer: left out
    assert "Elsewhere" not in got and "Not for sale" not in got
    assert "The Sea Wolf.pdf" in got and "Moby_ or, the Whale.pdf" in got and "No Range.epub" in got
    assert names(c, "/New books") == ["Same Title.epub", "Same Title (2).epub"]


def test_the_pages_of_a_long_feed_are_followed(server):
    _srv, port = server
    c = opds_client(port)
    assert names(c, "/Many pages") == ["Shelf 1", "Shelf 2", "Shelf 3"]
    assert names(c, "/Many pages/Shelf 2") == ["The Sea Wolf.epub"]


def test_an_opds_2_json_catalogue_works_too(server):
    _srv, port = server
    c = opds_client(port)
    assert names(c, "/JSON catalogue") == ["New in JSON", "A JSON Book.epub"]
    assert c.stat("/JSON catalogue/A JSON Book.epub").size == 8000


def test_a_file_is_read_in_blocks_with_ranges_and_without(server):
    _srv, port = server
    c = opds_client(port)
    assert read_all(c, "/The Sea Wolf.epub") == cs.BOOKS["1"][1]
    assert c.stat("/The Sea Wolf.epub").size == len(cs.BOOKS["1"][1])
    assert read_all(c, "/No Range.epub") == b"X" * 3000                  # the size comes from a HEAD, the server ignores the range
    assert c.stat("/No Range.epub").size == 3000


def test_a_wrong_password_is_an_auth_error_and_a_wrong_address_is_not_a_catalogue(server):
    _srv, port = server
    with pytest.raises(AuthError):
        opds_client(port, password="nope").connect()
    with pytest.raises(OSError):
        opds_client(port, start="/missing").connect()


def test_nothing_in_a_catalogue_can_be_changed(server):
    _srv, port = server
    c = opds_client(port)
    for call in (lambda: c.mkdir("/x"), lambda: c.remove("/The Sea Wolf.epub"), lambda: c.rename("/a", "/b"),
                 lambda: c.open("/The Sea Wolf.epub", 2), lambda: c.set_mtime("/The Sea Wolf.epub", 1.0), lambda: c.rmdir("/New books")):
        with pytest.raises(PermissionError):
            call()
    with pytest.raises(FileNotFoundError):
        c.stat("/no such thing")


# Subsonic --------------------------------------------------------------------------------------------------------------------------
def test_the_subsonic_login_sends_a_salted_token_and_never_the_password(server):
    srv, port = server
    c = subsonic_client(port)
    c.connect()
    assert all(cs.PASSWORD not in hit for hit in srv.hits) and all("t=" in hit and "s=" in hit for hit in srv.hits if "/rest/" in hit)
    with pytest.raises(AuthError):
        subsonic_client(port, "wrong").connect()


def test_the_music_tree_is_artists_albums_tracks_and_playlists(server):
    _srv, port = server
    c = subsonic_client(port)
    c.connect()
    assert names(c) == ["Artists", "Playlists"]
    assert names(c, "/Artists") == ["The Band", "AC_DC"]                  # a slash in a name is not a folder
    assert names(c, "/Artists/The Band") == ["First Album (1999)"]
    assert names(c, "/Artists/The Band/First Album (1999)") == ["1-01 Opening.mp3", "1-02 Second Song.mp3", "2-01 Back Again.mp3"]
    assert names(c, "/Artists/AC_DC") == []
    assert names(c, "/Playlists") == ["Road _ Trip"]
    assert names(c, "/Playlists/Road _ Trip") == ["01 The Band - Second Song.mp3"]


def test_a_track_downloads_exactly_and_reports_its_size_and_date(server):
    _srv, port = server
    c = subsonic_client(port)
    album = "/Artists/The Band/First Album (1999)"
    data = cs.SONGS["s1"][4]
    assert read_all(c, album + "/1-01 Opening.mp3") == data
    attrs = c.stat(album + "/1-01 Opening.mp3")
    assert attrs.size == len(data) and attrs.mtime > 1_500_000_000 and not attrs.is_dir
    assert c.stat(album).is_dir
    assert hashlib.md5(read_all(c, "/Playlists/Road _ Trip/01 The Band - Second Song.mp3")).digest() == hashlib.md5(cs.SONGS["s2"][4]).digest()


def test_a_server_that_is_not_subsonic_is_said_so(server):
    _srv, port = server
    c = SubsonicClient("127.0.0.1", port, False, cs.USER, cs.PASSWORD)
    c.set_start("/opds")                                                  # an address that answers, but not like Subsonic
    with pytest.raises((SftpError, OSError)):
        c.connect()


# through the file system the panels use --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["opds", "subsonic"])
def test_a_catalogue_session_is_a_read_only_folder_tree_for_the_panels(server, kind, tmp_path):
    _srv, port = server
    client = opds_client(port) if kind == "opds" else subsonic_client(port)
    client.connect()
    fs = SftpFileSystem(kind)
    authority = f"{cs.USER}@127.0.0.1:{port}"
    fs.add_session(Session(authority, client, read_only=True, scheme=kind))
    root = f"{kind}://{authority}/"
    listed = {e.name: e for e in fs.list(root)}
    assert listed
    first_file = "/The Sea Wolf.epub" if kind == "opds" else "/Artists/The Band/First Album (1999)/1-01 Opening.mp3"
    path = f"{kind}://{authority}{first_file}"
    entry = fs.stat(path)
    assert not entry.is_dir and entry.size > 0 and fs.is_remote
    with fs.open_read(path) as f:
        assert f.read(10) == (cs.BOOKS["1"][1] if kind == "opds" else cs.SONGS["s1"][4])[:10]
    assert not fs.is_writable(path)
    with pytest.raises(NotWritable):
        fs.remove(path)
    with pytest.raises(NotWritable):
        fs.mkdir(root + "new")
