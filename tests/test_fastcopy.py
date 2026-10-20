"""C5: large local files go through the operating system's own copy, with progress, pause and cancel."""
import os
import sys
import threading
import time

import pytest

from dossier.core import fastcopy, transfer
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import ExecOptions, execute, plan_copy
from dossier.core.progress import Cancelled, CancelToken, SpeedLimit
from dossier.core.vfs import LocalFileSystem

pytestmark = pytest.mark.skipif(not fastcopy.available(), reason="no system copy on this platform")


@pytest.fixture(autouse=True)
def small_threshold(monkeypatch):
    monkeypatch.setattr(fastcopy, "FAST_MIN", 1000)


def spy(monkeypatch):
    calls = []
    real = fastcopy.fast_copy

    def wrapper(*a, **k):
        calls.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(fastcopy, "fast_copy", wrapper)
    return calls


def make(path, size, fill=b"abcdefgh"):
    with open(path, "wb") as f:
        f.write((fill * (size // len(fill) + 1))[:size])
    return str(path)


def test_a_large_local_file_is_copied_by_the_system_with_content_and_time_intact(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    src = make(tmp_path / "big.bin", 3_000_000)
    os.utime(src, (1_600_000_000, 1_600_000_000))
    dst = str(tmp_path / "out.bin")
    seen = []
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), dst, progress=lambda d, t: seen.append((d, t)))
    assert calls == [src]
    assert open(dst, "rb").read() == open(src, "rb").read()
    assert int(os.path.getmtime(dst)) == 1_600_000_000
    assert seen and seen[-1][0] == seen[-1][1] == 3_000_000 and all(a <= b for a, b in zip(seen, seen[1:]))
    assert not os.path.exists(dst + transfer.PART_SUFFIX)


def test_a_small_file_a_throttled_copy_and_the_switch_use_the_plain_path(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    fs = LocalFileSystem()
    small = make(tmp_path / "small.bin", 500)
    transfer.copy_file(fs, small, fs, str(tmp_path / "small2.bin"))
    big = make(tmp_path / "big.bin", 200_000)
    transfer.copy_file(fs, big, fs, str(tmp_path / "t.bin"), throttle=SpeedLimit(50_000_000))
    transfer.copy_file(fs, big, fs, str(tmp_path / "n.bin"), native=False)
    assert calls == []
    assert open(tmp_path / "t.bin", "rb").read() == open(big, "rb").read()


def test_memory_and_archive_paths_never_reach_the_system_copy(monkeypatch):
    calls = spy(monkeypatch)
    fs = MemoryFileSystem()
    fs.makedirs("mem://dst")
    fs.put("mem://src/big.bin", b"x" * 100_000)
    transfer.copy_file(fs, "mem://src/big.bin", fs, "mem://dst/big.bin")
    assert calls == [] and fs.stat("mem://dst/big.bin").size == 100_000


def test_cancel_stops_the_system_copy_and_leaves_no_part_file(tmp_path):
    fs = LocalFileSystem()
    src = make(tmp_path / "big.bin", 40_000_000)
    dst = str(tmp_path / "out.bin")
    token = CancelToken()

    def progress(done, total):
        if done > 1_000_000:
            token.cancel()

    with pytest.raises(Cancelled):
        transfer.copy_file(fs, src, fs, dst, progress=progress, cancel=token)
    assert not os.path.exists(dst) and not os.path.exists(dst + transfer.PART_SUFFIX)


def test_pause_holds_the_system_copy_until_resumed(tmp_path):
    fs = LocalFileSystem()
    src = make(tmp_path / "big.bin", 60_000_000)
    dst = str(tmp_path / "out.bin")
    token = CancelToken()
    reports = []
    paused_once = []

    def progress(done, total):
        reports.append(done)
        if not paused_once:
            paused_once.append(True)
            token.pause()

    thread = threading.Thread(target=lambda: transfer.copy_file(fs, src, fs, dst, progress=progress, cancel=token))
    thread.start()
    held, steady_since, end = -1, time.time(), time.time() + 20
    while time.time() < end:                                         # wait until nothing has been reported for a while
        time.sleep(0.05)
        if len(reports) != held:
            held, steady_since = len(reports), time.time()
        elif time.time() - steady_since >= 0.6 and paused_once:
            break
    assert thread.is_alive() and len(reports) == held and token.paused   # nothing moves while paused
    token.resume()
    thread.join(30)
    assert not thread.is_alive() and os.path.getsize(dst) == 60_000_000


def test_an_error_from_the_system_is_an_oserror_the_retry_logic_understands(tmp_path):
    fs = LocalFileSystem()
    src = make(tmp_path / "big.bin", 5_000)
    with pytest.raises(OSError):
        transfer.copy_file(fs, src, fs, str(tmp_path / "no-such-folder" / "out.bin"))


def test_execute_copies_big_files_through_the_system_and_reports_progress(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    monkeypatch.setattr("dossier.core.ops.SMALL_FILE_LIMIT", 100)
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    for i in range(3):
        make(src / f"f{i}.bin", 20_000 + i)
    fs = LocalFileSystem()
    plan = plan_copy(fs, [str(src / f"f{i}.bin") for i in range(3)], str(dst))
    reports = []
    res = execute(plan, fs, progress=lambda d, t: reports.append((d, t)), options=ExecOptions(small_limit=100))
    assert not res.failed and len(calls) == 3
    assert reports[-1][0] == reports[-1][1]
    off = ExecOptions(small_limit=100, native_copy=False)
    for p in dst.iterdir():
        p.unlink()
    calls.clear()
    execute(plan_copy(fs, [str(src / f"f{i}.bin") for i in range(3)], str(dst)), fs, options=off)
    assert calls == [] and len(list(dst.iterdir())) == 3


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="copy_file_range is Linux")
def test_the_linux_loop_falls_back_when_the_kernel_refuses(tmp_path, monkeypatch):
    def refuse(*_a):
        raise OSError(38, "no copy_file_range")        # ENOSYS

    monkeypatch.setattr(os, "copy_file_range", refuse)
    src = make(tmp_path / "a.bin", 5000)
    assert fastcopy.fast_copy(src, str(tmp_path / "b.bin"), 5000, None, None) is False
    transfer.copy_file(LocalFileSystem(), src, LocalFileSystem(), str(tmp_path / "c.bin"))
    assert open(tmp_path / "c.bin", "rb").read() == open(src, "rb").read()
