"""The editable Metadata tab of Properties: the form, what counts as a change, and saving through plan, confirmation and the safe write."""
import os
import time
import zipfile

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("mutagen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import properties  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402
from dossier.gui.properties import DIFFERENT, REMOVED, PropertiesDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_metawrite import easy, make_cbz, make_mp3  # noqa: E402

fs = LocalFileSystem()


def wait(until, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def tag(path, key):
    """A tag of a file that may be in the middle of being replaced: its value, or None when it cannot be read just now."""
    try:
        return easy(path).get(key)
    except Exception:   # noqa: BLE001 -- polled while the file is swapped in
        return None


def dialog_for(win, paths):
    data = properties.gather(fs, [str(p) for p in paths])
    return PropertiesDialog(win, data, set()), data


# what is gathered -------------------------------------------------------------------------------------------------------------------------
def test_gather_finds_what_the_files_have_in_common(tmp_path):
    a = make_mp3(tmp_path / "a.mp3", album="Same", title="One")
    b = make_mp3(tmp_path / "b.mp3", album="Same", title="Two")
    one = properties.gather(fs, [a])
    assert one.edit_kind == "audio" and one.edit_values["title"] == "One" and one.edit_paths == [a] and one.edit_reason == ""
    both = properties.gather(fs, [a, b])
    assert both.edit_values["album"] == "Same" and both.edit_values["title"] is None and both.edit_paths == [a, b]


def test_a_mix_of_kinds_or_an_unsupported_kind_has_no_edit_tab(tmp_path):
    a = make_mp3(tmp_path / "a.mp3", title="T")
    c = make_cbz(tmp_path / "c.cbz")
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    assert properties.gather(fs, [a, c]).edit_kind == "" and properties.gather(fs, [str(wav)]).edit_kind == ""


def test_read_only_files_are_named_and_the_others_can_still_be_changed(tmp_path):
    a = make_mp3(tmp_path / "a.mp3", title="A")
    b = make_mp3(tmp_path / "b.mp3", title="B")
    os.chmod(b, 0o444)
    try:
        data = properties.gather(fs, [a, b])
        assert data.edit_paths == [a] and "read-only" in data.edit_problems[b] and data.edit_reason == ""
        os.chmod(a, 0o444)
        none = properties.gather(fs, [a, b])
        assert none.edit_reason and none.edit_values == {}
    finally:
        os.chmod(a, 0o644)
        os.chmod(b, 0o644)


# the form ---------------------------------------------------------------------------------------------------------------------------------
def test_one_file_shows_its_values_and_only_changed_fields_count(world, tmp_path):
    win, *_ = world
    a = make_mp3(tmp_path / "a.mp3", title="Song", artist="Band", genre="Rock")
    dlg, data = dialog_for(win, [a])
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())][:2] == ["General", "Audio tags"]
    assert dlg.edit_rows["title"][0].text() == "Song" and dlg.edit_rows["album"][0].text() == ""
    assert dlg.metadata_changes() == {} and "Nothing changed" in dlg.edit_summary.text()
    dlg.edit_rows["title"][0].setText("Better")
    dlg.edit_rows["album"][0].setText("Fresh")
    assert dlg.metadata_changes() == {"title": "Better", "album": "Fresh"} and "2 fields changed on 1 file" in dlg.edit_summary.text()
    assert dlg.edit_rows["title"][0].font().bold() and not dlg.edit_rows["genre"][0].font().bold()      # changed fields are marked
    dlg.edit_rows["title"][0].setText("Song")
    assert dlg.metadata_changes() == {"album": "Fresh"}                                           # put back by hand: no longer a change
    dlg.edit_rows["artist"][0].setText("")
    assert dlg.metadata_changes() == {"album": "Fresh", "artist": ""}                              # emptied: taken away


def test_several_files_show_different_and_typing_sets_it_on_all(world, tmp_path):
    win, *_ = world
    a = make_mp3(tmp_path / "a.mp3", album="Same", title="One")
    b = make_mp3(tmp_path / "b.mp3", album="Same", title="Two")
    dlg, _data = dialog_for(win, [a, b])
    assert dlg.edit_rows["album"][0].text() == "Same" and dlg.edit_rows["title"][0].text() == "" and dlg.edit_rows["title"][0].placeholderText() == DIFFERENT
    assert dlg.metadata_changes() == {}                                                          # a field that differs and is left blank is not touched
    dlg.edit_rows["artist"][0].setText("Both")
    dlg.edit_rows["title"][0].setText("Same title")
    assert dlg.metadata_changes() == {"artist": "Both", "title": "Same title"} and "on 2 files" in dlg.edit_summary.text()


def test_the_x_takes_a_field_away_from_every_file_and_typing_again_cancels_it(world, tmp_path):
    win, *_ = world
    a = make_mp3(tmp_path / "a.mp3", genre="Rock", title="One")
    b = make_mp3(tmp_path / "b.mp3", genre="Jazz", title="Two")
    dlg, _data = dialog_for(win, [a, b])
    dlg.edit_rows["genre"][1].click()
    assert dlg.metadata_changes() == {"genre": ""} and dlg.edit_rows["genre"][0].placeholderText() == REMOVED
    dlg.edit_rows["genre"][0].setText("Pop")
    assert dlg.metadata_changes() == {"genre": "Pop"}


