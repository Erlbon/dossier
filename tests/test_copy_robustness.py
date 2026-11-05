"""The copy engine against robocopy (docs/copy-robustness-plan.md, steps 1 to 3): waiting for the network, continuing a big file where it
stopped, and folder times."""
import errno
import os

import pytest

from dossier.core import transfer
from dossier.core.ops import ExecOptions, Kind, execute, is_network_error, is_transient, network_wait, plan_copy
from dossier.core.progress import Cancelled, CancelToken
from dossier.core.vfs import LocalFileSystem

T0 = 1_600_000_000


def put(path, data=b"x", mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def winerror(code: int) -> OSError:
    e = OSError(errno.EIO, "network")
    e.winerror = code
    return e


# 1: the network ---------------------------------------------------------------------------------------------------------------------------
def test_network_failures_are_told_from_locks_and_from_files_that_are_simply_wrong():
    for e in (winerror(64), winerror(59), winerror(121), winerror(53), TimeoutError(), ConnectionResetError(), OSError(errno.ETIMEDOUT, "t")):
        assert is_network_error(e), e
    for e in (FileNotFoundError(), PermissionError(), OSError(errno.ENOSPC, "full"), winerror(32)):
        assert not is_network_error(e), e
    assert is_transient(winerror(32)) and not is_transient(winerror(64))

    class NotConnected(ConnectionError):
        pass
    assert not is_network_error(NotConnected())                     # nobody is logging in again: waiting would not help
    assert [network_wait(n, 30) for n in range(5)] == [5, 10, 20, 30, 30]


class Flaky(LocalFileSystem):
    """A disk whose file opens fail with a network error a few times first."""

    def __init__(self, fails: int, error=None):
        super().__init__()
        self.fails, self.error, self.opens = fails, error, 0

    def open_read(self, path):
        self.opens += 1
        if self.fails:
            self.fails -= 1
            raise self.error or winerror(64)
        return super().open_read(path)


def test_a_file_waits_for_the_network_and_then_copies(tmp_path):
    src = put(tmp_path / "a" / "f.txt", b"data")
    (tmp_path / "b").mkdir()
    fs = Flaky(fails=3)
    waits = []
    plan = plan_copy(fs, [src], str(tmp_path / "b"))
    result = execute(plan, fs, options=ExecOptions(retry_delay=0, network_wait=0.01, on_wait=lambda *a: waits.append(a[1:3])))
    assert [r.status for r in result.results] == ["done"] and (tmp_path / "b" / "f.txt").read_bytes() == b"data"
    assert waits == [(1, 20), (2, 20), (3, 20)]


def test_when_the_network_stays_away_the_rest_fails_at_once_instead_of_waiting_all_over_again(tmp_path):
    for n in range(4):
        put(tmp_path / "a" / f"f{n}.txt", b"d")
    (tmp_path / "b").mkdir()
    fs = Flaky(fails=10_000)
    waits = []
    plan = plan_copy(fs, [str(tmp_path / "a" / f"f{n}.txt") for n in range(4)], str(tmp_path / "b"))
    result = execute(plan, fs, options=ExecOptions(retry_delay=0, network_wait=0.01, network_retries=3, workers=1,
                                                   on_wait=lambda *a: waits.append(a[1])))
    assert [r.status for r in result.results] == ["failed"] * 4 and waits == [1, 2, 3]
    assert "network" in result.results[0].error or result.results[0].error


def test_a_wait_for_the_network_stops_at_once_on_cancel(tmp_path):
    src = put(tmp_path / "a" / "f.txt")
    (tmp_path / "b").mkdir()
    token = CancelToken()
    fs = Flaky(fails=5)
    plan = plan_copy(fs, [src], str(tmp_path / "b"))
    result = execute(plan, fs, cancel=token, options=ExecOptions(network_wait=600, on_wait=lambda *a: token.cancel()))
    assert result.cancelled and [r.status for r in result.results] == ["cancelled"]


# 2: continuing a big file ------------------------------------------------------------------------------------------------------------------
class Breaking:
    """A source stream that fails with a network error after ``limit`` bytes."""

    def __init__(self, inner, limit):
        self.inner, self.limit, self.done = inner, limit, 0

    def read(self, n=-1):
        if self.done >= self.limit:
            raise winerror(64)
        data = self.inner.read(min(n, self.limit - self.done))
        self.done += len(data)
        return data

    def seek(self, *a):
        return self.inner.seek(*a)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.inner.close()


def test_a_big_file_that_broke_off_goes_on_from_where_it_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "RESUME_MIN", 1024 * 1024)
    monkeypatch.setattr(transfer, "RESUME_BACK", 64 * 1024)
    monkeypatch.setattr(transfer, "RESUME_CHECK", 16 * 1024)
    data = os.urandom(3 * 1024 * 1024)
    src = put(tmp_path / "a" / "big.bin", data)
    dst = str(tmp_path / "b" / "big.bin")
    (tmp_path / "b").mkdir()
    real_open = open
    calls = {"n": 0}

    def opener(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        if "r" in mode and "+" not in mode and os.path.normcase(str(path)).endswith(os.path.normcase(os.path.join("a", "big.bin"))):
            calls["n"] += 1
            if calls["n"] == 1:
                return Breaking(f, 2 * 1024 * 1024)                 # the first try breaks off at 2 MB
        return f
    monkeypatch.setattr("builtins.open", opener)
    fs = LocalFileSystem()
    with pytest.raises(OSError):
        transfer.copy_file(fs, src, fs, dst)
    assert transfer.resumed_part(dst) and not os.path.exists(dst)
    seen = []
    transfer.copy_file(fs, src, fs, dst, progress=lambda d, t: seen.append(d))
    assert real_open(dst, "rb").read() == data and not transfer.resumed_part(dst)
    assert seen[0] == 2 * 1024 * 1024 - 64 * 1024                  # it began where the sound part ended, not at 0
    assert os.path.getmtime(dst) == T0


def test_a_part_that_does_not_match_the_original_any_more_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "RESUME_MIN", 1024 * 1024)
    monkeypatch.setattr(transfer, "RESUME_BACK", 64 * 1024)
    monkeypatch.setattr(transfer, "RESUME_CHECK", 16 * 1024)
    data = os.urandom(2 * 1024 * 1024)
    src = put(tmp_path / "a" / "big.bin", data)
    dst = tmp_path / "b" / "big.bin"
    dst.parent.mkdir()
    part = str(dst) + transfer.PART_SUFFIX
    with open(part, "wb") as f:
        f.write(b"\0" * (1024 * 1024 + 300 * 1024))                # garbage of the right kind of length
    with open(part + ".json", "w") as f:
        import json
        json.dump({"source": os.path.abspath(src), "size": len(data), "mtime": T0}, f)
    seen = []
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), str(dst), progress=lambda d, t: seen.append(d))
    assert dst.read_bytes() == data and seen[0] <= 1024 * 1024       # started over: the first report is the first chunk
    os.utime(src, (T0 + 50, T0 + 50))
    assert transfer._resume_from(src, part, LocalFileSystem().stat(src)) == 0       # a changed original: never continued


