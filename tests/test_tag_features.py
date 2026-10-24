"""Tags in the lists: the Tags and Rating columns, Mark by Tag, searching by tag, and the Flatten button."""
import os
import time

import pytest

from dossier.core import filetags
from dossier.core.filetags import Tags, write_tags
from dossier.core.search import Criteria, search
from dossier.core.vfs import LocalFileSystem

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

fs = LocalFileSystem()


def tagged_folder(base):
    """a (holiday, 2019, 4 stars, green), b (holiday), c (2019, 2 stars), d (nothing), and a sub folder with e (holiday)."""
    if not filetags.can_hold_tags(str(base)):
        pytest.skip("no place for tags here")
    for name, t in (("a.jpg", Tags(tags=["holiday", "2019"], rating=4, label="green")), ("b.jpg", Tags(tags=["holiday"])),
                    ("c.jpg", Tags(tags=["2019"], rating=2)), ("d.jpg", None)):
        p = base / name
        p.write_text(name)
        if t:
            write_tags(str(p), t)
    (base / "sub").mkdir()
    (base / "sub" / "e.jpg").write_text("e")
    write_tags(str(base / "sub" / "e.jpg"), Tags(tags=["holiday"], rating=5))


def names(result):
    return sorted(os.path.basename(e.path) for e in result.entries)


# search ------------------------------------------------------------------------------------------------------------
def test_search_finds_files_by_tag_rating_and_label(tmp_path):
    tagged_folder(tmp_path)
    root = str(tmp_path)
    assert names(search(fs, Criteria(root=root, tags=["holiday"]))) == ["a.jpg", "b.jpg", "e.jpg"]
    assert names(search(fs, Criteria(root=root, tags=["Holiday", "2019"]))) == ["a.jpg"]          # all of them, any case
    assert names(search(fs, Criteria(root=root, min_rating=4))) == ["a.jpg", "e.jpg"]
    assert names(search(fs, Criteria(root=root, label="GREEN"))) == ["a.jpg"]
    assert names(search(fs, Criteria(root=root, tags=["holiday"], subfolders=False))) == ["a.jpg", "b.jpg"]
    assert names(search(fs, Criteria(root=root, tags=["nothing-like-this"]))) == []
    assert "tagged holiday" in Criteria(root=root, tags=["holiday"], min_rating=3).describe()


def test_the_tag_test_comes_after_the_cheap_ones(tmp_path, monkeypatch):
    tagged_folder(tmp_path)
    seen = []
    real = filetags.read_tags
    monkeypatch.setattr(filetags, "read_tags", lambda p, backend=None: (seen.append(os.path.basename(p)), real(p, backend))[1])
    search(fs, Criteria(root=str(tmp_path), name="*.jpg", tags=["holiday"], subfolders=False))
    assert sorted(seen) == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]                  # folders and other names were never opened


def test_the_search_dialog_hands_tags_rating_and_label_to_the_criteria(app, tmp_path):
    from dossier.gui.search_dialog import SearchDialog
    d = SearchDialog(None, str(tmp_path))
    d.tags.setText("holiday; 2019, ")
    d.min_rating.setCurrentIndex(d.min_rating.findData(3))
    d.label.setCurrentIndex(d.label.findData("green"))
    c = d.criteria()
    assert c.tags == ["holiday", "2019"] and c.min_rating == 3 and c.label == "green"


# columns -----------------------------------------------------------------------------------------------------------
def shown(win, name, col):
    m = win.left.model
    r = next(i for i in range(m.entry_count()) if m.entry_at(i).name == name)
    return m.index(r, col).data()


def test_the_tags_and_rating_columns_are_off_by_default_and_read_nothing_until_switched_on(world, monkeypatch):
    win, d, left, *_ = world
    tagged_folder(left)
    reads = []
    real = filetags.read_tags
    monkeypatch.setattr(filetags, "read_tags", lambda p, backend=None: (reads.append(p), real(p, backend))[1])
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 5)
    time.sleep(0.2)
    assert reads == [] and not win.left.tag_columns_visible()
    win._column_toggled("tags", True)
    win._column_toggled("rating", True)
    from dossier.core.columns import index_of
    pump(win, lambda: shown(win, "a.jpg", index_of("tags")) == "holiday, 2019")
    assert shown(win, "a.jpg", index_of("rating")) == chr(0x2605) * 4 and shown(win, "d.jpg", index_of("tags")) == ""
    assert shown(win, "c.jpg", index_of("rating")) == chr(0x2605) * 2