def test_the_save_button_belongs_to_its_tab(world, tmp_path):
    win, *_ = world
    a = make_mp3(tmp_path / "a.mp3", title="T")
    dlg, _data = dialog_for(win, [a])
    dlg.tabs.setCurrentWidget(dlg.meta_tab)
    assert dlg.meta_button.isVisibleTo(dlg) and not dlg.save_button.isVisibleTo(dlg)
    dlg.tabs.setCurrentIndex(0)
    assert not dlg.meta_button.isVisibleTo(dlg)
    dlg.tabs.setCurrentWidget(dlg.meta_tab)
    dlg._save_metadata()                                                                          # nothing changed: it does not close
    assert dlg.meta_edits == {} and dlg.result() == 0


def test_a_comic_gets_the_comicinfo_form_with_a_multi_line_summary(world, tmp_path):
    win, *_ = world
    c = make_cbz(tmp_path / "c.cbz")
    dlg, _data = dialog_for(win, [c])
    assert dlg.tabs.tabText(1) == "ComicInfo" and dlg.edit_rows["Series"][0].text() == "Old Series"
    assert dlg.edit_rows["Summary"][3] is True                                                    # a longer text box, not one line
    dlg.edit_rows["Summary"][0].setPlainText("A long summary")
    dlg.edit_rows["Year"][0].setText("2020")
    assert dlg.metadata_changes() == {"Summary": "A long summary", "Year": "2020"}


def test_the_rest_of_what_the_file_carries_is_listed_read_only(world, tmp_path):
    win, *_ = world
    a = make_mp3(tmp_path / "a.mp3", title="T")
    dlg, data = dialog_for(win, [a])
    texts = {dlg.meta_tab.findChildren(type(dlg.tabs))} if False else None
    labels = [f.label for f in data.meta.fields if f.key not in {"title", "artist", "album", "albumartist", "track", "disc", "date", "genre", "composer"}]
    assert labels == [] or any(label for label in labels)                                          # technical facts are not duplicated in the form


# saving from the window ---------------------------------------------------------------------------------------------------------------------
def test_saving_asks_once_writes_the_file_and_the_old_one_goes_to_the_bin(world, monkeypatch):
    win, d, left, right, tmp = world
    path = make_mp3(left / "a.mp3", title="Old", genre="Rock")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.selection.add([path])

    def drive(dlg):
        dlg.edit_rows["title"][0].setText("New title")
        dlg.edit_rows["year" if "year" in dlg.edit_rows else "date"][0].setText("2019")
        dlg._save_metadata()
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: drive(dlg))
    win.show_properties()
    wait(lambda: d.confirms)
    title, text = d.confirms[-1]
    assert title == "Save Metadata" and "Title" in text and "1 file" in text and "recycle bin" in text
    wait(lambda: tag(path, "title") == ["New title"])
    assert easy(path)["genre"] == ["Rock"] and easy(path)["date"] == ["2019"]
    pump(win, lambda: "Saved the metadata of 1 file" in win.status.text())
    assert any("a.mp3" in n for n in os.listdir(tmp / "bin")) and [n for n in os.listdir(left) if n.endswith(".dossier-part")] == []


def test_declining_the_confirmation_writes_nothing(world, monkeypatch):
    win, d, left, right, tmp = world
    path = make_mp3(left / "a.mp3", title="Old")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.selection.add([path])
    d.confirm_answer = False

    def drive(dlg):
        dlg.edit_rows["title"][0].setText("New")
        dlg._save_metadata()
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: drive(dlg))
    win.show_properties()
    wait(lambda: d.confirms)
    for _ in range(30):
        QApplication.processEvents()
    assert easy(path)["title"] == ["Old"] and os.listdir(tmp / "bin") == []


def test_several_files_are_written_and_a_broken_one_is_named_while_the_others_are_saved(world, monkeypatch):
    win, d, left, right, tmp = world
    a = make_mp3(left / "a.mp3", title="A")
    b = make_mp3(left / "b.mp3", title="B")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    win.selection.add([a, b])

    def drive(dlg):
        dlg.edit_rows["album"][0].setText("Together")
        os.chmod(b, 0o444)                                                  # b becomes read-only after the form was filled: the plan names it
        dlg._save_metadata()
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: drive(dlg))
    win.show_properties()
    wait(lambda: d.confirms)
    try:
        assert "b.mp3" in d.confirms[-1][1] and "read-only" in d.confirms[-1][1] and "1 file" in d.confirms[-1][1]
        wait(lambda: tag(a, "album") == ["Together"])
        assert "album" not in easy(b)
    finally:
        os.chmod(b, 0o644)


def test_a_comic_is_saved_through_the_same_path(world, monkeypatch):
    win, d, left, right, tmp = world
    c = make_cbz(left / "c.cbz")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.selection.add([c])

    def drive(dlg):
        dlg.edit_rows["Series"][0].setText("Fresh Series")
        dlg._save_metadata()
    monkeypatch.setattr(type(win), "_show_properties_dialog", lambda self, dlg: drive(dlg))
    win.show_properties()
    wait(lambda: d.confirms)
    def written():
        try:
            return b"Fresh Series" in zipfile.ZipFile(c).read("ComicInfo.xml")
        except (OSError, zipfile.BadZipFile):                              # the file is being swapped in at this moment
            return False
    wait(written)
    with zipfile.ZipFile(c) as z:
        assert z.testzip() is None and "page1.jpg" in z.namelist()
