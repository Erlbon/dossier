"""SFTP servers as folders: the path rules, the file system contract against a real sftp-server, read-only connections, and the ordinary copy
and delete plans going to and from a server."""
import os
import shutil

import pytest

from dossier.core import sftp_proto as sp
from dossier.core.drives import is_network_path, is_remote_quick
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import execute, plan_copy, plan_delete, plan_move
from dossier.core.sftpfs import NotConnected, Session, SftpFileSystem, make_path, split_path
from dossier.core.vfs import LocalFileSystem, NotWritable
from tests.sftp_server import LocalServer, find_sftp_server

AUTH = "me@files.example.com:2222"
needs_server = pytest.mark.skipif(find_sftp_server() is None, reason="no sftp-server on this computer")


def url(path="/"):
    return make_path(AUTH, path)


# paths -----------------------------------------------------------------------------------------------------------------------------
def test_a_server_path_splits_into_the_server_and_the_path_on_it():
    assert split_path("sftp://me@h:2222/a/b/") == ("me@h:2222", "/a/b")
    assert split_path("sftp://me@h") == ("me@h", "/") and split_path("sftp://me@h/") == ("me@h", "/")
    assert split_path("sftp://me@h/a//b/../c") == ("me@h", "/a/c")
    assert make_path("me@h", "/x/y") == "sftp://me@h/x/y" and make_path("me@h", "x") == "sftp://me@h/x"


def test_the_path_functions_use_forward_slashes_and_the_root_of_a_server_has_no_parent():
    fs = SftpFileSystem()
    assert fs.join(url("/a"), "b", "c") == url("/a/b/c") and fs.join(url(), "x") == url("/x")
    assert fs.basename(url("/a/b.txt")) == "b.txt" and fs.basename(url()) == AUTH
    assert fs.dirname(url("/a/b.txt")) == url("/a") and fs.dirname(url("/a")) == url("/") and fs.dirname(url("/")) == url("/")
    assert fs.is_root(url()) and fs.is_root("sftp://" + AUTH) and not fs.is_root(url("/a"))
    assert fs.parent(url("/a")) == url("/") and fs.parent(url("/")) is None
    assert fs.root == "sftp://" and fs.sep == "/" and fs.case_sensitive


def test_a_server_has_no_recycle_bin_and_is_remote():
    assert is_network_path(url("/a")) and is_remote_quick(url("/a"))
    assert is_network_path("") is False and getattr(SftpFileSystem(), "is_remote", False)


def test_a_path_with_no_connection_says_so_with_the_name_of_the_server():
    fs = SftpFileSystem()
    for call in (lambda: fs.list(url()), lambda: fs.stat(url("/a")), lambda: fs.open_read(url("/a"))):
        with pytest.raises(NotConnected) as e:
            call()
        assert e.value.authority == AUTH and isinstance(e.value, ConnectionError)
    assert not fs.is_writable(url("/a")) and not fs.connected(AUTH)


# a live session --------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def remote(tmp_path):
    if find_sftp_server() is None:
        pytest.skip("no sftp-server on this computer")
    folder = tmp_path / "remote"
    folder.mkdir()
    server = LocalServer(find_sftp_server(), str(folder))
    client = sp.SftpClient(server.reader, server.writer, server.stop)
    fs = SftpFileSystem()
    session = Session(AUTH, client, read_only=False, base=server.path("").rstrip("/"))
    fs.add_session(session)
    fs.folder, fs.session = folder, session
    yield fs
    client.close()


