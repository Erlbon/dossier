"""Flat view, stored result lists and the search engine."""
import os
import time

import pytest

from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.listings import (FLAT_PREFIX, FOUND_PREFIX, FlatFileSystem, FoundFileSystem, ResultSet, ResultStore,
                                   relative, walk_files)
from dossier.core.memfs import MemoryFileSystem
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.search import BadCriteria, Criteria, search
from dossier.core.vfs import LocalFileSystem, NotWritable

fs = LocalFileSystem()


def write(path, text="x", mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture
def tree(tmp_path):
    t = tmp_path / "t"
    write(t / "a.txt", "alpha")
    write(t / "sub" / "b.txt", "beta needle here")
    write(t / "sub" / "deep" / "c.jpg", "gamma")
    write(t / "sub" / "deep" / "Report Final.TXT", "the Needle is here\nsecond line")
    write(t / "other" / "d.log", "delta")
    (t / "empty").mkdir()
    return t


# the flat view ----------------------------------------------------------------------------------------------
def test_walk_files_lists_every_file_by_its_path_below_the_root_and_never_a_folder(tree):
    entries = walk_files(fs, str(tree))
    names = sorted(e.name for e in entries)
    assert names == sorted(["a.txt", os.path.join("sub", "b.txt"), os.path.join("sub", "deep", "c.jpg"),
                            os.path.join("sub", "deep", "Report Final.TXT"), os.path.join("other", "d.log")])
    assert all(not e.is_dir and os.path.isfile(e.path) for e in entries)               # real paths, files only


def test_the_walk_skips_links_and_unreadable_folders_and_stops_when_cancelled(tree):
    class Picky(LocalFileSystem):
        def list(self, path):
            if path.endswith("other"):
                raise PermissionError(13, "no", path)
            return super().list(path)

    assert "d.log" not in " ".join(e.name for e in walk_files(Picky(), str(tree)))
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        walk_files(fs, str(tree), token)


def test_too_many_files_is_an_error_not_a_freeze(tree):
    with pytest.raises(OSError, match="too many"):
        walk_files(fs, str(tree), limit=2)


def test_relative_names_use_the_systems_separator():
    assert relative("C:" + chr(92) + "r", "C:" + chr(92) + "r" + chr(92) + "a" + chr(92) + "b.txt", "/") == "a/b.txt"
    assert relative("/r/", "/r/a/b.txt", "/") == "a/b.txt"


def test_a_flat_path_is_a_read_only_folder_whose_way_up_is_the_real_folder(tree):
    flat = FlatFileSystem(fs)
    path = FLAT_PREFIX + str(tree)
    assert flat.parent(path) == str(tree) and not flat.is_writable(path) and not flat.is_root(path)
    assert flat.basename(path) == "t (all files)" and flat.stat(path).is_dir
    assert len(flat.list(path)) == 5
    with pytest.raises(NotWritable):
        flat.mkdir(path + "/new")


# result lists ----------------------------------------------------------------------------------------------
def test_result_lists_are_stored_by_number_and_the_oldest_go_first():
    store = ResultStore(keep=2)
    paths = [store.add(ResultSet(f"s{i}", "C:" + chr(92) + "x", [])) for i in range(3)]
    assert paths == [FOUND_PREFIX + "1", FOUND_PREFIX + "2", FOUND_PREFIX + "3"]
    assert store.get(paths[0]) is None and store.get(paths[2]).title == "s2" and len(store) == 2
    assert store.get(FOUND_PREFIX + "nonsense") is None


def test_a_found_list_shows_what_still_exists_and_leads_back_to_where_it_started(tree):
    found = FoundFileSystem(fs)
    entries = walk_files(fs, str(tree))
    path = found.store.add(ResultSet("Search: x (5 found)", str(tree), entries))
    assert len(found.list(path)) == 5
    os.remove(tree / "a.txt")                                                          # gone since the search
    assert len(found.list(path)) == 4
    assert found.parent(path) == str(tree) and found.basename(path) == "Search: x (5 found)"
    assert not found.is_writable(path)
    with pytest.raises(FileNotFoundError):
        found.list(FOUND_PREFIX + "99")                                                # a list that is no longer kept
    assert found.parent(FOUND_PREFIX + "99") is None


def test_the_router_sends_flat_and_found_paths_to_their_systems(tree):
    router = RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider()))
    flat_path = FLAT_PREFIX + str(tree)
    assert len(router.list(flat_path)) == 5 and not router.is_writable(flat_path)
    path = router.found.store.add(ResultSet("S", str(tree), router.list(flat_path)[:2]))
    assert len(router.list(path)) == 2 and router.parent(path) == str(tree) and not router.is_writable(path)
    assert router.is_writable(str(tree))
    # the entries carry real paths, so every other command works on them
    entry = router.list(path)[0]
    assert router.stat(entry.path).size > 0 and router.is_writable(entry.path)


