"""Changing a zip from the file lists: copy and move into an open zip, delete, rename and new folder inside it."""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from dossier.core.zipfs import archive_root  # noqa: E402
from dossier.gui.zip_edit import zip_parts  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def names(path):
    """The entries of the zip, or nothing while it is being swapped for its new version (the window does that on a thread)."""
    try:
        with zipfile.ZipFile(path) as z:
            return sorted(z.namelist())
    except (OSError, zipfile.BadZipFile):
        return []


def ready(path, predicate):
    """The zip as it is once the window has finished: read once, and never while it is being swapped for its new version."""
    found = names(path)
    return bool(found) and bool(predicate(found))


def make_zip(path, entries=("keep.txt", "dir/one.txt", "dir/two.txt")):
    with zipfile.ZipFile(path, "w") as z:
        for n in entries:
            z.writestr(n, n)


def open_zip(win, archive, inside=""):
    win.right.set_folder(archive_root(str(archive)) + inside)
    pump(win, lambda: win.right.path.startswith("zip://") and win.right.model.entry_count() >= 1)


def test_the_path_is_taken_apart_without_touching_the_disk():
    bs = chr(92)
    archive = "C:" + bs + "a" + bs + "b.zip"
    assert zip_parts("zip://" + archive + "!/dir/x.txt") == (archive, "dir/x.txt")
    assert zip_parts("zip://" + archive + "!/") == (archive, "") and zip_parts("zip://" + archive + "!") == (archive, "")
    assert zip_parts("C:" + bs + "plain") is None and zip_parts("home://") is None


def test_copying_into_the_open_zip_adds_files_and_folders_in_one_rewrite(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    (left / "new.txt").write_text("NEW")
    (left / "album").mkdir()
    (left / "album" / "t.txt").write_text("T")
    win.left.refresh()
    open_zip(win, z, "dir")
    win.select_all()
    win.copy()
    pump(win, lambda: d.confirms)
    assert "into a.zip" in d.confirms[-1][1] and "recycle bin" in d.confirms[-1][1]
    pump(win, lambda: not win.busy and ready(str(z), lambda n: "dir/new.txt" in n))
    assert {"dir/new.txt", "dir/album/", "dir/album/t.txt", "keep.txt", "dir/one.txt"} <= set(names(str(z)))
    assert (left / "new.txt").exists()                                          # a copy leaves the originals
    assert [n for n in os.listdir(tmp / "bin")]                                  # the old zip went to the bin


def test_a_clash_is_counted_and_the_new_file_replaces_the_old_one(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    (left / "keep.txt").write_text("REPLACED")
    win.left.refresh()
    open_zip(win, z)
    win.select_all()
    win.copy()
    pump(win, lambda: d.confirms)
    assert "1 entry with the same name will be replaced" in d.confirms[-1][1]
    pump(win, lambda: not win.busy and ready(str(z), lambda n: zipfile.ZipFile(z).read("keep.txt") == b"REPLACED"))


def test_moving_into_the_zip_then_trashes_the_originals(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    (left / "gone.txt").write_text("G")
    win.left.refresh()
    open_zip(win, z)
    win.select_all()
    win.move()
    pump(win, lambda: d.confirms)
    pump(win, lambda: not win.busy and ready(str(z), lambda n: "gone.txt" in n) and not (left / "gone.txt").exists())
    assert zipfile.ZipFile(z).read("gone.txt") == b"G"


def test_cancelling_the_confirmation_changes_nothing(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    before = z.read_bytes()
    (left / "n.txt").write_text("n")
    win.left.refresh()
    open_zip(win, z)
    win.select_all()
    d.confirm_answer = False
    win.copy()
    pump(win, lambda: d.confirms)
    pump(win, lambda: not win.busy)
    assert z.read_bytes() == before and not os.listdir(tmp / "bin")


def test_delete_inside_the_zip_removes_the_entries_after_a_confirmation(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    open_zip(win, z, "dir")
    win._set_active(win.right)
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("one.txt"), 0))
    win.delete()
    pump(win, lambda: d.confirms)
    assert "Delete 1 item from a.zip" in d.confirms[-1][1]
    pump(win, lambda: not win.busy and ready(str(z), lambda n: "dir/one.txt" not in n))
    assert {"keep.txt", "dir/two.txt"} <= set(names(str(z)))


def test_rename_and_new_folder_inside_the_zip(world):
    win, d, left, right, tmp = world
    z = right / "a.zip"
    make_zip(z)
    open_zip(win, z)
    win._set_active(win.right)
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("keep.txt"), 0))
    d.texts.append("kept.txt")
    win.rename()
    pump(win, lambda: not win.busy and ready(str(z), lambda n: "kept.txt" in n))
    assert "keep.txt" not in names(str(z))
    d.texts.append("fresh")
    win.new_folder()
    pump(win, lambda: not win.busy and ready(str(z), lambda n: "fresh/" in n))


def test_other_archives_say_why_they_cannot_be_written_into(world):
    py7zr = pytest.importorskip("py7zr")
    win, d, left, right, tmp = world
    seven = right / "a.7z"
    with py7zr.SevenZipFile(seven, "w") as w:
        w.writestr(b"x", "x.txt")
    (left / "n.txt").write_text("n")
    win.left.refresh()
    open_zip(win, seven)
    win.select_all()
    win.copy()
    pump(win, lambda: d.infos)
    assert "converted to zip" in d.infos[-1][1] and not [n for n in os.listdir(right) if n.endswith(".dossier-part")]
