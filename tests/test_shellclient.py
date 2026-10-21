"""The ``scp`` kind of connection: files through a shell. The parser of ``ls`` is tested on lines of the usual makes, and the client against a
real POSIX shell on pipes (the one in Git for Windows, or the system's)."""
import os
import subprocess
import sys
import threading

import pytest

from dossier.core import shellclient as sc
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import execute, plan_copy, plan_delete
from dossier.core.sftp_proto import EXCL_FLAG, READ_FLAG, WRITE_FLAG, SftpError, SftpReadFile, SftpWriteFile
from dossier.core.sftpfs import Session, SftpFileSystem, make_path
from dossier.core.vfs import LocalFileSystem
from tests.sftp_server import find_sh

SH = find_sh()
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX shell on this computer")
NOW = 1_760_000_000          # 2025-10-09 08:53 UTC


# the parser ------------------------------------------------------------------------------------------------------------------------
def parse(line, offset=0):
    return sc.parse_ls_line(line, NOW, offset)


def test_a_plain_file_a_folder_and_a_link_are_read_from_ls_lines():
    name, target, a = parse("-rw-r--r--    1 root     root          1234 Jan  5  2023 notes.txt")
    assert (name, target, a.size, a.is_file) == ("notes.txt", "", 1234, True) and a.perm & 0o777 == 0o644
    name, _t, a = parse("drwxr-xr-x  2 me users 4096 Sep 30 12:00 My Documents")
    assert name == "My Documents" and a.is_dir and a.perm & 0o777 == 0o755
    name, target, a = parse("lrwxrwxrwx 1 me me 9 Oct  1 09:15 current -> releases/2")
    assert (name, target) == ("current", "releases/2") and a.is_link


def test_numeric_owners_acl_marks_and_special_bits_are_read():
    assert parse("-rw-r--r--+ 1 1000 1000 5 Jan  5  2023 a")[2].size == 5
    assert parse("-rwsr-xr-x 1 root root 5 Jan  5  2023 su")[2].perm & 0o7777 == 0o4755
    assert parse("drwxrwxrwt 1 root root 5 Jan  5  2023 tmp")[2].perm & 0o7777 == 0o1777
    assert parse("-rwxr-sr-x 1 root root 5 Jan  5  2023 x")[2].perm & 0o7777 == 0o2755


def test_devices_headers_and_noise_are_not_entries():
    for line in ("total 24", "", "crw-rw-rw- 1 root root 1, 3 Jan  5  2023 null", "srwxr-xr-x 1 me me 0 Jan  5 12:00 socket",
                 "ls: cannot access 'x': No such file or directory"):
        assert parse(line) is None


def test_the_time_comes_back_as_utc_whatever_the_servers_zone_and_a_time_without_a_year_is_never_in_the_future():
    _n, _t, a = parse("-rw-r--r-- 1 me me 1 Jan  5  2023 old")
    assert a.mtime == 1672876800                                               # 2023-01-05 00:00 UTC
    _n, _t, a = parse("-rw-r--r-- 1 me me 1 Jan  5  2023 old", offset=7200)     # the server is two hours east of UTC
    assert a.mtime == 1672876800 - 7200
    _n, _t, a = parse("-rw-r--r-- 1 me me 1 Oct  9 07:00 today")
    assert a.mtime == 1759993200                                                # 07:00 UTC on the 9th, with the time of day
    _n, _t, a = parse("-rw-r--r-- 1 me me 1 Dec 25 10:00 christmas")            # December is after "now" (October): last year's
    assert a.mtime < NOW and a.mtime > NOW - 366 * 86400


# against a real shell ---------------------------------------------------------------------------------------------------------------
def msys(path) -> str:
    text = str(path).replace(os.sep, "/")
    return "/" + text[0].lower() + text[2:] if len(text) > 2 and text[1] == ":" else text


@pytest.fixture
def shell(tmp_path):
    if SH is None:
        pytest.skip("no POSIX shell on this computer")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    p = subprocess.Popen([SH], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)

    def stop():
        for s in (p.stdin, p.stdout):
            try:
                s.close()
            except OSError:
                pass
        p.kill()
    client = sc.ShellClient(p.stdout, p.stdin, stop)
    client.root = msys(tmp_path)
    client.tmp = tmp_path
    yield client
    client.close()


@needs_sh
def test_the_shell_answers_and_marks_the_end_of_each_answer_exactly(shell):
    out, status = shell.run("printf 'no newline at the end'")
    assert out == b"no newline at the end" and status == 0
    out, status = shell.run("printf 'one\\n'; false")
    assert out == b"one\n" and status == 1
    out, status = shell.run("printf '\\000\\001\\377 binary \\n__DOSSIER_END_ not the marker'")
    assert out == b"\x00\x01\xff binary \n__DOSSIER_END_ not the marker"


