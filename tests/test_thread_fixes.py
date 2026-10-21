"""The window's thread never touches the disk for the things the review found: notes, the status line, unpacking an
archive member, closing; plus long names, exit with a stuck thread, and the exec bit."""
import os
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from dossier.core import notes as notes_module, transfer, zipfs
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import execute, plan_copy, plan_delete
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem
from dossier.core.worker import JobRunner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# notes ---------------------------------------------------------------------------------------------------------
class NoListing(MemoryFileSystem):
    def list(self, path):
        raise AssertionError("the folder was listed a second time")


def test_find_notes_uses_the_listing_it_is_given_and_does_not_list_again():
    mem = MemoryFileSystem()
    mem.put("mem://f/README.md", b"Hello")
    entries = mem.list("mem://f")
    mem.__class__ = NoListing                                   # from here on any listing is a failure
    assert [n.body for n in notes_module.find_notes(mem, "mem://f", entries)] == ["Hello"]


# in the window ------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402

from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

MAIN = threading.main_thread().ident


def watch_calls(monkeypatch, names=("list", "open_read", "stat")):
    seen = []
    for name in names:
        real = getattr(LocalFileSystem, name)

        def wrapper(self, path, *a, _real=real, _name=name, **k):
            seen.append((_name, str(path), threading.get_ident()))
            return _real(self, path, *a, **k)

        monkeypatch.setattr(LocalFileSystem, name, wrapper)
    return seen


def test_going_to_a_folder_lists_it_once_and_reads_its_note_off_the_window_thread(world, monkeypatch):
    win, _d, left, right, tmp = world
    folder = tmp / "withnote"
    folder.mkdir()
    (folder / "README.md").write_text("# Note\n\nHello there")
    (folder / "a.txt").write_text("a")
    win.left.set_folder(str(folder))
    pump(win, lambda: win.left.path == str(folder))
    pump(win, lambda: win.left.model.note_row >= 0)
    seen = watch_calls(monkeypatch)
    win.left.refresh()
    pump(win, lambda: True)
    pump(win, lambda: any(c[0] == "list" for c in seen))
    time.sleep(0.2)
    mine = [c for c in seen if os.path.normcase(c[1]).startswith(os.path.normcase(str(folder)))]
    listings = [c for c in mine if c[0] == "list" and os.path.normcase(c[1]) == os.path.normcase(str(folder))]
    assert len(listings) == 1                                                 # once, not a second time for the note
    assert not [c for c in mine if c[2] == MAIN and c[0] in ("list", "open_read")]   # and never on the window's thread
    assert win.left.model.note_row >= 0


def test_the_notes_can_be_switched_off_and_on_again(world):
    win, _d, left, right, tmp = world
    (left / "README.md").write_text("Hello")
    win.left.refresh()
    pump(win, lambda: win.left.model.note_row >= 0)
    win.set_notes_visible(False)
    assert win.left.model.note_row < 0
    win.set_notes_visible(True)
    pump(win, lambda: win.left.model.note_row >= 0)


# the status line ------------------------------------------------------------------------------------------
def test_the_status_line_asks_the_disk_for_an_unknown_size_on_a_thread(world, monkeypatch):
    win, _d, left, right, tmp = world
    (left / "a.bin").write_bytes(b"x" * 3000)
    win.left.refresh()
    win._sizes.clear()                                                         # the size is not known from a listing
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    seen = watch_calls(monkeypatch, names=("stat",))
    key(win, Qt.Key.Key_Space)
    pump(win, lambda: "2.9 K" in win.status.text() or "2.9 KB" in win.status.text(), timeout=10)
    asked = [c for c in seen if c[1].endswith("a.bin")]
    assert asked and all(c[2] != MAIN for c in asked)                          # looked up, but never on the window's thread


# unpacking an archive member ----------------------------------------------------------------------------------
def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


