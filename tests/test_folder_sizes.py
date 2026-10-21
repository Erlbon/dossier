"""Folder tree sizes on request: the walk, and the Size column."""
import os
import threading
import time

import pytest

from dossier.core.foldersize import TreeSize, folder_sizes, tree_size
from dossier.core.memfs import MemoryFileSystem
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem


def make_tree(root):
    for name, size in (("a.bin", 100), ("sub/b.bin", 2000), ("sub/deep/c.bin", 30000), ("sub/deep/d.bin", 1)):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    (root / "empty").mkdir(exist_ok=True)


def test_a_tree_is_added_up_with_counts(tmp_path):
    make_tree(tmp_path / "t")
    result = tree_size(LocalFileSystem(), str(tmp_path / "t"))
    assert result == TreeSize(size=32101, files=4, folders=3, unreadable=0)


def test_an_empty_folder_is_zero(tmp_path):
    (tmp_path / "e").mkdir()
    assert tree_size(LocalFileSystem(), str(tmp_path / "e")) == TreeSize()


def test_a_link_is_not_followed(tmp_path):
    make_tree(tmp_path / "t")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "big.bin").write_bytes(b"y" * 5000)
    try:
        os.symlink(tmp_path / "other", tmp_path / "t" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")
    assert tree_size(LocalFileSystem(), str(tmp_path / "t")).size == 32101        # the 5000 bytes behind the link are not counted


def test_a_loop_cannot_trap_the_walk(tmp_path):
    (tmp_path / "t" / "a").mkdir(parents=True)
    try:
        os.symlink(tmp_path / "t", tmp_path / "t" / "a" / "back", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")
    assert tree_size(LocalFileSystem(), str(tmp_path / "t")).folders == 1


class Unreadable(MemoryFileSystem):
    def list(self, path):
        if path.endswith("locked"):
            raise PermissionError(13, "denied", path)
        return super().list(path)


def test_a_folder_that_cannot_be_read_is_counted_and_skipped():
    fs = Unreadable()
    fs.put("mem://t/a.bin", b"x" * 10)
    fs.put("mem://t/ok/b.bin", b"x" * 20)
    fs.makedirs("mem://t/locked")
    result = tree_size(fs, "mem://t")
    assert result.size == 30 and result.unreadable == 1 and result.folders == 2


def test_cancel_stops_the_walk_promptly(tmp_path):
    fs = MemoryFileSystem()
    for i in range(200):
        fs.put(f"mem://t/d{i}/f.bin", b"x")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        tree_size(fs, "mem://t", token)


def test_several_folders_are_walked_with_progress_and_a_cancel_returns_what_was_done(tmp_path):
    fs = MemoryFileSystem()
    for name in ("a", "b", "c", "d"):
        fs.put(f"mem://t/{name}/f.bin", b"x" * 10)
    seen = []
    result = folder_sizes(fs, [f"mem://t/{n}" for n in "abcd"], progress=lambda *a: seen.append(a))
    assert {p.rsplit("/", 1)[1]: r.size for p, r in result.items()} == {"a": 10, "b": 10, "c": 10, "d": 10}
    assert seen[-1][0] == seen[-1][1] == 4 and any(a[3] for a in seen)               # names were reported
    token = CancelToken()
    token.cancel()
    assert folder_sizes(fs, [f"mem://t/{n}" for n in "abcd"], token) == {}


# in the window -------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401


def size_cells(panel):
    m = panel.model
    return {m.entry_at(r).name: m.data(m.index(r, 1)) for r in range(m.entry_count()) if not m.is_up_row(r)}


def wait_sizes(win, panel, folder):
    pump(win, lambda: size_cells(panel).get(folder) != "", timeout=10)


def setup(win, left):
    make_tree(left / "t")
    (left / "u").mkdir()
    (left / "u" / "x.bin").write_bytes(b"z" * 7000)
    (left / "plain.txt").write_text("hi")
    win.left.refresh()


def test_the_button_adds_up_every_folder_and_the_size_column_shows_it(world):
    win, _d, left, *_ = world
    setup(win, left)
    assert size_cells(win.left)["t"] == "" and size_cells(win.left)["u"] == ""
    win.left.sizes_button.click()
    wait_sizes(win, win.left, "t")
    cells = size_cells(win.left)
    assert cells["t"] == "31.3 K" or cells["t"].startswith("31") and cells["u"].startswith("6.8")
    assert cells["plain.txt"] == "2 B"
    assert "folders: " in win.status.text() or "folder" in win.status.text()


def test_marked_folders_only_when_some_are_marked(world):
    win, _d, left, *_ = world
    setup(win, left)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("u"), 0))
    key(win, Qt.Key.Key_Space)
    win.calculate_folder_sizes()
    wait_sizes(win, win.left, "u")
    cells = size_cells(win.left)
    assert cells["u"] != "" and cells["t"] == ""


def test_the_marked_total_of_the_status_line_counts_folder_sizes(world):
    win, _d, left, *_ = world
    setup(win, left)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("u"), 0))
    key(win, Qt.Key.Key_Space)
    win.calculate_folder_sizes()
    wait_sizes(win, win.left, "u")
    pump(win, lambda: "6.8" in win.status.text() or "folder" in win.status.text())
    win._update_status()
    assert "1 marked" in win.status.text() and ("6.8" in win.status.text())


def test_sorting_by_size_orders_folders_by_their_tree_size(world):
    win, _d, left, *_ = world
    setup(win, left)
    (left / "zero").mkdir()
    win.left.refresh()
    win.left.sizes_button.click()
    wait_sizes(win, win.left, "t")
    win.left.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert [n for n in names(win.left) if n in ("t", "u", "zero")] == ["t", "u", "zero"]
    win.left.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert [n for n in names(win.left) if n in ("t", "u", "zero")] == ["zero", "u", "t"]


def test_the_cursor_stays_on_its_item_when_the_sizes_arrive(world):
    win, _d, left, *_ = world
    setup(win, left)
    win.left.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("u"), 0))
    win.left.sizes_button.click()
    wait_sizes(win, win.left, "u")
    assert win.left.current_name() == "u"


def test_a_refresh_forgets_the_sizes_and_shows_dir_again(world):
    win, _d, left, *_ = world
    setup(win, left)
    win.left.sizes_button.click()
    wait_sizes(win, win.left, "t")
    win.left.refresh()
    pump(win, lambda: size_cells(win.left).get("t") == "")


def test_a_folder_list_without_folders_and_the_home_page_say_so(world):
    win, _d, left, *_ = world
    (left / "only.txt").write_text("x")
    win.left.refresh()
    win.calculate_folder_sizes()
    assert "no folders" in win.status.text()
    win.left.go_home()
    pump(win, lambda: win.left.is_home)
    win.calculate_folder_sizes()
    assert "Home page" in win.status.text()


def test_the_menu_item_and_the_other_panels_button_work(world):
    win, _d, left, right, tmp = world
    (right / "r").mkdir()
    (right / "r" / "f.bin").write_bytes(b"q" * 4096)
    win.right.refresh()
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Folder Sizes" in [a.text() for a in menus["View"].actions()]
    win.right.sizes_button.click()                       # the left panel is the active one; the button belongs to the right
    wait_sizes(win, win.right, "r")
    assert size_cells(win.right)["r"] == "4.0 K"