@needs_sh
def test_listing_stat_mkdir_rename_and_remove(shell):
    r = shell.root
    (shell.tmp / "sub").mkdir()
    (shell.tmp / "a b.txt").write_bytes(b"12345")
    os.utime(shell.tmp / "a b.txt", (1_700_000_000, 1_700_000_000))
    names = {n.name: n.attrs for n in shell.listdir(r)}
    assert set(names) == {"sub", "a b.txt"} and names["sub"].is_dir and names["a b.txt"].size == 5
    assert abs(names["a b.txt"].mtime - 1_700_000_000) <= 2 * 86400              # an old file is shown by its day only
    assert shell.stat(r + "/a b.txt").size == 5 and shell.stat(r + "/sub").is_dir
    with pytest.raises(FileNotFoundError):
        shell.stat(r + "/missing")
    with pytest.raises(FileNotFoundError):
        shell.listdir(r + "/missing")
    shell.mkdir(r + "/new folder")
    assert (shell.tmp / "new folder").is_dir()
    with pytest.raises(OSError):
        shell.mkdir(r + "/new folder")
    shell.rename(r + "/a b.txt", r + "/c.txt")
    (shell.tmp / "d.txt").write_bytes(b"d")
    with pytest.raises(FileExistsError):
        shell.rename(r + "/c.txt", r + "/d.txt")
    shell.rename(r + "/c.txt", r + "/d.txt", overwrite=True)
    assert (shell.tmp / "d.txt").read_bytes() == b"12345" and not (shell.tmp / "c.txt").exists()
    shell.remove(r + "/d.txt")
    shell.rmdir(r + "/new folder")
    assert not (shell.tmp / "d.txt").exists() and not (shell.tmp / "new folder").exists()
    shell.set_mtime(r + "/sub", 1_600_000_000)
    assert abs(shell.stat(r + "/sub").mtime - 1_600_000_000) <= 2 * 86400
    assert shell.realpath(r).rstrip("/").endswith(shell.root.rstrip("/").rsplit("/", 1)[-1])


@needs_sh
def test_no_file_name_can_become_a_command(shell):
    r = shell.root
    for name in ("x; touch HACKED", "$(touch HACKED2)", "`touch HACKED3`", "it's", 'say "hi"', "50% & more"):
        shell.mkdir(f"{r}/{name}")
        assert shell.stat(f"{r}/{name}").is_dir
    assert sorted(p.name for p in shell.tmp.iterdir() if p.name.startswith("HACKED")) == []
    assert {n.name for n in shell.listdir(r)} >= {"x; touch HACKED", "$(touch HACKED2)", "it's"}


@needs_sh
def test_every_byte_value_goes_there_and_back_and_a_big_file_in_pieces(shell):
    r = shell.root
    data = bytes(range(256)) * 2000 + b"__DOSSIER_END_deadbeef__\n" + os.urandom(100_000)
    path = f"{r}/blob.bin"
    f = SftpWriteFile(shell, path)
    f.write(data[:100_000])
    f.write(data[100_000:])
    f.close()
    assert (shell.tmp / "blob.bin").read_bytes() == data
    g = SftpReadFile(shell, path, len(data))
    assert g.read() == data
    g.seek(70_001)
    assert g.read(5) == data[70_001:70_006]                                     # not on a block boundary
    g.seek(-7, 2)
    assert g.read() == data[-7:]
    g.close()


@needs_sh
def test_an_empty_file_an_existing_exclusive_file_and_a_missing_file(shell):
    r = shell.root
    SftpWriteFile(shell, f"{r}/empty").close()
    assert (shell.tmp / "empty").read_bytes() == b""
    assert SftpReadFile(shell, f"{r}/empty", 0).read() == b""
    with pytest.raises(OSError):
        SftpWriteFile(shell, f"{r}/empty", exclusive=True)
    with pytest.raises(FileNotFoundError):
        SftpReadFile(shell, f"{r}/nope", 0)
    shell.mkdir(f"{r}/dir")
    with pytest.raises(FileNotFoundError):
        SftpReadFile(shell, f"{r}/dir", 0)


@needs_sh
def test_two_threads_can_share_the_shell(shell):
    r = shell.root
    (shell.tmp / "f.bin").write_bytes(os.urandom(300_000))
    errors = []

    def work():
        try:
            for _ in range(4):
                assert any(n.name == "f.bin" for n in shell.listdir(r))
                f = SftpReadFile(shell, f"{r}/f.bin", 300_000)
                assert len(f.read()) == 300_000
                f.close()
        except Exception as e:   # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors


@needs_sh
def test_a_lost_shell_is_a_connection_error(shell):
    shell.close()
    with pytest.raises(ConnectionError):
        shell.stat(shell.root)


# as a file system, with the ordinary plans --------------------------------------------------------------------------------------------
@pytest.fixture
def router(shell, tmp_path):
    fs = SftpFileSystem("scp")
    fs.add_session(Session("me@old.example.com", shell, read_only=False, scheme="scp"))
    r = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    r.scp = fs
    r.root_url = make_path("me@old.example.com", shell.root, "scp")
    return r


@needs_sh
def test_scp_paths_go_to_their_own_system_and_a_server_has_no_bin(router):
    from dossier.core.drives import is_network_path
    assert router.fs_for(router.root_url) is router.scp and router.root_url.startswith("scp://me@old.example.com/")
    assert is_network_path(router.root_url)
    entries = router.list(router.root_url)
    assert all(e.path.startswith("scp://me@old.example.com/") for e in entries)


@needs_sh
def test_a_tree_goes_to_the_shell_and_back_with_the_ordinary_plans(router, tmp_path):
    src = tmp_path / "src"
    (src / "docs" / "deep").mkdir(parents=True)
    (src / "docs" / "one.txt").write_bytes(b"1" * 1000)
    (src / "docs" / "deep" / "two.bin").write_bytes(os.urandom(150_000))
    dest = router.join(router.root_url, "up")
    router.mkdir(dest)
    plan = plan_copy(router, [str(src / "docs")], dest)
    assert plan.executable
    assert not execute(plan, router, trasher=lambda p: None).failed
    assert (tmp_path / "up" / "docs" / "deep" / "two.bin").read_bytes() == (src / "docs" / "deep" / "two.bin").read_bytes()
    back = tmp_path / "back"
    back.mkdir()
    assert not execute(plan_copy(router, [router.join(dest, "docs")], str(back)), router, trasher=lambda p: None).failed
    assert (back / "docs" / "one.txt").read_bytes() == b"1" * 1000
    plan = plan_delete(router, [dest])
    assert not plan.ops[0].to_trash
    assert not execute(plan, router, trasher=lambda p: None).failed and not (tmp_path / "up").exists()