def test_listing_and_stat_give_names_sizes_and_times_below_the_virtual_root(remote):
    (remote.folder / "sub").mkdir()
    (remote.folder / "a.txt").write_bytes(b"12345")
    os.utime(remote.folder / "a.txt", (1_700_000_000, 1_700_000_000))
    entries = {e.name: e for e in remote.list(url("/"))}
    assert set(entries) == {"sub", "a.txt"} and entries["sub"].is_dir and entries["sub"].size == 0
    assert entries["a.txt"].size == 5 and entries["a.txt"].mtime == 1_700_000_000 and entries["a.txt"].path == url("/a.txt")
    assert remote.stat(url("/a.txt")).size == 5 and remote.stat(url("/sub")).is_dir
    assert remote.stat(url("/")).is_dir and remote.stat(url("/")).path == url("/")
    with pytest.raises(FileNotFoundError):
        remote.stat(url("/nope"))
    assert remote.connected(AUTH) and remote.is_writable(url("/a.txt"))


def test_a_file_is_written_read_replaced_renamed_and_removed(remote):
    with remote.open_write(url("/f.bin")) as f:
        f.write(b"hello ")
        f.write(b"world")
    assert (remote.folder / "f.bin").read_bytes() == b"hello world"
    with remote.open_read(url("/f.bin")) as f:
        assert f.read() == b"hello world"
    with pytest.raises(OSError):
        remote.open_write(url("/f.bin"), exclusive=True)
    with remote.open_write(url("/g.bin")) as f:
        f.write(b"g")
    with pytest.raises(FileExistsError):
        remote.rename(url("/g.bin"), url("/f.bin"))
    remote.rename(url("/g.bin"), url("/f.bin"), overwrite=True)
    assert (remote.folder / "f.bin").read_bytes() == b"g" and not (remote.folder / "g.bin").exists()
    remote.set_mtime(url("/f.bin"), 1_600_000_000)
    assert remote.stat(url("/f.bin")).mtime == 1_600_000_000
    remote.remove(url("/f.bin"))
    assert not (remote.folder / "f.bin").exists()


def test_folders_are_made_with_parents_and_removed_only_when_empty(remote):
    remote.mkdir(url("/a/b/c"), parents=True)
    assert (remote.folder / "a" / "b" / "c").is_dir()
    remote.mkdir(url("/a/b/c"), parents=True, exist_ok=True)
    with pytest.raises(FileExistsError):
        remote.mkdir(url("/a"))
    remote.mkdir(url("/a"), exist_ok=True)
    with pytest.raises(OSError):
        remote.remove(url("/a"))                                                       # not empty
    remote.remove(url("/a/b/c"))
    assert not (remote.folder / "a" / "b" / "c").exists()


def test_a_read_only_connection_refuses_every_change_but_reads_freely(remote):
    (remote.folder / "x.txt").write_bytes(b"x")
    remote.session.read_only = True
    assert not remote.is_writable(url("/x.txt"))
    assert remote.open_read(url("/x.txt")).read() == b"x"
    for call in (lambda: remote.open_write(url("/y.txt")), lambda: remote.mkdir(url("/d")), lambda: remote.remove(url("/x.txt")),
                 lambda: remote.rename(url("/x.txt"), url("/z.txt")), lambda: remote.set_mtime(url("/x.txt"), 1)):
        with pytest.raises(NotWritable):
            call()
    assert (remote.folder / "x.txt").exists() and not (remote.folder / "y.txt").exists()


def test_a_dead_connection_is_not_connected_and_can_be_replaced(remote):
    remote.session.client.close()
    with pytest.raises(NotConnected):
        remote.list(url("/"))
    assert not remote.connected(AUTH)
    remote.drop(AUTH)
    assert AUTH not in remote.sessions


# the ordinary plans, through the router ---------------------------------------------------------------------------------------------
@pytest.fixture
def router(remote):
    r = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    r.sftp = remote
    return r


def bin_to(tmp_path):
    def go(path):
        shutil.move(path, str(tmp_path / ("bin_" + os.path.basename(path))))
    return go


def test_the_router_sends_sftp_paths_to_the_server_system(router):
    assert router.fs_for(url("/a")) is router.sftp and router.is_writable(url("/a"))
    assert router.join(url("/a"), "b") == url("/a/b") and router.dirname(url("/a/b")) == url("/a")


