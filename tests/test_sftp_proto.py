"""The SFTP client against a real server (OpenSSH's sftp-server over pipes): the whole file protocol the program uses."""
import hashlib
import os

import pytest

from dossier.core import sftp_proto as sp
from tests.sftp_server import LocalServer, find_sftp_server

EXE = find_sftp_server()
pytestmark = pytest.mark.skipif(EXE is None, reason="no sftp-server on this computer")


@pytest.fixture
def server(tmp_path):
    s = LocalServer(EXE, str(tmp_path))
    client = sp.SftpClient(s.reader, s.writer, s.stop)
    s.client = client
    yield s
    client.close()


def put(server, name: str, data: bytes) -> str:
    path = server.path(name)
    f = sp.SftpWriteFile(server.client, path)
    f.write(data)
    f.close()
    return path


def test_the_handshake_says_version_3_and_the_extensions_the_server_has(server):
    assert server.client.version == 3 and not server.client.closed
    assert sp.POSIX_RENAME in server.client.extensions


def test_a_file_written_over_the_wire_arrives_on_the_disk_and_reads_back(server, tmp_path):
    data = os.urandom(300_000)
    path = put(server, "a.bin", data)
    assert (tmp_path / "a.bin").read_bytes() == data
    f = sp.SftpReadFile(server.client, path, len(data))
    assert f.read() == data and f.read(10) == b""                            # to the end, then nothing more
    f.close()


def test_a_big_file_is_pipelined_in_both_directions_and_comes_back_exact(server, tmp_path):
    data = os.urandom(5 * 1024 * 1024 + 123)
    path = put(server, "big.bin", data)
    assert (tmp_path / "big.bin").stat().st_size == len(data)
    f = sp.SftpReadFile(server.client, path, len(data))
    h = hashlib.sha256()
    while True:
        block = f.read(1 << 20)
        if not block:
            break
        h.update(block)
    f.close()
    assert h.hexdigest() == hashlib.sha256(data).hexdigest()


def test_seek_and_partial_reads(server):
    data = bytes(range(256)) * 400
    path = put(server, "s.bin", data)
    f = sp.SftpReadFile(server.client, path, len(data))
    f.seek(100_000)
    assert f.read(5) == data[100_000:100_005] and f.tell() == 100_005
    f.seek(-10, 2)
    assert f.read() == data[-10:]
    f.seek(0)
    assert f.read(3) == data[:3]
    f.close()
    assert f.closed


def test_stat_and_listing_tell_files_from_folders_with_sizes_and_times(server, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.txt").write_bytes(b"hello")
    os.utime(tmp_path / "f.txt", (1_700_000_000, 1_700_000_000))
    names = {n.name: n.attrs for n in server.client.listdir(server.path(""))}
    assert set(names) == {"sub", "f.txt"} and names["sub"].is_dir and names["f.txt"].is_file
    assert names["f.txt"].size == 5 and names["f.txt"].mtime == 1_700_000_000
    st = server.client.stat(server.path("f.txt"))
    assert st.size == 5 and not st.is_dir
    assert server.client.listdir(server.path("sub")) == []


def test_folders_are_made_removed_and_renamed_and_an_existing_target_is_only_replaced_when_asked(server, tmp_path):
    server.client.mkdir(server.path("d"))
    assert (tmp_path / "d").is_dir()
    put(server, "d/one.txt", b"1")
    put(server, "d/two.txt", b"2")
    with pytest.raises(sp.SftpError):
        server.client.rename(server.path("d/one.txt"), server.path("d/two.txt"))               # version 3: refuses an existing target
    assert (tmp_path / "d" / "two.txt").read_bytes() == b"2"
    server.client.rename(server.path("d/one.txt"), server.path("d/two.txt"), overwrite=True)
    assert (tmp_path / "d" / "two.txt").read_bytes() == b"1" and not (tmp_path / "d" / "one.txt").exists()
    server.client.rename(server.path("d/two.txt"), server.path("d/three.txt"))
    server.client.remove(server.path("d/three.txt"))
    server.client.rmdir(server.path("d"))
    assert not (tmp_path / "d").exists()


def test_errors_arrive_as_the_exceptions_the_program_already_handles(server, tmp_path):
    with pytest.raises(FileNotFoundError):
        server.client.stat(server.path("missing"))
    with pytest.raises(FileNotFoundError):
        server.client.listdir(server.path("missing"))
    with pytest.raises(FileNotFoundError):
        sp.SftpReadFile(server.client, server.path("missing"), 0)
    server.client.mkdir(server.path("here"))
    with pytest.raises(OSError):
        server.client.mkdir(server.path("here"))
    put(server, "x.txt", b"x")
    with pytest.raises(OSError):
        sp.SftpWriteFile(server.client, server.path("x.txt"), exclusive=True)                  # it already exists
    with pytest.raises(OSError):
        server.client.rmdir(server.path("x.txt"))


def test_the_modified_time_can_be_set(server, tmp_path):
    put(server, "t.txt", b"t")
    server.client.set_mtime(server.path("t.txt"), 1_600_000_000)
    assert int((tmp_path / "t.txt").stat().st_mtime) == 1_600_000_000
    assert server.client.stat(server.path("t.txt")).mtime == 1_600_000_000


def test_names_with_spaces_and_non_ascii_letters_survive(server, tmp_path):
    name = "a b æøå ☃.txt"
    put(server, name, b"x")
    assert (tmp_path / name).read_bytes() == b"x"
    assert [n.name for n in server.client.listdir(server.path(""))] == [name]


def test_realpath_gives_an_absolute_path_and_a_lost_connection_is_a_connection_error(server):
    assert server.client.realpath(".")                                         # the server's own idea of where it is
    server.stop()
    with pytest.raises(ConnectionError):
        server.client.stat(server.path("anything"))
    assert server.client.closed


def test_two_threads_can_use_one_connection_without_mixing_up_the_answers(server):
    import threading
    data = os.urandom(400_000)
    path = put(server, "shared.bin", data)
    errors, results = [], []

    def lister():
        try:
            for _ in range(30):
                assert any(n.name == "shared.bin" for n in server.client.listdir(server.path("")))
        except Exception as e:   # noqa: BLE001
            errors.append(e)

    def reader():
        try:
            f = sp.SftpReadFile(server.client, path, len(data))
            results.append(f.read())
            f.close()
        except Exception as e:   # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=lister), threading.Thread(target=reader), threading.Thread(target=lister)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and results == [data]
