"""C1 of the copy engine plan: small files are copied by several workers at once, everything else as before."""
import threading
import time

import pytest

from dossier.core import ops as ops_module
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import (ExecOptions, Resolution, choose_workers, execute, plan_copy, plan_delete, plan_move)
from dossier.core.progress import CancelToken
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem


class SlowMemory(MemoryFileSystem):
    """Memory file system where creating a file takes time (like a virus scanner), and which records how many
    were being created at the same moment."""

    def __init__(self, delay=0.02):
        super().__init__()
        self.delay = delay
        self.now = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.fail_on = set()
        self.started = []

    def open_write(self, path, *, exclusive=False):
        name = self.basename(path)
        if name.endswith(".dossier-part"):
            with self.lock:
                self.now += 1
                self.peak = max(self.peak, self.now)
                self.started.append(name)
            time.sleep(self.delay)
            with self.lock:
                self.now -= 1
            if name[:-len(".dossier-part")] in self.fail_on:
                raise PermissionError(13, "locked by another process", path)
        return super().open_write(path, exclusive=exclusive)


def build(n=40, size=10, delay=0.02):
    fs = SlowMemory(delay)
    fs.makedirs("mem://dst")
    for i in range(n):
        fs.put(f"mem://src/f{i:03d}.txt", bytes([i % 256]) * size)
    return fs


def copy_all(fs, **kw):
    plan = plan_copy(fs, [f"mem://src/f{i:03d}.txt" for i in range(40)], "mem://dst")
    return plan, execute(plan, fs, **kw)


# the speed-up --------------------------------------------------------------------------------------------------
def test_small_files_are_created_several_at_a_time_and_one_at_a_time_when_asked():
    fs = build()
    _plan, res = copy_all(fs, options=ExecOptions(workers=8))
    assert not res.failed and len(res.done) == 40 and fs.peak > 1
    fs2 = build()
    _plan, res2 = copy_all(fs2, options=ExecOptions(workers=1))
    assert fs2.peak == 1 and len(res2.done) == 40


def test_parallel_is_clearly_faster_when_creating_a_file_has_a_cost():
    serial, parallel = build(delay=0.03), build(delay=0.03)
    t = time.perf_counter()
    copy_all(serial, options=ExecOptions(workers=1))
    t_serial = time.perf_counter() - t
    t = time.perf_counter()
    copy_all(parallel, options=ExecOptions(workers=8))
    t_parallel = time.perf_counter() - t
    assert t_parallel < t_serial / 2.5, (t_serial, t_parallel)


def test_every_file_arrives_intact_and_no_temporary_name_is_left():
    fs = build(size=1000)
    copy_all(fs, options=ExecOptions(workers=8))
    names = [fs.basename(e.path) for e in fs.list("mem://dst")]
    assert len(names) == 40 and not any(n.endswith(".dossier-part") for n in names)
    for i in range(40):
        with fs.open_read(f"mem://dst/f{i:03d}.txt") as f:
            assert f.read() == bytes([i % 256]) * 1000


# the order of things ------------------------------------------------------------------------------------------------
def test_results_follow_the_plan_not_the_finishing_order():
    fs = build()
    plan, res = copy_all(fs, options=ExecOptions(workers=8))
    assert [r.op.src for r in res.results] == [op.src for op in plan.ops]


def test_folders_are_made_before_the_files_in_them():
    fs = SlowMemory(0.01)
    fs.put("mem://src/tree/a/one.txt", b"1")
    fs.put("mem://src/tree/a/b/two.txt", b"2")
    fs.put("mem://src/tree/c/three.txt", b"3")
    fs.put("mem://src/tree/four.txt", b"4")
    fs.makedirs("mem://dst")
    plan = plan_copy(fs, ["mem://src/tree"], "mem://dst")
    res = execute(plan, fs, options=ExecOptions(workers=8))
    assert not res.failed
    assert sorted(e.name for e in fs.list("mem://dst/tree")) == ["a", "c", "four.txt"]
    assert sorted(e.name for e in fs.list("mem://dst/tree/a")) == ["b", "one.txt"]


