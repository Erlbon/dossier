"""Zip archives shown as read-only folders."""
import os
import struct
import zipfile

import pytest
from tests.helpers import wait_planned

from dossier.core import zipfs
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import execute, plan_copy, plan_delete, plan_move, plan_rename
from dossier.core.vfs import LocalFileSystem, NotWritable
from dossier.core.zipfs import ZipFileSystem, archive_root


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return str(path)


@pytest.fixture
def archive(tmp_path):
    return make_zip(tmp_path / "a.zip", {"readme.txt": "hello", "docs/one.txt": "1" * 100, "docs/deep/two.txt": "22",
                                         "empty/": ""})


@pytest.fixture
def fs():
    return ZipFileSystem()


def names(entries):
    return sorted(e.name for e in entries)


def test_the_root_lists_files_and_folders_with_implicit_parents(fs, archive):
    assert names(fs.list(archive_root(archive))) == ["docs", "empty", "readme.txt"]
    docs = [e for e in fs.list(archive_root(archive)) if e.name == "docs"][0]
    assert docs.is_dir and docs.path == archive_root(archive) + "docs"
    assert names(fs.list(docs.path)) == ["deep", "one.txt"]
    assert fs.list(archive_root(archive) + "empty") == []


def test_stat_reads_sizes_and_reports_missing_items(fs, archive):
    assert fs.stat(archive_root(archive) + "docs/one.txt").size == 100
    assert fs.stat(archive_root(archive)).is_dir
    with pytest.raises(FileNotFoundError):
        fs.stat(archive_root(archive) + "nope.txt")
    with pytest.raises(FileNotFoundError):
        fs.list(archive_root(archive) + "nope")


def test_open_read_gives_the_content_and_closes_the_archive(fs, archive):
    with fs.open_read(archive_root(archive) + "docs/deep/two.txt") as f:
        assert f.read() == b"22"
    os.remove(archive)                                    # no handle was left open (Windows would refuse)


def test_the_path_functions_stay_inside_the_archive_until_the_root(fs, archive):
    root = archive_root(archive)
    deep = root + "docs/deep"
    assert fs.basename(deep) == "deep" and fs.dirname(deep) == root + "docs"
    assert fs.parent(deep) == root + "docs" and fs.parent(root + "docs") == root
    assert fs.is_root(root) and not fs.is_root(deep)
    assert fs.basename(root) == "a.zip"
    assert fs.parent(root) == os.path.dirname(archive)       # one step up leaves the archive
    assert fs.join(root, "docs", "x.txt") == root + "docs/x.txt"
    assert fs.join(deep, "x") == deep + "/x"


def test_an_archive_with_an_exclamation_mark_in_its_name(fs, tmp_path):
    folder = tmp_path / "wow!"
    folder.mkdir()
    path = make_zip(folder / "a!.zip", {"x/y.txt": "y"})
    assert names(fs.list(archive_root(path) + "x")) == ["y.txt"]
    assert fs.split(archive_root(path) + "x/y.txt") == (path, "x/y.txt")


def test_names_that_climb_out_are_left_out(fs, tmp_path):
    path = make_zip(tmp_path / "evil.zip", {"../escape.txt": "x", "/abs.txt": "x", "C:/drive.txt": "x",
                                           "a/../../b.txt": "x", "fine.txt": "ok"})
    assert names(fs.list(archive_root(path))) == ["fine.txt"]


def test_backslash_names_become_folders(fs, tmp_path):
    path = make_zip(tmp_path / "w.zip", {"dir\\file.txt": "x"})
    assert names(fs.list(archive_root(path) + "dir")) == ["file.txt"]


def test_a_dos_code_page_name_is_decoded(fs, tmp_path):
    path = make_zip(tmp_path / "n.zip", {"r#d.txt": "x"})
    data = open(path, "rb").read().replace(b"r#d.txt", b"r" + bytes([0x91]) + b"d.txt")   # a DOS name, no UTF-8 flag
    open(path, "wb").write(data)
    (entry,) = fs.list(archive_root(path))
    assert entry.name == "r\u00e6d.txt"
    with fs.open_read(entry.path) as f:
        assert f.read() == b"x"


def test_the_listing_follows_changes_to_the_archive(fs, tmp_path):
    path = make_zip(tmp_path / "c.zip", {"a.txt": "a"})
    assert names(fs.list(archive_root(path))) == ["a.txt"]
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("b.txt", "bb")
    assert names(fs.list(archive_root(path))) == ["a.txt", "b.txt"]


def test_an_encrypted_entry_is_reported_not_guessed(fs, tmp_path):
    path = make_zip(tmp_path / "e.zip", {"s.txt": "secret"})
    data = bytearray(open(path, "rb").read())
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):   # set the "encrypted" bit in both headers
        i = data.find(sig)
        flags = struct.unpack_from("<H", data, i + off)[0] | 1
        struct.pack_into("<H", data, i + off, flags)
    open(path, "wb").write(bytes(data))
    with pytest.raises(PermissionError):
        fs.open_read(archive_root(path) + "s.txt")


