"""The metadata columns in the window: off by default, read on a thread for the kinds of file that are needed, per folder layout."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from dossier.core.columns import META_KEYS, index_of  # noqa: E402
from dossier.core.metacolumns import SHARED_CACHE  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


class Reader:
    """A stand-in for the file readers: records what was opened and answers from the file name."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, kinds):
        self.calls.append((os.path.basename(path), tuple(sorted(kinds))))
        name = os.path.basename(path)
        stem = name.rsplit(".", 1)[0]
        if name.endswith(".mp3"):
            return {"m_artist": "Band " + stem[-1], "m_track": stem[-1]}
        if name.endswith(".cbz"):
            return {"m_series": "Series " + stem[-1]}
        return {}


def music_folder(tmp, name="music"):
    folder = tmp / name
    folder.mkdir(exist_ok=True)
    for n in ("a3.mp3", "b1.mp3", "c2.mp3", "d.txt", "e.cbz"):
        (folder / n).write_text(n)
    return folder


def goto(win, panel, path):
    panel.set_folder(str(path))
    pump(win, lambda: panel.path == str(path) and not panel.loading)


def cell(panel, name, key):
    return panel.model.index(panel.model.row_of(name), index_of(key)).data()


def use(win, reader):
    SHARED_CACHE.clear()
    for p in (win.left, win.right):
        p.meta_reader = reader


def test_the_metadata_columns_are_off_by_default_and_nothing_is_opened(world):
    win, d, left, right, tmp = world
    reader = Reader()
    use(win, reader)
    goto(win, win.left, music_folder(tmp))
    pump(win)
    assert reader.calls == []
    assert all(win.left.table.isColumnHidden(index_of(k)) for k in META_KEYS)
    assert win.left.meta_columns_visible() == []


def test_switching_a_column_on_reads_only_the_kinds_it_needs_and_fills_the_cells(world):
    win, d, left, right, tmp = world
    reader = Reader()
    use(win, reader)
    folder = music_folder(tmp)
    goto(win, win.left, folder)
    win.active = win.left
    win._column_toggled("m_artist", True)
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    assert cell(win.left, "b1.mp3", "m_artist") == "Band 1" and cell(win.left, "d.txt", "m_artist") == ""
    assert sorted({c[0] for c in reader.calls if c[0] in ("a3.mp3", "b1.mp3", "c2.mp3", "d.txt", "e.cbz")}) == ["a3.mp3", "b1.mp3", "c2.mp3"]
    assert {c[1] for c in reader.calls} == {("audio",)}                           # comics and text were never opened
    assert not win.left.table.isColumnHidden(index_of("m_artist"))


def test_the_list_can_be_sorted_by_a_metadata_column(world):
    win, d, left, right, tmp = world
    use(win, Reader())
    goto(win, win.left, music_folder(tmp))
    win.active = win.left
    win._column_toggled("m_track", True)
    pump(win, lambda: cell(win.left, "a3.mp3", "m_track") == "3")
    win.left.table.sortByColumn(index_of("m_track"), Qt.SortOrder.AscendingOrder)
    names = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    mp3 = [n for n in names if n.endswith(".mp3")]
    assert mp3 == ["b1.mp3", "c2.mp3", "a3.mp3"]


def test_a_file_is_read_once_until_it_changes(world):
    win, d, left, right, tmp = world
    reader = Reader()
    use(win, reader)
    folder = music_folder(tmp)
    goto(win, win.left, folder)
    win.active = win.left
    win._column_toggled("m_artist", True)
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    first = len(reader.calls)
    win.left.refresh()                                                            # the same folder again
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    assert len(reader.calls) == first
    (folder / "a3.mp3").write_text("changed and longer")
    win.left.refresh()
    pump(win, lambda: len(reader.calls) > first)
    assert len(reader.calls) == first + 1


def test_switching_the_column_off_stops_reading(world):
    win, d, left, right, tmp = world
    reader = Reader()
    use(win, reader)
    goto(win, win.left, music_folder(tmp))
    win.active = win.left
    win._column_toggled("m_artist", True)
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    win._column_toggled("m_artist", False)
    SHARED_CACHE.clear()
    count = len(reader.calls)
    win.left.refresh()
    pump(win)
    assert len(reader.calls) == count and win.left.meta_columns_visible() == []


def test_a_folder_layout_can_turn_the_columns_on_for_one_folder_only(world):
    win, d, left, right, tmp = world
    reader = Reader()
    use(win, reader)
    music, other = music_folder(tmp), music_folder(tmp, "other")
    goto(win, win.left, music)
    win.active = win.left
    win.remember_layout("only")
    win._column_toggled("m_artist", True)                                         # goes to the folder's layout, not the default
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    goto(win, win.left, other)
    pump(win)
    count = len(reader.calls)
    assert win.left.meta_columns_visible() == [] and win.left.table.isColumnHidden(index_of("m_artist"))
    assert cell(win.left, "a3.mp3", "m_artist") == "" and len(reader.calls) == count     # nothing was opened here
    goto(win, win.left, music)
    pump(win, lambda: cell(win.left, "a3.mp3", "m_artist") == "Band 3")
    assert not win.left.table.isColumnHidden(index_of("m_artist"))


def test_choices_saved_before_the_metadata_columns_existed_do_not_show_them(world):
    win, d, left, right, tmp = world
    win.settings.setValue("view/columns_hidden", "created,accessed,attributes,location,tags,rating,label")
    win.settings.setValue("view/columns_order", "name,type,size,modified")
    win.settings.remove("view/columns_known")
    hidden, order = win.column_choice()
    assert set(META_KEYS) <= hidden and set(META_KEYS) <= set(order)
    win.apply_columns_everywhere()
    assert win.left.meta_columns_visible() == []