def test_a_cancelled_big_copy_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "RESUME_MIN", 1024)
    src = put(tmp_path / "a" / "big.bin", os.urandom(64 * 1024))
    dst = str(tmp_path / "b" / "big.bin")
    (tmp_path / "b").mkdir()
    token = CancelToken()
    with pytest.raises(Cancelled):
        transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, cancel=token, chunk_size=4096,
                           progress=lambda d, t: token.cancel())
    assert os.listdir(tmp_path / "b") == []


# 3: folder times -----------------------------------------------------------------------------------------------------------------------------
def test_folders_a_copy_makes_get_the_times_of_the_folders_they_copy(tmp_path):
    put(tmp_path / "a" / "Vrakkart" / "NO" / "1910.doc", b"w", T0)
    for d, t in (("Vrakkart", T0 - 1000), (os.path.join("Vrakkart", "NO"), T0 - 500)):
        os.utime(tmp_path / "a" / d, (t, t))
    (tmp_path / "b").mkdir()
    fs = LocalFileSystem()
    plan = plan_copy(fs, [str(tmp_path / "a" / "Vrakkart")], str(tmp_path / "b"))
    assert any(op.kind is Kind.MKDIR for op in plan.ops)
    execute(plan, fs)
    assert int(os.path.getmtime(tmp_path / "b" / "Vrakkart")) == T0 - 1000
    assert int(os.path.getmtime(tmp_path / "b" / "Vrakkart" / "NO")) == T0 - 500
    (tmp_path / "c").mkdir()
    execute(plan_copy(fs, [str(tmp_path / "a" / "Vrakkart")], str(tmp_path / "c")), fs, options=ExecOptions(folder_times=False))
    assert int(os.path.getmtime(tmp_path / "c" / "Vrakkart")) != T0 - 1000
