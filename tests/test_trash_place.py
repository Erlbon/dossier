"""Card 46B (2026-11-18): the Trash as a place on Linux and Windows, with Put Back and Empty (core/trash.py)."""
from __future__ import annotations

import os
import struct
import time

from dossier.core import trash
from dossier.core.ops import execute
from dossier.core.vfs import LocalFileSystem


def _xdg_trash(tmp_path, original, content=b"hello"):
    bin_folder = tmp_path / "data" / "Trash"
    (bin_folder / "files").mkdir(parents=True, exist_ok=True)
    (bin_folder / "info").mkdir(parents=True, exist_ok=True)
    name = os.path.basename(original)
    (bin_folder / "files" / name).write_bytes(content)
    (bin_folder / "info" / (name + ".trashinfo")).write_text(trash.record_text(str(original), time.time() - 60), encoding="utf-8")
    return bin_folder


def test_a_trashinfo_record_is_read():
    path, when = trash.parse_trashinfo("[Trash Info]\nPath=/home/kari/My%20File.txt\nDeletionDate=2026-11-18T10:20:30\n")
    assert path == "/home/kari/My%20File.txt" and when > 0


def test_a_windows_record_is_read_in_both_versions():
    original = "C:" + chr(92) + "Users" + chr(92) + "kari" + chr(92) + "a.txt"
    filetime = int((1_700_000_000 + 11644473600) * 10_000_000)
    v2 = struct.pack("<QQQI", 2, 1234, filetime, len(original) + 1) + (original + chr(0)).encode("utf-16-le")
    assert trash.parse_recycle_record(v2) == (original, 1234, 1_700_000_000)
    v1 = struct.pack("<QQQ", 1, 5, filetime) + (original + chr(0)).encode("utf-16-le").ljust(520, b"\0")
    assert trash.parse_recycle_record(v1)[0] == original


def test_the_bins_of_the_standard_are_found(tmp_path):
    (tmp_path / "data" / "Trash").mkdir(parents=True)
    stick = tmp_path / "stick"
    (stick / ".Trash-1000" / "info").mkdir(parents=True)
    bins = trash.xdg_bins(str(tmp_path), [("/", "System", "fixed"), (str(stick), "stick", "removable")], 1000,
                          {"XDG_DATA_HOME": str(tmp_path / "data")})
    assert [b.folder for b in bins] == [str(tmp_path / "data" / "Trash"), str(stick / ".Trash-1000")]
    assert bins[1].top == str(stick)


def test_items_list_with_where_they_came_from_and_put_back_restores_them(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    original = home / "Documents" / "notes.txt"
    bin_folder = _xdg_trash(tmp_path, original)
    items = trash.list_items([trash.Bin(str(bin_folder))])
    assert len(items) == 1 and items[0].name == "notes.txt" and items[0].original == str(original)
    fs = LocalFileSystem()
    plan = trash.put_back_plan(fs, items)
    assert plan.executable and not plan.blocking                      # Documents is gone: it is made again
    execute(plan, fs)
    assert original.read_bytes() == b"hello"
    assert trash.forget_restored(items) == 1
    assert trash.list_items([trash.Bin(str(bin_folder))]) == []


def test_put_back_onto_a_taken_place_is_a_conflict(tmp_path):
    original = tmp_path / "home" / "a.txt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"new one")
    items = trash.list_items([trash.Bin(str(_xdg_trash(tmp_path, original)))])
    plan = trash.put_back_plan(LocalFileSystem(), items)
    assert plan.conflicts


def test_emptying_removes_items_and_records_for_good(tmp_path):
    bin_folder = _xdg_trash(tmp_path, tmp_path / "x" / "gone.txt")
    (bin_folder / "files" / "folder").mkdir()
    (bin_folder / "files" / "folder" / "inner.txt").write_text("x", encoding="utf-8")
    (bin_folder / "info" / "folder.trashinfo").write_text(trash.record_text(str(tmp_path / "x" / "folder"), time.time()),
                                                         encoding="utf-8")
    items = trash.list_items([trash.Bin(str(bin_folder))])
    assert {i.name for i in items} == {"gone.txt", "folder"}
    assert trash.remove_for_good(items) == (2, [])
    assert os.listdir(bin_folder / "files") == [] and os.listdir(bin_folder / "info") == []


def test_a_path_in_a_bin_is_recognised():
    assert trash.in_a_bin("C:" + chr(92) + "$Recycle.Bin" + chr(92) + "S-1-5" + chr(92) + "$R12.txt")
    assert trash.in_a_bin("/home/kari/.local/share/Trash/files/a.txt")
    assert trash.in_a_bin("/media/stick/.Trash-1000/files/a.txt")
    assert not trash.in_a_bin("/home/kari/Trash/a.txt")