def test_an_archive_that_is_not_a_zip_is_an_error_not_a_crash(fs, tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a zip")
    assert not zipfs.is_archive(str(bad))
    with pytest.raises(OSError):
        fs.list(archive_root(str(bad)))


def test_too_many_entries_are_refused(fs, tmp_path, monkeypatch):
    monkeypatch.setattr(zipfs, "MAX_ENTRIES", 3)
    path = make_zip(tmp_path / "big.zip", {f"f{i}": "x" for i in range(5)})
    with pytest.raises(OSError, match="entries"):
        fs.list(archive_root(path))


def test_nothing_in_an_archive_can_be_written(fs, archive):
    root = archive_root(archive)
    assert not fs.is_writable(root)
    for call in (lambda: fs.mkdir(root + "new"), lambda: fs.remove(root + "readme.txt"),
                 lambda: fs.rename(root + "readme.txt", root + "x"), lambda: fs.open_write(root + "n.txt")):
        with pytest.raises(NotWritable):
            call()


# through the router and the operation plans ---------------------------------------------------------
@pytest.fixture
def router():
    return RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider()))


def test_the_router_sends_zip_paths_to_the_archive_and_knows_it_is_read_only(router, archive, tmp_path):
    root = archive_root(archive)
    assert names(router.list(root)) == ["docs", "empty", "readme.txt"]
    assert not router.is_writable(root + "docs") and router.is_writable(str(tmp_path))


def test_copying_out_of_an_archive_works_with_folders(router, archive, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    root = archive_root(archive)
    plan = plan_copy(router, [root + "docs", root + "readme.txt"], str(dest))
    assert not plan.blocking and not plan.conflicts
    result = execute(plan, router)
    assert not result.failed
    assert (dest / "readme.txt").read_text() == "hello"
    assert (dest / "docs" / "deep" / "two.txt").read_text() == "22"


def test_copying_into_an_archive_is_blocked(router, archive, tmp_path):
    (tmp_path / "f.txt").write_text("f")
    plan = plan_copy(router, [str(tmp_path / "f.txt")], archive_root(archive))
    assert plan.blocking and "read-only" in plan.blocking[0]


def test_move_rename_and_delete_inside_an_archive_are_blocked(router, archive, tmp_path):
    root = archive_root(archive)
    assert plan_move(router, [root + "readme.txt"], str(tmp_path)).blocking
    assert plan_rename(router, root + "readme.txt", "x.txt").blocking
    assert plan_delete(router, [root + "readme.txt"]).blocking


def test_a_local_copy_of_an_entry_is_a_real_file(router, archive):
    path = zipfs.local_copy(router, archive_root(archive) + "docs/deep/two.txt")
    assert os.path.basename(path) == "two.txt" and open(path, "rb").read() == b"22"
    zipfs.clean_temp()
    assert not os.path.exists(path)


# in the window --------------------------------------------------------------------------------------
def test_enter_opens_a_zip_like_a_folder_and_dotdot_leaves_it(tmp_path):
    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import Qt
    from tests.test_gui_commander import FakeDialogs, key, names as panel_names, pump
    from PyQt6.QtWidgets import QApplication
    from dossier.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])      # must stay referenced
    left, right = tmp_path / "l", tmp_path / "r"
    left.mkdir()
    right.mkdir()
    make_zip(left / "a.zip", {"docs/one.txt": "1", "top.txt": "t"})
    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=dialogs)
    try:
        win.show()
        win.left.refresh()
        win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.zip"), 0))
        key(win, Qt.Key.Key_Return)
        pump(win, lambda: win.left.path.startswith("zip://"))
        assert panel_names(win.left) == ["..", "docs", "top.txt"]
        win.left.table.setCurrentIndex(win.left.model.index(0, 0))
        key(win, Qt.Key.Key_Return)                           # the cursor is on ".."
        pump(win, lambda: not win.left.path.startswith("zip://"))
        assert win.left.path == str(left)
        assert win.left.current_name() == "a.zip"
        # in again, then into a folder of the archive
        key(win, Qt.Key.Key_Return)
        pump(win, lambda: win.left.path.startswith("zip://"))
        win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("docs"), 0))
        key(win, Qt.Key.Key_Return)
        pump(win, lambda: win.left.path.endswith("docs"))
        assert panel_names(win.left) == ["..", "one.txt"]
        # a zip can be changed now (see test_zip_edit.py): delete asks first, and a "no" changes nothing; opening a member for
        # editing is still refused with a reason
        win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("one.txt"), 0))
        dialogs.confirm_answer = False
        dialogs.confirms.clear()
        win.delete()
        assert dialogs.confirms and "Delete 1 item from" in dialogs.confirms[-1][1]
        dialogs.confirm_answer = True
        dialogs.infos.clear()
        win.edit_file()
        assert dialogs.infos
        # copying out works from the window
        win.copy()                                            # the left panel is active, the target is the right one
        wait_planned(win)
        pump(win, lambda: (right / "one.txt").exists())
        assert (right / "one.txt").read_text() == "1"
    finally:
        win.close()
