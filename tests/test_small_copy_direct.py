"""A small new file is copied by the system straight to its name (decided 2026-11-06, after timing against robocopy): no part
file and no rename, which cost about a quarter of the time of a small file. A file that is replaced, a big file and anything that
is not a plain local path still go through the part file, so an existing file is never touched before the new one is whole."""
import os

import pytest

from dossier.core import fastcopy, transfer
from dossier.core.progress import Cancelled, CancelToken
from dossier.core.vfs import LocalFileSystem

pytestmark = pytest.mark.skipif(not fastcopy.available(), reason="no system copy on this platform")


def spy(monkeypatch):
    calls = []
    real = fastcopy.fast_copy

    def wrapper(src, dst, *a, **k):
        calls.append((src, dst, k.get("fail_if_exists", False)))
        return real(src, dst, *a, **k)
    monkeypatch.setattr(fastcopy, "fast_copy", wrapper)
    return calls


def make(path, data=b"small file " * 40, mtime=1_600_000_000):
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def test_a_small_new_file_goes_straight_to_its_name_with_time_and_content(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    src, dst = make(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    seen = []
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, progress=lambda d, t: seen.append((d, t)))
    assert calls == [(src, dst, True)]                                         # never overwrites what may have appeared meanwhile
    assert open(dst, "rb").read() == open(src, "rb").read() and int(os.path.getmtime(dst)) == 1_600_000_000
    assert seen[-1] == (os.path.getsize(src), os.path.getsize(src))


def test_a_file_that_is_replaced_still_goes_through_the_part_file(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    src, dst = make(tmp_path / "a.txt", b"new"), make(tmp_path / "b.txt", b"old")
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, overwrite=True)
    assert all(d != dst for _s, d, _f in calls) and open(dst, "rb").read() == b"new"


def test_the_system_copy_never_replaces_a_file_that_appeared_at_the_name(tmp_path):
    src, dst = make(tmp_path / "a.txt", b"mine"), make(tmp_path / "b.txt", b"theirs")
    with pytest.raises(FileExistsError):
        fastcopy.fast_copy(src, dst, 4, None, None, fail_if_exists=True)
    assert open(dst, "rb").read() == b"theirs"


def test_a_failed_or_cancelled_direct_copy_leaves_nothing_under_the_name(tmp_path, monkeypatch):
    src, dst = make(tmp_path / "a.txt"), str(tmp_path / "b.txt")

    def half_then_fail(s, d, *a, **k):
        with open(d, "wb") as f:
            f.write(b"half")
        raise OSError("the disk went away")
    monkeypatch.setattr(fastcopy, "fast_copy", half_then_fail)
    with pytest.raises(OSError):
        transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst)
    assert not os.path.exists(dst)
    token = CancelToken()
    token.cancel()
    monkeypatch.undo()
    with pytest.raises(Cancelled):
        transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, cancel=token)
    assert not os.path.exists(dst)


def test_a_verify_that_fails_removes_the_new_file(tmp_path):
    src, dst = make(tmp_path / "a.txt"), str(tmp_path / "b.txt")

    def bad(path):
        raise transfer.VerifyFailed("not the same")
    with pytest.raises(transfer.VerifyFailed):
        transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, check_part=bad)
    assert not os.path.exists(dst)


def test_a_big_file_keeps_the_part_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fastcopy, "FAST_MIN", 1000)
    calls = spy(monkeypatch)
    src, dst = make(tmp_path / "a.bin", b"x" * 5000), str(tmp_path / "b.bin")
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst)
    assert calls == [(src, dst + transfer.PART_SUFFIX, False)]


def test_the_window_s_router_still_gets_the_system_copy(tmp_path, monkeypatch):
    from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
    calls = spy(monkeypatch)
    router = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))
    src, dst = make(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    transfer.copy_file(router, src, router, dst)
    assert calls == [(src, dst, True)]


def test_a_file_system_that_reads_its_own_way_keeps_its_own_calls(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    opened = []

    class Watched(LocalFileSystem):
        def open_read(self, path):
            opened.append(path)
            return super().open_read(path)
    src, dst = make(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    transfer.copy_file(Watched(), src, Watched(), dst)
    assert calls == [] and opened == [src]