@needs_server
def test_a_folder_tree_copies_to_the_server_and_back_with_the_ordinary_plans(router, tmp_path):
    src = tmp_path / "src"
    (src / "docs" / "deep").mkdir(parents=True)
    (src / "docs" / "one.txt").write_bytes(b"1" * 1000)
    (src / "docs" / "deep" / "two.bin").write_bytes(os.urandom(200_000))
    (src / "top.txt").write_bytes(b"top")
    plan = plan_copy(router, [str(src / "docs"), str(src / "top.txt")], url("/"))
    assert plan.executable, plan.conflicts or plan.blocking
    result = execute(plan, router, trasher=bin_to(tmp_path))
    assert not result.failed
    folder = router.sftp.folder
    assert (folder / "docs" / "one.txt").read_bytes() == b"1" * 1000 and (folder / "top.txt").read_bytes() == b"top"
    assert (folder / "docs" / "deep" / "two.bin").read_bytes() == (src / "docs" / "deep" / "two.bin").read_bytes()
    back = tmp_path / "back"
    back.mkdir()
    result = execute(plan_copy(router, [url("/docs")], str(back)), router, trasher=bin_to(tmp_path))
    assert not result.failed and (back / "docs" / "deep" / "two.bin").read_bytes() == (src / "docs" / "deep" / "two.bin").read_bytes()


@needs_server
def test_a_replaced_file_on_the_server_is_overwritten_not_sent_to_a_recycle_bin(router, tmp_path):
    (router.sftp.folder / "f.txt").write_bytes(b"old")
    local = tmp_path / "f.txt"
    local.write_bytes(b"new")
    plan = plan_copy(router, [str(local)], url("/"))
    assert plan.conflicts
    plan = plan.resolve(__import__("dossier.core.ops", fromlist=["Resolution"]).Resolution.OVERWRITE, router)
    result = execute(plan, router, trasher=bin_to(tmp_path))
    assert not result.failed and (router.sftp.folder / "f.txt").read_bytes() == b"new"
    assert not any(n.startswith("bin_") for n in os.listdir(tmp_path))                  # nothing went to the (local) bin


@needs_server
def test_deleting_on_a_server_is_permanent_and_the_plan_says_so(router, tmp_path):
    (router.sftp.folder / "d" / "e").mkdir(parents=True)
    (router.sftp.folder / "d" / "e" / "x.txt").write_bytes(b"x")
    plan = plan_delete(router, [url("/d")], to_trash=True)
    assert not plan.ops[0].to_trash and any("no recycle bin" in w for w in plan.warnings)
    result = execute(plan, router, trasher=bin_to(tmp_path))
    assert not result.failed and not (router.sftp.folder / "d").exists()


@needs_server
def test_a_read_only_server_blocks_the_plans_before_anything_runs(router, tmp_path):
    router.sftp.session.read_only = True
    local = tmp_path / "up.txt"
    local.write_bytes(b"u")
    assert plan_copy(router, [str(local)], url("/")).blocking
    (router.sftp.folder / "keep.txt").write_bytes(b"k")
    assert plan_delete(router, [url("/keep.txt")]).blocking
    assert (router.sftp.folder / "keep.txt").exists()


@needs_server
def test_a_move_within_one_server_renames_and_a_move_to_the_server_copies_then_removes(router, tmp_path):
    (router.sftp.folder / "inbox").mkdir()
    (router.sftp.folder / "outbox").mkdir()
    (router.sftp.folder / "inbox" / "m.txt").write_bytes(b"m")
    result = execute(plan_move(router, [url("/inbox/m.txt")], url("/outbox")), router, trasher=bin_to(tmp_path))
    assert not result.failed and (router.sftp.folder / "outbox" / "m.txt").read_bytes() == b"m"
    local = tmp_path / "l.txt"
    local.write_bytes(b"l")
    result = execute(plan_move(router, [str(local)], url("/inbox")), router, trasher=bin_to(tmp_path))
    assert not result.failed and (router.sftp.folder / "inbox" / "l.txt").read_bytes() == b"l" and not local.exists()