# the search engine -----------------------------------------------------------------------------------------
def found(tree, **kw):
    return sorted(e.name.replace(os.sep, "/") for e in search(fs, Criteria(root=str(tree), **kw)).entries)


def test_a_plain_word_is_found_anywhere_in_the_name_ignoring_case(tree):
    assert found(tree, name="report") == ["sub/deep/Report Final.TXT"]
    assert found(tree, name="REPORT", case_sensitive=True) == []


def test_wildcards_match_the_whole_name_and_several_patterns_and_exclusions_work(tree):
    assert found(tree, name="*.txt") == ["a.txt", "sub/b.txt", "sub/deep/Report Final.TXT"]
    assert found(tree, name="*.jpg;*.log") == ["other/d.log", "sub/deep/c.jpg"]
    assert found(tree, name="*.txt;!*report*") == ["a.txt", "sub/b.txt"]
    assert found(tree, name="?.txt") == ["a.txt", "sub/b.txt"]                       # one character, then .txt
    assert found(tree, name="??.txt") == []
    assert found(tree, name="*.TXT", case_sensitive=True) == ["sub/deep/Report Final.TXT"]


def test_subfolders_can_be_left_out_and_folders_can_be_searched_for(tree):
    assert found(tree, name="*", subfolders=False) == ["a.txt"]
    assert found(tree, kinds="folders") == ["empty", "other", "sub", "sub/deep"]
    both = found(tree, kinds="both", name="deep")
    assert both == ["sub/deep"]


def test_size_and_date_limits(tree):
    write(tree / "big.bin", "x" * 5000, mtime=1_500_000_000)
    write(tree / "new.bin", "y" * 10, mtime=1_700_000_000)
    assert found(tree, name="*.bin", min_size=1000) == ["big.bin"]
    assert found(tree, name="*.bin", max_size=100) == ["new.bin"]
    assert found(tree, name="*.bin", newer_than=1_600_000_000) == ["new.bin"]
    assert found(tree, name="*.bin", older_than=1_600_000_000) == ["big.bin"]


def test_text_search_finds_the_files_and_says_the_line(tree):
    result = search(fs, Criteria(root=str(tree), text="needle"))
    assert sorted(e.name.replace(os.sep, "/") for e in result.entries) == ["sub/b.txt", "sub/deep/Report Final.TXT"]
    by_name = {os.path.basename(e.path): e.detail for e in result.entries}
    assert by_name["Report Final.TXT"].startswith("line 1: the Needle is here")
    assert found(tree, text="NEEDLE", text_case=True) == []
    assert found(tree, text=r"ne+dle\b", text_regex=True) == ["sub/b.txt", "sub/deep/Report Final.TXT"]
    assert found(tree, text="second", name="*.txt") == ["sub/deep/Report Final.TXT"]


def test_a_binary_file_and_a_big_one_are_not_searched_for_text(tree):
    (tree / "bin.dat").write_bytes(b"\x00\x01needle\x00")
    assert "bin.dat" not in found(tree, text="needle")
    from dossier.core import search as search_module
    search_module.MAX_TEXT_FILE, old = 5, search_module.MAX_TEXT_FILE
    try:
        assert found(tree, text="needle") == []                                       # every file is "too big" now
    finally:
        search_module.MAX_TEXT_FILE = old


def test_utf16_text_is_searched_too(tree):
    (tree / "wide.txt").write_bytes("hello needle world".encode("utf-16"))
    assert "wide.txt" in found(tree, text="needle")


def test_a_search_can_be_cancelled_reports_progress_and_has_a_result_limit(tree):
    seen = []
    result = search(fs, Criteria(root=str(tree)), progress=lambda scanned, n: seen.append((scanned, n)))
    assert seen and seen[-1] == (result.scanned, len(result.entries))
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        search(fs, Criteria(root=str(tree)), token)
    limited = search(fs, Criteria(root=str(tree), max_results=2))
    assert limited.truncated and len(limited.entries) == 2


def test_bad_criteria_are_explained_before_anything_runs(tree):
    for bad, words in ((Criteria(root=str(tree), min_size=10, max_size=5), "smallest"),
                       (Criteria(root=str(tree), newer_than=20, older_than=10), "earliest"),
                       (Criteria(root=str(tree), text="(", text_regex=True), "valid pattern"),
                       (Criteria(root=str(tree), kinds="folders", text="x"), "folder has no text"),
                       (Criteria(root=str(tree), kinds="things"), "kinds")):
        with pytest.raises(BadCriteria, match=words):
            search(fs, bad)


def test_unreadable_folders_are_counted_and_the_search_goes_on(tree):
    class Picky(LocalFileSystem):
        def list(self, path):
            if path.endswith("other"):
                raise PermissionError(13, "no", path)
            return super().list(path)

    result = search(Picky(), Criteria(root=str(tree), name="*.log"))
    assert result.entries == [] and result.unreadable == 1


