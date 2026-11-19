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


def cursor_on(win, name):
    win.selection.clear()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of(name), 0))


def test_compress_one_file_makes_name_zip_beside_it_without_a_box(world, monkeypatch):
    win, d, left, right, *_ = world
    (left / "report.txt").write_text("hello")
    (left / "other.txt").write_text("o")
    win.left.refresh()
    win.select_all()
    cursor_on(win, "report.txt")
    monkeypatch.setattr(type(win), "_ask_pack", lambda self, dlg: pytest.fail("Compress must not ask"))
    win.compress_marked()
    pump(win, lambda: (left / "report.txt.zip").exists() and not win.busy and "Compressed" in win.status.text())
    assert names(str(left / "report.txt.zip")) == ["report.txt"]
    with zipfile.ZipFile(left / "report.txt.zip") as z:
        assert z.read("report.txt") == b"hello"
    assert not d.texts and not d.infos


def test_compress_several_items_uses_the_folder_name_and_a_taken_name_gets_a_number(world):
    win, d, left, right, *_ = world
    (left / "a.txt").write_text("aaa")
    (left / "sub").mkdir()
    (left / "sub" / "b.txt").write_text("bbb")
    (left / "left.zip").write_text("keep me")
    win.left.refresh()
    win.selection.set([str(left / "a.txt"), str(left / "sub")])
    assert len(win.left.targets()) == 2
    win.compress_marked()
    pump(win, lambda: (left / "left 2.zip").exists() and not win.busy and "Compressed" in win.status.text())
    assert (left / "left.zip").read_text() == "keep me"
    assert {"a.txt", "sub/", "sub/b.txt"} <= set(names(str(left / "left 2.zip")))


def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as w:
        for n, c in members.items():
            w.writestr(n, c)


def test_extract_here_one_item_goes_straight_in_and_many_go_into_a_folder(world):
    win, d, left, right, *_ = world
    make_zip(left / "one.zip", {"only.txt": "1"})
    make_zip(left / "many.zip", {"x.txt": "x", "dir/y.txt": "y"})
    win.left.refresh()
    cursor_on(win, "one.zip")
    win.extract_here()
    pump(win, lambda: (left / "only.txt").exists() and not win.busy)
    assert (left / "only.txt").read_text() == "1"
    cursor_on(win, "many.zip")
    win.extract_here()
    pump(win, lambda: (left / "many" / "dir" / "y.txt").exists() and not win.busy)
    assert (left / "many" / "x.txt").read_text() == "x" and not (left / "x.txt").exists()
    assert not d.texts                                                    # no box asked where to unpack


def test_extract_here_does_not_overwrite_silently(world):
    win, d, left, right, *_ = world
    make_zip(left / "one.zip", {"only.txt": "new"})
    (left / "only.txt").write_text("old")
    win.left.refresh()
    cursor_on(win, "one.zip")
    asked = []
    d.ask_conflicts = lambda rows, folder: asked.append(rows)           # the conflict question; cancelled
    win.extract_here()
    pump(win, lambda: asked)
    pump(win, lambda: not win.busy)
    assert (left / "only.txt").read_text() == "old"


def test_the_menus_offer_compress_and_extract_here(world):
    win, d, left, right, *_ = world
    (left / "c.txt").write_text("c")
    make_zip(left / "z.zip", {"a": "1"})
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    sub = [a for a in menus["Tools"].actions() if a.text() == "Archives"][0].menu()
    assert {"Compress", "Extract Here"} <= {a.text() for a in sub.actions()}
    zipmenu = [a.text() for a in win.build_context_menu(win.left, win.left.model.row_of("z.zip")).actions()]
    txtmenu = [a.text() for a in win.build_context_menu(win.left, win.left.model.row_of("c.txt")).actions()]
    assert "Compress" in zipmenu and "Extract Here" in zipmenu
    assert "Compress" in txtmenu and "Extract Here" not in txtmenu


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
