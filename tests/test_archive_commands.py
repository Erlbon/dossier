"""Pack to Zip, Unpack and Convert to Zip from the window."""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog  # noqa: E402

from dossier.gui.archive_commands import PackDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def names(path):
    with zipfile.ZipFile(path) as z:
        return sorted(z.namelist())


def test_the_pack_dialog_builds_the_target_and_refuses_bad_names(app, tmp_path):
    d = PackDialog(None, str(tmp_path), "Holiday.zip", 3)
    assert d.target() == str(tmp_path / "Holiday.zip") and d.values()[1:] == ("normal", True)
    d.name.setText("photos")
    assert d.target() == str(tmp_path / "photos.zip")                       # .zip is added
    d.name.setText("a/b")
    d._accept()
    assert "without any of" in d.problem.text() and d.result() == 0
    d.name.setText("")
    d._accept()
    assert d.problem.text()
    d.name.setText("fine")
    d.level.setCurrentIndex(d.level.findData("store"))
    d._accept()
    assert d.result() == QDialog.DialogCode.Accepted and d.values()[1] == "store"


def test_pack_writes_the_marked_items_into_a_zip_in_the_other_panel(world, monkeypatch):
    win, d, left, right, *_ = world
    (left / "a.txt").write_text("aaa")
    (left / "sub").mkdir()
    (left / "sub" / "b.txt").write_text("bbb")
    win.left.refresh()
    win.select_all()
    monkeypatch.setattr(type(win), "_ask_pack", lambda self, dlg: True)
    win.pack_to_zip()
    pump(win, lambda: (right / "left.zip").exists() or any(n.endswith(".zip") for n in os.listdir(right)))
    pump(win, lambda: not win.busy and "Packed" in win.status.text())
    z = [n for n in os.listdir(right) if n.endswith(".zip")][0]
    assert names(str(right / z)) == ["a.txt", "sub/", "sub/b.txt"]
    assert "Packed 2 files" in win.status.text()


def test_pack_with_nothing_marked_says_what_to_do(world):
    win, *_ = world
    win.left.table.clearSelection()
    win.selection.clear()
    win.pack_to_zip()
    assert "Mark files" in win.status.text() or "pack" in win.status.text().lower()


def test_pack_will_not_overwrite_an_existing_zip(world, monkeypatch):
    win, d, left, right, *_ = world
    (left / "a.txt").write_text("aaa")
    (right / "a.zip").write_text("keep me")
    win.left.refresh()
    win.select_all()
    monkeypatch.setattr(type(win), "_ask_pack", lambda self, dlg: (dlg.name.setText("a.zip"), True)[1])
    win.pack_to_zip()
    pump(win, lambda: d.infos)
    assert (right / "a.zip").read_text() == "keep me" and "already exists" in d.infos[-1][1]


def test_unpack_copies_everything_into_a_folder_named_like_the_archive(world):
    win, d, left, right, *_ = world
    z = left / "stuff.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("one.txt", "1")
        w.writestr("dir/two.txt", "2")
    win.left.refresh()
    win.select_all()
    d.texts.append(str(right / "stuff"))
    win.unpack_archive()
    pump(win, lambda: (right / "stuff" / "dir" / "two.txt").exists())
    pump(win, lambda: not win.busy)
    assert (right / "stuff" / "one.txt").read_text() == "1" and (right / "stuff" / "dir" / "two.txt").read_text() == "2"


def test_unpacking_something_that_is_not_an_archive_is_explained(world):
    win, d, left, right, *_ = world
    (left / "plain.txt").write_text("x")
    win.left.refresh()
    win.select_all()
    d.texts.append(str(right / "plain"))
    win.unpack_archive()
    pump(win, lambda: d.infos)
    assert d.infos and not (right / "plain" / "x").exists()


def test_a_7z_is_converted_to_a_zip_beside_it(world):
    py7zr = pytest.importorskip("py7zr")
    win, d, left, right, *_ = world
    src = left / "pack"
    src.mkdir()
    (src / "x.txt").write_text("xx")
    archive = left / "pack.7z"
    with py7zr.SevenZipFile(archive, "w") as z:
        z.writeall(str(src), "pack")
    win.left.refresh()
    win.select_all()
    # only the 7z should be under the cursor: mark just it
    win.selection.clear()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("pack.7z"), 0))
    win.convert_archive_to_zip()
    pump(win, lambda: (left / "pack.zip").exists())
    pump(win, lambda: not win.busy)
    assert names(str(left / "pack.zip")) == ["pack/", "pack/x.txt"] and archive.exists()


def test_the_menu_has_the_three_commands(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    sub = [a for a in menus["Tools"].actions() if a.text() == "Archives"][0].menu()
    texts = [a.text() for a in sub.actions()]
    assert {"Pack to Zip...", "Unpack...", "Convert Archive to Zip", "Open as Archive"} <= set(texts)


def test_unpack_suggests_a_folder_beside_the_archive_not_in_the_other_panel(world):
    win, d, left, right, *_ = world
    z = left / "stuff.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("one.txt", "1")
    win.left.refresh()
    win.select_all()
    asked = []
    d.ask_text = lambda title, label, default="": asked.append(default)          # the question is only looked at, then cancelled
    win.unpack_archive()
    assert asked == [str(left / "stuff")]
    assert win.other.path == str(right)                                          # the other panel was right there, and was not used