def test_the_criteria_describe_themselves_for_the_title():
    assert Criteria(root="r", name="*.jpg").describe() == "*.jpg"
    assert Criteria(root="r", name="a", text="b").describe() == 'a containing "b"'
    assert Criteria(root="r").describe() == "everything"


def test_a_memory_file_system_can_be_searched_too():
    mem = MemoryFileSystem()
    mem.put("mem://r/a.txt", b"hello")
    mem.put("mem://r/sub/b.txt", b"hello hello")
    result = search(mem, Criteria(root="mem://r", text="hello"))
    assert sorted(e.name for e in result.entries) == ["a.txt", "sub/b.txt"]


# in the window ---------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402

from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401


def build_tree(left):
    write(left / "a.txt", "alpha")
    write(left / "sub" / "b.txt", "beta needle")
    write(left / "sub" / "deep" / "c.txt", "gamma")


def test_all_files_below_opens_a_new_tab_with_every_file_and_the_way_up_goes_back(world):
    win, _d, left, right, tmp = world
    build_tree(left)
    win.left.refresh()
    tabs = win.left.tabs.count()
    win.show_all_files_below()
    pump(win, lambda: win.left.path.startswith(FLAT_PREFIX))
    assert win.left.tabs.count() == tabs + 1
    assert sorted(n.replace(os.sep, "/") for n in names(win.left) if n != "..") == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    win.left.table.setCurrentIndex(win.left.model.index(0, 0))                          # the ".." row
    key(win, Qt.Key.Key_Return)
    pump(win, lambda: win.left.path == str(left))


def test_the_commands_work_on_the_files_of_a_flat_list(world):
    win, dialogs, left, right, tmp = world
    build_tree(left)
    win.left.refresh()
    win.show_all_files_below()
    pump(win, lambda: win.left.path.startswith(FLAT_PREFIX))
    win.left.table.setCurrentIndex(win.left.model.index(2, 0))                              # sub/b.txt (row 0 is "..", row 1 a.txt)
    key(win, Qt.Key.Key_Space)
    win.copy()
    wait_planned(win)
    assert f"from {left}" in dialogs.confirms[-1][1] and "flat://" not in dialogs.confirms[-1][1]
    pump(win, lambda: (right / "b.txt").exists())                                         # copied by its real path
    assert (right / "b.txt").read_text() == "beta needle" and (left / "sub" / "b.txt").exists()


def test_a_flat_list_cannot_be_written_to_or_pinned_and_a_terminal_opens_in_its_real_folder(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    build_tree(left)
    win.show_all_files_below()
    pump(win, lambda: win.left.path.startswith(FLAT_PREFIX))
    win.new_folder()
    assert dialogs.infos and "read-only" in dialogs.infos[-1][1]
    win.pin_folder()
    assert "not a folder" in dialogs.infos[-1][1] or "list or an archive" in dialogs.infos[-1][1]
    assert win.left.real_folder() == str(left)
    launched = []
    win.launch_terminal = lambda launch: launched.append(launch)
    win.open_terminal()
    assert launched and launched[0].cwd == str(left)


def test_a_search_opens_its_result_in_a_new_tab_and_the_folder_stays_where_it_was(world):
    win, dialogs, left, right, tmp = world
    build_tree(left)
    win.left.refresh()
    tabs = win.left.tabs.count()
    win.start_search(Criteria(root=str(left), text="needle"))
    pump(win, lambda: win.left.path.startswith(FOUND_PREFIX), timeout=10)
    assert win.left.tabs.count() == tabs + 1
    assert [n.replace(os.sep, "/") for n in names(win.left) if n != ".."] == ["sub/b.txt"]
    assert "1 found" in win.left.tabs.tabText(win.left.tabs.currentIndex()) or "Search" in win.left.tabs.tabText(win.left.tabs.currentIndex())
    win.left.tabs.setCurrentIndex(0)                                                         # the folder tab is as it was
    pump(win, lambda: win.left.path == str(left))
    assert "found among" in win.status.text() or "looked at" in win.status.text() or win.left.path == str(left)


def test_a_bad_search_is_explained_and_makes_no_tab(world):
    win, dialogs, left, *_ = world
    tabs = win.left.tabs.count()
    win.start_search(Criteria(root=str(left), min_size=10, max_size=1))
    assert dialogs.infos and "smallest" in dialogs.infos[-1][1] and win.left.tabs.count() == tabs


def test_a_search_result_tab_is_saved_as_the_folder_it_started_in(world):
    win, dialogs, left, *_ = world
    build_tree(left)
    win.start_search(Criteria(root=str(left), name="*.txt"))
    pump(win, lambda: win.left.path.startswith(FOUND_PREFIX), timeout=10)
    assert str(left) in win.left.tab_paths() and not any(p.startswith(FOUND_PREFIX) for p in win.left.tab_paths())


def test_the_go_menu_has_the_flat_view(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "All Files Below This Folder" in [a.text() for a in menus["Go"].actions()]