def test_big_files_are_copied_one_at_a_time_after_the_small_ones():
    fs = SlowMemory(0.02)
    fs.makedirs("mem://dst")
    for i in range(10):
        fs.put(f"mem://src/small{i}.txt", b"s" * 10)
    for i in range(4):
        fs.put(f"mem://src/big{i}.bin", b"B" * 5000)
    plan = plan_copy(fs, [e.path for e in fs.list("mem://src")], "mem://dst")
    res = execute(plan, fs, options=ExecOptions(workers=8, small_limit=1000))
    assert not res.failed
    order = [n[:-len(".dossier-part")] for n in fs.started]
    first_big = min(i for i, n in enumerate(order) if n.startswith("big"))
    assert all(n.startswith("small") for n in order[:first_big]) and first_big == 10
    assert fs.peak > 1                                                   # the small ones overlapped
    big_alone = SlowMemory(0.02)
    big_alone.makedirs("mem://dst")
    for i in range(4):
        big_alone.put(f"mem://src/big{i}.bin", b"B" * 5000)
    execute(plan_copy(big_alone, [e.path for e in big_alone.list("mem://src")], "mem://dst"), big_alone,
            options=ExecOptions(workers=8, small_limit=1000))
    assert big_alone.peak == 1                                           # never two big files at once


def test_a_few_small_files_do_not_start_a_pool():
    fs = build(n=3)
    plan = plan_copy(fs, [f"mem://src/f{i:03d}.txt" for i in range(3)], "mem://dst")
    execute(plan, fs)
    assert fs.peak == 1
    assert choose_workers(fs, plan, 3, ExecOptions()) == 1


# progress, cancel, errors ---------------------------------------------------------------------------------------------
def test_progress_from_several_workers_never_goes_back_and_ends_at_the_total():
    fs = build(size=500)
    seen = []
    lock = threading.Lock()

    def progress(d, t):
        with lock:
            seen.append((d, t))

    plan, res = copy_all(fs, progress=progress, options=ExecOptions(workers=8))
    assert seen and all(b[0] >= a[0] for a, b in zip(seen, seen[1:]))
    assert seen[-1] == (plan.total_work, plan.total_work)


def test_cancel_stops_new_files_and_leaves_no_half_file():
    fs = build(n=40, delay=0.02)
    token = CancelToken()

    def progress(d, t):
        if d >= 8 * 10:                       # after about eight files
            token.cancel()

    plan = plan_copy(fs, [f"mem://src/f{i:03d}.txt" for i in range(40)], "mem://dst")
    res = execute(plan, fs, progress=progress, cancel=token, options=ExecOptions(workers=4))
    assert res.cancelled
    names = [fs.basename(e.path) for e in fs.list("mem://dst")]
    assert 0 < len(names) < 40 and not any(n.endswith(".dossier-part") for n in names)
    assert len(res.results) < 40                                         # the ones never started have no result


def test_one_locked_file_is_reported_and_the_others_still_arrive():
    fs = build()
    fs.fail_on = {"f007.txt", "f021.txt"}
    plan, res = copy_all(fs, options=ExecOptions(workers=8))
    assert sorted(fs.basename(r.op.src) for r in res.failed) == ["f007.txt", "f021.txt"]
    assert all("locked" in r.error for r in res.failed) and len(res.done) == 38
    assert len(fs.list("mem://dst")) == 38


def test_a_bug_in_a_worker_is_raised_not_swallowed(monkeypatch):
    fs = build(n=10)
    original = ops_module.copy_file
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 6:
            raise RuntimeError("a bug")
        return original(*a, **k)

    monkeypatch.setattr(ops_module, "copy_file", flaky)
    plan = plan_copy(fs, [f"mem://src/f{i:03d}.txt" for i in range(10)], "mem://dst")
    with pytest.raises(RuntimeError, match="a bug"):
        execute(plan, fs, options=ExecOptions(workers=4))