def test_the_tags_column_sorts_and_follows_a_save(world):
    win, d, left, *_ = world
    tagged_folder(left)
    from dossier.core.columns import index_of
    win._column_toggled("tags", True)
    win.left.refresh()
    pump(win, lambda: shown(win, "b.jpg", index_of("tags")) == "holiday")
    from PyQt6.QtCore import Qt
    win.left.model.sort(index_of("tags"), Qt.SortOrder.DescendingOrder)
    files = [e.name for e in (win.left.model.entry_at(r) for r in range(win.left.model.entry_count())) if not e.is_dir]
    assert files[0] == "a.jpg" and files[-1] == "d.jpg"                              # "holiday, 2019" before "holiday", untagged last
    write_tags(str(left / "d.jpg"), Tags(tags=["zzz"]))
    win.left.refresh_tags()
    pump(win, lambda: shown(win, "d.jpg", index_of("tags")) == "zzz")


# mark by tag -------------------------------------------------------------------------------------------------------
def test_mark_by_tag_marks_what_carries_every_tag_and_unmark_takes_them_off(world):
    win, d, left, *_ = world
    tagged_folder(left)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 5)
    d.texts.append("holiday")
    win.mark_by_tag()
    pump(win, lambda: not win.busy and len(win.left.marked_here()) == 2)
    assert sorted(os.path.basename(p) for p in win.left.marked_here()) == ["a.jpg", "b.jpg"]
    assert "Marked 2 items tagged holiday" in win.status.text()
    d.texts.append("2019, holiday")
    win.mark_by_tag(mark=False)
    pump(win, lambda: not win.busy and len(win.left.marked_here()) == 1)
    assert [os.path.basename(p) for p in win.left.marked_here()] == ["b.jpg"]
    d.texts.append("never-used")
    win.mark_by_tag()
    pump(win, lambda: "Nothing here is tagged never-used" in win.status.text())


# the flatten button ------------------------------------------------------------------------------------------------
def test_the_flatten_button_sits_right_next_to_the_sigma_button_and_opens_the_flat_list(world):
    win, d, left, *_ = world
    (left / "sub").mkdir()
    (left / "sub" / "deep.txt").write_text("x")
    (left / "top.txt").write_text("x")
    win.left.refresh()
    bar = win.left.tool_group.layout()
    items = [bar.itemAt(i).widget() for i in range(bar.count())]
    assert items.index(win.left.flatten_button) == items.index(win.left.sizes_button) + 1
    assert win.left.flatten_button.text() == chr(0x2261) and "Flatten" in win.left.flatten_button.toolTip()
    tabs = win.left.tabs.count()
    win.left.flatten_button.click()
    pump(win, lambda: win.left.tabs.count() == tabs + 1)
    pump(win, lambda: win.left.path.startswith("flat:") and win.left.model.entry_count() >= 2)
    got = sorted(win.left.model.entry_at(r).name for r in range(win.left.model.entry_count()) if win.left.model.entry_at(r).name != "..")
    assert got == [os.path.join("sub", "deep.txt"), "top.txt"] or got == ["sub/deep.txt", "top.txt"]


# the Label column -------------------------------------------------------------------------------------------------
def test_the_label_column_shows_a_coloured_dot_and_the_name_and_sorts(world):
    win, d, left, *_ = world
    tagged_folder(left)
    from PyQt6.QtCore import Qt
    from dossier.core.columns import LABEL_COLORS, index_of
    assert "label" in __import__("dossier.core.columns", fromlist=["x"]).DEFAULT_HIDDEN
    win._column_toggled("label", True)
    win.left.refresh()
    pump(win, lambda: shown(win, "a.jpg", index_of("label")) == chr(0x25CF) + " Green")
    m = win.left.model
    row = next(r for r in range(m.entry_count()) if m.entry_at(r).name == "a.jpg")
    brush = m.index(row, index_of("label")).data(Qt.ItemDataRole.ForegroundRole)
    assert brush.color().name() == LABEL_COLORS["green"]
    assert shown(win, "b.jpg", index_of("label")) == ""
    m.sort(index_of("label"), Qt.SortOrder.DescendingOrder)
    assert [e.name for e in (m.entry_at(r) for r in range(m.entry_count())) if not e.is_dir][0] == "a.jpg"


def test_the_label_column_alone_is_enough_to_read_the_tags(world, monkeypatch):
    win, d, left, *_ = world
    tagged_folder(left)
    reads = []
    real = filetags.read_tags
    monkeypatch.setattr(filetags, "read_tags", lambda p, backend=None: (reads.append(p), real(p, backend))[1])
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 5)
    assert not win.left.tag_columns_visible() and reads == []
    win._column_toggled("label", True)
    pump(win, lambda: len(reads) >= 4)
    assert win.left.tag_columns_visible()
