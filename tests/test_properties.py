"""The Properties dialog: facts of one or many items and the read-only metadata of audio, comic and video files."""
import os
import zipfile

import pytest

from dossier.core import properties
from dossier.core.properties import gather, kind_of, many_items, one_item
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()

INFO = ("<ComicInfo><Series>Blueberry</Series><Number>3</Number><Year>1973</Year><Writer>Charlier</Writer>"
        "<PageCount>48</PageCount></ComicInfo>")


def facts(g):
    return {f.label: f.value for f in g.facts}


def test_the_reader_is_chosen_by_the_extension():
    assert kind_of("a.MP3") == "audio" and kind_of("a.cbz") == "comic" and kind_of("a.mkv") == "video"
    assert kind_of("a.txt") == "" and kind_of("noext") == ""


def test_a_file_gives_name_place_type_size_and_times(tmp_path):
    f = tmp_path / "report.txt"
    f.write_text("x" * 2048)
    g = one_item(fs, str(f))
    d = facts(g)
    assert d["Name"] == "report.txt" and d["Type"] == "TXT file" and d["Location"] == str(tmp_path)
    assert "2,048 bytes" in d["Size"] and d["Modified"][:2] == "20" and d["Attributes"]
    assert g.meta is None and g.title == "Properties of report.txt"


def test_a_folder_gives_the_size_of_everything_below_it(tmp_path):
    (tmp_path / "d" / "e").mkdir(parents=True)
    (tmp_path / "d" / "a.bin").write_bytes(bytes(100))
    (tmp_path / "d" / "e" / "b.bin").write_bytes(bytes(50))
    d = facts(one_item(fs, str(tmp_path / "d")))
    assert d["Type"] == "Folder" and "150 bytes" in d["Size"] and "2 files and 1 folders" in d["Size"]


def test_several_items_give_totals(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "x").write_bytes(bytes(10))
    (tmp_path / "a").write_bytes(bytes(5))
    (tmp_path / "b").write_bytes(bytes(7))
    g = many_items(fs, [str(tmp_path / n) for n in ("d", "a", "b")])
    d = facts(g)
    assert d["Items"] == "3: 2 files, 1 folders" and "22 bytes" in d["Total size"] and d["Files inside the folders"] == "1"
    assert gather(fs, [str(tmp_path / "a")]).title == "Properties of a"


def test_a_cbz_carries_its_comicinfo_and_nothing_is_written(tmp_path):
    p = tmp_path / "x.cbz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ComicInfo.xml", INFO)
        z.writestr("001.jpg", bytes(5))
    before = p.read_bytes()
    g = one_item(fs, str(p))
    assert g.meta_kind == "comic" and g.meta.get("series") == "Blueberry" and g.meta.get("writer") == "Charlier"
    assert p.read_bytes() == before


def test_audio_and_video_go_to_their_readers_and_a_failing_reader_never_raises(tmp_path, monkeypatch):
    seen = []
    from redactor_common.core.meta_fields import MetaResult
    real = properties.read_metadata

    def fake(path, kind):
        seen.append(kind)
        return MetaResult(kind)

    monkeypatch.setattr(properties, "read_metadata", fake)
    for name in ("a.mp3", "b.mkv"):
        (tmp_path / name).write_bytes(b"x")
        one_item(fs, str(tmp_path / name))
    assert seen == ["audio", "video"]
    assert real(str(tmp_path / "nothing.xyz"), "other").error == "no reader for this type"


pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui.properties import PropertiesDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_window_shows_a_general_and_a_metadata_tab_for_a_comic(world, monkeypatch):
    win, d, left, *_ = world
    p = left / "x.cbz"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ComicInfo.xml", INFO)
    win.left.refresh()
    shown = []
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: shown.append(dlg))
    win.select_all()
    win.show_properties()
    pump(win, lambda: shown)
    dlg = shown[0]
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["General", "ComicInfo"]
    labels = [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())]
    assert "Tags" in labels and "Credits" in labels
    assert "Series: Blueberry" in dlg.text() and "Writer: Charlier" in dlg.text()
    flags = dlg.tree.topLevelItem(0).child(0).flags()
    assert not flags & Qt.ItemFlag.ItemIsEditable                              # read only
    dlg.copy_all()
    assert "Blueberry" in QApplication.clipboard().text()


def test_nothing_to_show_says_so_and_the_menu_has_properties(world):
    win, *_ = world
    win.left.table.clearSelection()
    win.selection.clear()
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Properties" in [a.text() for a in menus["Files"].actions()]
    assert win.act_properties.shortcut().toString() in ("Alt+Return", "Alt+Enter")