def test_the_bin_is_asked_for_one_item_at_a_time_even_with_workers():
    fs = build(n=12, delay=0.0)
    for i in range(12):
        fs.put(f"mem://dst/f{i:03d}.txt", b"old")
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()
    binned = []

    def trasher(path):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.01)
        binned.append(path)
        fs.remove(path)
        with lock:
            active["now"] -= 1

    plan = plan_copy(fs, [f"mem://src/f{i:03d}.txt" for i in range(12)], "mem://dst").resolve(Resolution.OVERWRITE, fs)
    res = execute(plan, fs, trasher=trasher, options=ExecOptions(workers=8))
    assert not res.failed and len(binned) == 12 and active["peak"] == 1


# the choice of worker count ---------------------------------------------------------------------------------------------
def test_workers_are_chosen_by_the_target(monkeypatch, tmp_path):
    from dossier.core.drives import Drive
    local = LocalFileSystem()
    plan = plan_copy(local, [], str(tmp_path)) if False else None
    (tmp_path / "a").write_text("x")
    plan = plan_copy(local, [str(tmp_path / "a")], str(tmp_path / "..")) if False else plan_copy(
        local, [str(tmp_path / "a")], str(tmp_path))
    monkeypatch.setattr(ops_module, "list_drives", lambda: [Drive(str(tmp_path.anchor), "x", "", "fixed")])
    assert choose_workers(local, plan, 100, ExecOptions()) >= 2
    monkeypatch.setattr(ops_module, "list_drives", lambda: [Drive(str(tmp_path.anchor), "x", "", "removable")])
    assert choose_workers(local, plan, 100, ExecOptions()) == 2
    monkeypatch.setattr(ops_module, "list_drives", lambda: [Drive(str(tmp_path.anchor), "x", "", "optical")])
    assert choose_workers(local, plan, 100, ExecOptions()) == 1
    assert choose_workers(local, plan, 100, ExecOptions(workers=5)) == 5
    assert choose_workers(local, plan, 100, ExecOptions(workers=0)) == 1


def test_a_failing_drive_lookup_never_stops_a_copy(monkeypatch, tmp_path):
    local = LocalFileSystem()
    (tmp_path / "a").write_text("x")
    plan = plan_copy(local, [str(tmp_path / "a")], str(tmp_path))
    monkeypatch.setattr(ops_module, "list_drives", lambda: (_ for _ in ()).throw(RuntimeError("no drives")))
    assert choose_workers(local, plan, 100, ExecOptions()) >= 2


def test_real_disk_with_workers_gives_the_same_tree(tmp_path):
    local = LocalFileSystem()
    src, dst = tmp_path / "s", tmp_path / "d"
    for i in range(60):
        (src / f"dir{i % 5}").mkdir(parents=True, exist_ok=True)
        (src / f"dir{i % 5}" / f"f{i}.txt").write_bytes(bytes([i]) * 100)
    dst.mkdir()
    plan = plan_copy(local, [str(src)], str(dst))
    res = execute(plan, local, options=ExecOptions(workers=6))
    assert not res.failed
    for i in range(60):
        assert (dst / "s" / f"dir{i % 5}" / f"f{i}.txt").read_bytes() == bytes([i]) * 100


def test_moves_renames_and_deletes_are_unchanged_by_the_pool(tmp_path):
    local = LocalFileSystem()
    for n in "abcdef":
        (tmp_path / n).write_text(n)
    (tmp_path / "dst").mkdir()
    res = execute(plan_move(local, [str(tmp_path / n) for n in "abc"], str(tmp_path / "dst")), local,
                  options=ExecOptions(workers=8))
    assert len(res.done) == 3 and sorted(p.name for p in (tmp_path / "dst").iterdir()) == ["a", "b", "c"]
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    res = execute(plan_delete(local, [str(tmp_path / n) for n in "def"]), local,
                  trasher=lambda p: __import__("shutil").move(p, str(bin_)), options=ExecOptions(workers=8))
    assert len(res.done) == 3 and not (tmp_path / "d").exists()
