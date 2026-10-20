"""The Properties dialog: facts of one or many items and the read-only metadata of audio, comic and video files."""
import os
import sys
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
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["General", "ComicInfo", "Tags"]
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


# the Tags tab -----------------------------------------------------------------------------------------------------
from dossier.core import filetags  # noqa: E402
from dossier.core.filetags import Tags, read_tags, write_tags  # noqa: E402

needs_streams = pytest.mark.skipif(not filetags.can_hold_tags(os.getcwd()) if False else sys.platform != "win32",
                                   reason="real tags need NTFS streams (Windows) or attributes")


def _tagged(win_left, name="x.txt", **kw):
    p = win_left / name
    p.write_text("x")
    if kw:
        write_tags(str(p), Tags(**kw))
    return p


@needs_streams
def test_gather_reads_the_tags_of_every_local_item(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("1")
    b.write_text("2")
    if not filetags.can_hold_tags(str(a)):
        pytest.skip("no streams here")
    write_tags(str(a), Tags(tags=["x"], rating=2))
    g = gather(fs, [str(a)])
    assert g.tags[str(a)].tags == ["x"] and g.tags_can_write and not g.tags_reason
    g2 = gather(fs, [str(a), str(b)])
    assert set(g2.tags) == {str(a), str(b)} and g2.paths == [str(a), str(b)]


def test_gather_says_why_there_are_no_tags_for_a_drive_that_cannot_hold_them(tmp_path, monkeypatch):
    (tmp_path / "a").write_text("1")
    monkeypatch.setattr(filetags, "can_hold_tags", lambda p, backend=None: False)
    g = gather(fs, [str(tmp_path / "a")])
    assert not g.tags_can_write and "cannot store tags" in g.tags_reason


from dossier.gui.properties import PropertiesDialog, split_tags  # noqa: E402


def test_typed_tags_are_split_on_commas_and_semicolons_and_cleaned():
    assert split_tags("Holiday; 2019, holiday ,, Family") == ["Holiday", "2019", "Family"]


@needs_streams
def test_the_tags_tab_for_one_file_only_asks_for_what_was_changed(tmp_path, app):
    p = tmp_path / "a.txt"
    p.write_text("x")
    if not filetags.can_hold_tags(str(p)):
        pytest.skip("no streams here")
    write_tags(str(p), Tags(tags=["a", "b"], rating=3, label="red", note="hi"))
    dlg = PropertiesDialog(None, gather(fs, [str(p)]), known_tags=["old", "a"])
    assert "Tags" in [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] and dlg.tag_edit.text() == "a, b"
    assert dlg.tag_change().is_empty()
    dlg.tag_edit.setText("a, b, c")
    dlg.rating.setCurrentIndex(dlg.rating.findData(5))
    dlg._pick("old")
    c = dlg.tag_change()
    assert c.replace == ["a", "b", "c", "old"] and c.rating == 5 and c.label is None and c.note is None


@needs_streams
def test_the_tags_tab_for_several_files_adds_and_removes_and_leaves_the_rest(tmp_path, app):
    paths = []
    for n in ("a", "b"):
        p = tmp_path / n
        p.write_text(n)
        paths.append(str(p))
    if not filetags.can_hold_tags(paths[0]):
        pytest.skip("no streams here")
    write_tags(paths[0], Tags(tags=["both", "only-a"]))
    write_tags(paths[1], Tags(tags=["both"]))
    dlg = PropertiesDialog(None, gather(fs, paths))
    dlg.add_edit.setText("new")
    dlg.remove_edit.setText("both")
    c = dlg.tag_change()
    assert c.add == ["new"] and c.remove == ["both"] and c.rating is None and c.label is None and c.replace is None


def test_a_drive_that_cannot_hold_tags_gets_a_read_only_tab_with_the_reason(tmp_path, app, monkeypatch):
    (tmp_path / "a").write_text("1")
    monkeypatch.setattr(filetags, "can_hold_tags", lambda p, backend=None: False)
    dlg = PropertiesDialog(None, gather(fs, [str(tmp_path / "a")]))
    assert not dlg.tag_edit.isEnabled() and not dlg.save_button.isVisibleTo(dlg) and dlg.tag_change().is_empty()


@needs_streams
def test_saving_from_the_window_writes_the_tags_and_remembers_them_for_the_pick_list(world, monkeypatch):
    win, d, left, *_ = world
    p = _tagged(left, "pic.jpg")
    if not filetags.can_hold_tags(str(p)):
        pytest.skip("no streams here")
    win.left.refresh()
    win.select_all()

    def edit(self, dlg):
        dlg.tag_edit.setText("holiday, 2019")
        dlg.rating.setCurrentIndex(dlg.rating.findData(4))
        dlg._save_tags()

    monkeypatch.setattr(type(win), "_show_properties_dialog", edit)
    win.show_properties()
    pump(win, lambda: read_tags(str(p)).tags == ["holiday", "2019"])
    assert read_tags(str(p)).rating == 4 and {"holiday", "2019"} <= win._known_tags
    pump(win, lambda: "Tags saved on 1 item" in win.status.text())