def test_viewing_a_file_inside_an_archive_unpacks_it_on_a_thread_and_then_opens_the_viewer(world):
    win, dialogs, left, right, tmp = world
    make_zip(left / "a.zip", {"inner/readme.txt": "hello from inside"})
    win.left.refresh()
    win.left.set_folder(zipfs.archive_root(str(left / "a.zip")) + "inner")
    pump(win, lambda: win.left.path.endswith("inner"))
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("readme.txt"), 0))
    win.view_file()
    pump(win, lambda: len(win.viewers) == 1, timeout=10)
    assert os.path.basename(win.viewers[0].paths[0]) == "readme.txt" if hasattr(win.viewers[0], "paths") else True


def test_enter_on_a_file_inside_an_archive_unpacks_it_and_hands_it_to_the_system(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    from dossier.gui import unpack as mw
    opened = []
    win.set_open_choice("system")                 # a text file would otherwise be shown in the viewer
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile()) or True))
    make_zip(left / "a.zip", {"x.txt": "xx"})
    win.left.set_folder(zipfs.archive_root(str(left / "a.zip")))
    pump(win, lambda: win.left.path.startswith("zip://"))
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("x.txt"), 0))
    key(win, Qt.Key.Key_Return)
    pump(win, lambda: len(opened) == 1, timeout=10)
    assert os.path.basename(opened[0]) == "x.txt" and open(opened[0], "rb").read() == b"xx"


def test_a_big_member_asks_first_and_declining_unpacks_nothing(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    from dossier.gui import unpack as mw
    opened = []
    monkeypatch.setattr(mw, "EXTRACT_CONFIRM", 1)
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    make_zip(left / "a.zip", {"big.bin": "x" * 100})
    win.left.set_folder(zipfs.archive_root(str(left / "a.zip")))
    pump(win, lambda: win.left.path.startswith("zip://"))
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("big.bin"), 0))
    dialogs.confirm_answer = False
    key(win, Qt.Key.Key_Return)
    wait_planned(win)
    assert dialogs.confirms and "unpacked" in dialogs.confirms[-1][1] and opened == [] and not win._size_jobs
    dialogs.confirm_answer = True
    key(win, Qt.Key.Key_Return)
    pump(win, lambda: len(opened) == 1, timeout=10)


class Bomb(MemoryFileSystem):
    """Says the file is 100 bytes and then hands out five megabytes."""

    def open_read(self, path):
        import io
        return io.BytesIO(b"x" * 5_000_000)


def test_local_copy_stops_an_item_that_unpacks_to_far_more_than_it_says_and_leaves_nothing():
    mem = Bomb()
    mem.put("mem://a/small.bin", b"x" * 100)
    before = set(os.listdir(zipfs._temp_root)) if zipfs._temp_root else set()
    with pytest.raises(OSError, match="much more"):
        zipfs.local_copy(mem, "mem://a/small.bin")
    after = {d for d in os.listdir(zipfs._temp_root)} if zipfs._temp_root else set()
    assert after == before                                                    # the half-unpacked folder was removed


def test_local_copy_reports_progress_and_can_be_cancelled():
    mem = MemoryFileSystem()
    mem.put("mem://a/f.bin", b"x" * 3_000_000)
    seen = []
    path = zipfs.local_copy(mem, "mem://a/f.bin", progress=seen.append)
    assert seen[-1] == 3_000_000 and os.path.getsize(path) == 3_000_000
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        zipfs.local_copy(mem, "mem://a/f.bin", cancel=token)


# closing and leaving --------------------------------------------------------------------------------------------
def test_a_permanent_delete_stops_between_items_when_cancelled(tmp_path):
    fs = LocalFileSystem()
    for i in range(30):
        (tmp_path / "tree" / f"d{i}").mkdir(parents=True, exist_ok=True)
        (tmp_path / "tree" / f"d{i}" / "f.txt").write_text("x")
    token = CancelToken()
    plan = plan_delete(fs, [str(tmp_path / "tree")], to_trash=False)
    token.cancel()
    res = execute(plan, fs, cancel=token)
    assert res.cancelled and (tmp_path / "tree").exists()                      # stopped before it removed anything big


def test_shutdown_can_drop_the_jobs_that_have_not_started():
    runner = JobRunner(workers=1)
    started = []
    gate = threading.Event()
    runner.submit("first", lambda progress, cancel: (started.append(1), gate.wait(2)))
    time.sleep(0.1)
    runner.submit("second", lambda progress, cancel: started.append(2))
    runner.shutdown(wait=False, cancel_futures=True)
    gate.set()
    time.sleep(0.3)
    assert started == [1]


def run_python(code, *args):
    return subprocess.run([sys.executable, "-I", "-c", code, ROOT, *args], capture_output=True, text=True, timeout=60)


def test_the_program_ends_even_when_a_background_thread_is_stuck():
    code = ("import sys, threading, time\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from dossier.gui.app import leave\n"
            "threading.Thread(target=lambda: time.sleep(60)).start()\n"          # a non-daemon thread that never ends
            "started = time.time()\n"
            "code = leave(7, grace=0.3)\n"
            "print('not reached', code)\n")
    start = time.time()
    done = run_python(code)
    assert done.returncode == 7 and "not reached" not in done.stdout and time.time() - start < 30


def test_leave_returns_the_code_when_nothing_is_stuck():
    code = ("import sys\nsys.path.insert(0, sys.argv[1])\nfrom dossier.gui.app import leave\n"
            "print(leave(5, grace=0.2))\n")
    done = run_python(code)
    assert done.returncode == 0 and done.stdout.strip() == "5"


# long names and the exec bit --------------------------------------------------------------------------------------
def test_a_file_with_a_very_long_name_can_be_copied_and_overwritten(tmp_path):
    from dossier.core.platform import longpath
    fs = LocalFileSystem()
    name = "n" * 244 + ".txt"                                                  # legal on NTFS, 257 with the part suffix
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    src, dst = str(tmp_path / "src" / name), str(tmp_path / "dst" / name)

    def put(path, text):
        with open(longpath(path), "w", encoding="utf-8") as f:
            f.write(text)

    def get(path):
        with open(longpath(path), encoding="utf-8") as f:
            return f.read()

    put(src, "NEW")
    res = execute(plan_copy(fs, [src], str(tmp_path / "dst")), fs)
    assert not res.failed and get(dst) == "NEW"
    assert os.listdir(longpath(str(tmp_path / "dst"))) == [name]                 # no temporary name left behind
    put(src, "NEWER")
    from dossier.core.ops import Resolution
    plan = plan_copy(fs, [src], str(tmp_path / "dst")).resolve(Resolution.OVERWRITE, fs)
    res = execute(plan, fs, trasher=lambda p: os.remove(longpath(p)))
    assert not res.failed and get(dst) == "NEWER" and os.listdir(longpath(str(tmp_path / "dst"))) == [name]


def test_side_names_keep_the_name_when_it_fits_and_are_short_when_it_does_not():
    fs = LocalFileSystem()
    assert transfer.side_name(fs, "C:" + chr(92) + "d" + chr(92) + "a.txt", ".dossier-part") == "C:" + chr(92) + "d" + chr(92) + "a.txt.dossier-part"
    long = os.path.join("C:" + os.sep, "d", "n" * 250)
    short = transfer.side_name(fs, long, ".dossier-part")
    assert os.path.dirname(short) == os.path.dirname(long) and len(os.path.basename(short)) < 40
    assert short.endswith(".dossier-part") and short != transfer.side_name(fs, long, ".dossier-part")   # unique each time


@pytest.mark.skipif(os.name == "nt", reason="the exec bit")
def test_a_file_copied_by_hand_keeps_its_exec_bit(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    script = tmp_path / "src" / "run.sh"
    script.write_text("#!/bin/sh\n")
    os.chmod(script, 0o755)
    execute(plan_copy(fs, [str(script)], str(tmp_path / "dst")), fs, options=__import__("dossier.core.ops", fromlist=["ExecOptions"]).ExecOptions(native_copy=False))
    assert os.access(tmp_path / "dst" / "run.sh", os.X_OK)


def test_copy_mode_is_harmless_everywhere(tmp_path):
    (tmp_path / "a").write_text("x")
    (tmp_path / "b").write_text("y")
    transfer.copy_mode(str(tmp_path / "a"), str(tmp_path / "b"))
    transfer.copy_mode(str(tmp_path / "missing"), str(tmp_path / "b"))
