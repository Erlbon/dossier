"""Writing metadata: mp3 and flac tags and the ComicInfo of a cbz. A change is planned first, written beside the file and put in place after a
read back, the old file goes to the bin, and what was not asked for is never touched."""
import os
import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

mutagen = pytest.importorskip("mutagen")

from mutagen.id3 import APIC, ID3, TXXX  # noqa: E402

from dossier.core import filetags, metawrite as mw  # noqa: E402
from dossier.core.progress import CancelToken, Cancelled  # noqa: E402


def make_mp3(path, **tags):
    """A tiny but real mp3 (silent frames of 128 kbit/s) with the given easy tags."""
    frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)
    with open(path, "wb") as f:
        f.write(frame * 12)
    if tags:
        easy = mutagen.File(str(path), easy=True)
        easy.add_tags()
        for key, value in tags.items():
            easy[key] = [value]
        easy.save()
    return str(path)


def make_flac(path, **tags):
    """A FLAC with only its STREAMINFO block: enough for the tag code, which never looks at the audio."""
    info = struct.pack(">HHBBBBBBBBBBBBBBBB", 4096, 4096, 0, 0, 0, 0, 0, 0x0A, 0xC4, 0x40, 0xF0, 0, 0, 0, 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"fLaC" + bytes([0x80, 0, 0, 34]) + info + bytes(34 - len(info)))
    if tags:
        flac = mutagen.File(str(path), easy=True)
        for key, value in tags.items():
            flac[key] = [value]
        flac.save()
    return str(path)


def easy(path):
    return mutagen.File(path, easy=True)


class Bin:
    """A recycle bin that only remembers what was sent to it (and deletes it, as a bin would take it away)."""

    def __init__(self):
        self.got = []

    def __call__(self, path):
        self.got.append(os.path.basename(path))
        os.remove(path)


# audio -------------------------------------------------------------------------------------------------------------------------------------
def test_planning_shows_old_and_new_and_writes_nothing(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="Old title", artist="Same")
    before = open(path, "rb").read()
    items = mw.plan([path], {"title": "New title", "artist": "Same", "album": "Fresh"})
    assert len(items) == 1 and items[0].writable
    changes = {c.key: (c.old, c.new) for c in items[0].changes}
    assert changes == {"title": ("Old title", "New title"), "album": ("", "Fresh")}          # artist is the same: no change
    assert open(path, "rb").read() == before and os.listdir(tmp_path) == ["a.mp3"]


def test_apply_writes_the_tags_keeps_the_rest_and_sends_the_old_file_to_the_bin(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="Old", genre="Rock")
    raw = ID3(path)                                                       # things the editor does not know: cover art and a custom frame
    raw.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=b"PNGDATA"))
    raw.add(TXXX(encoding=3, desc="MY_FRAME", text=["keep me"]))
    raw.save()
    bin_ = Bin()
    result = mw.apply(mw.plan([path], {"title": "New", "tracknumber": "3/12", "date": "2019"}), trasher=bin_)
    assert result.done == 1 and not result.failed
    e = easy(path)
    assert (e["title"], e["genre"], e["tracknumber"], e["date"]) == (["New"], ["Rock"], ["3/12"], ["2019"])
    kept = ID3(path)
    assert kept.getall("APIC")[0].data == b"PNGDATA" and kept.getall("TXXX")[0].text == ["keep me"]
    assert len(bin_.got) == 1 and os.listdir(tmp_path) == ["a.mp3"]            # the old file went to the bin; no leftovers


def test_an_empty_value_takes_a_field_away_and_a_file_without_tags_gets_them(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T", artist="A")
    mw.apply(mw.plan([path], {"artist": ""}))
    assert "artist" not in easy(path) and easy(path)["title"] == ["T"]
    bare = make_mp3(tmp_path / "bare.mp3")
    assert mw.read_values(bare)["title"] == ""
    mw.apply(mw.plan([bare], {"title": "Now tagged"}))
    assert easy(bare)["title"] == ["Now tagged"]


def test_flac_tags_are_written_too(tmp_path):
    path = make_flac(tmp_path / "a.flac", title="Old")
    result = mw.apply(mw.plan([path], {"title": "New", "artist": "Band", "tracknumber": "2"}))
    assert result.done == 1
    f = easy(path)
    assert (f["title"], f["artist"], f["tracknumber"]) == (["New"], ["Band"], ["2"])


def test_a_bad_value_is_a_problem_in_the_plan_and_the_file_is_left_alone(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="Keep")
    before = open(path, "rb").read()
    item = mw.plan([path], {"date": "x" * (mw.MAX_VALUE + 1)})[0]
    assert "too long" in item.problem and not item.writable
    item = mw.plan([path], {"nonsense": "x"})[0]
    assert "no field nonsense" in item.problem
    assert mw.apply([item]).done == 0 and open(path, "rb").read() == before


def test_a_failed_write_leaves_the_original_and_no_leftovers(tmp_path, monkeypatch):
    path = make_mp3(tmp_path / "a.mp3", title="Keep")
    before = open(path, "rb").read()
    monkeypatch.setattr(mw.zipwrite, "swap_in", lambda *a: (_ for _ in ()).throw(PermissionError(13, "in use")))
    result = mw.apply(mw.plan([path], {"title": "New"}))
    assert result.done == 0 and result.failed and "in use" in result.failed[0][1]
    assert open(path, "rb").read() == before and os.listdir(tmp_path) == ["a.mp3"]


def test_one_bad_file_does_not_stop_the_others(tmp_path):
    good = make_mp3(tmp_path / "good.mp3", title="G")
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"this is not audio at all")
    other = make_mp3(tmp_path / "other.mp3", title="O")
    items = mw.plan([good, str(broken), other], {"album": "Set"})
    assert [bool(i.problem) for i in items] == [False, True, False] or items[1].changes == [] or items[1].problem
    result = mw.apply(items)
    assert easy(good)["album"] == ["Set"] and easy(other)["album"] == ["Set"]
    assert result.done == 2


def test_a_read_only_file_and_a_file_that_is_not_there_are_problems(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T")
    os.chmod(path, 0o444)
    try:
        assert "read-only" in mw.plan([path], {"title": "N"})[0].problem
    finally:
        os.chmod(path, 0o644)
    assert "not there" in mw.plan([str(tmp_path / "missing.mp3")], {"title": "N"})[0].problem
    assert "cannot be written yet" in mw.plan([str(tmp_path / "x.wav")], {"title": "N"})[0].problem
    assert "drive of this computer" in mw.plan(["zip://a.zip/x.mp3"], {"title": "N"})[0].problem


def test_the_rating_and_label_kept_on_the_file_follow_it(tmp_path):
    path = make_mp3(tmp_path / "a.mp3", title="T")
    if not filetags.can_hold_tags(path):
        pytest.skip("this drive cannot hold tags")
    filetags.write_tags(path, filetags.Tags(["keeper"], 4, "green"))
    mw.apply(mw.plan([path], {"title": "N"}))
    t = filetags.read_tags(path)
    assert (t.tags, t.rating, t.label) == (["keeper"], 4, "green")


def test_several_files_get_the_same_field_and_the_shared_values_are_found(tmp_path):
    a = make_mp3(tmp_path / "a.mp3", album="Same", title="One")
    b = make_mp3(tmp_path / "b.mp3", album="Same", title="Two")
    kind, values, problems = mw.common_values([a, b])
    assert kind == mw.AUDIO and values["album"] == "Same" and values["title"] is None and values["artist"] == "" and not problems
    mw.apply(mw.plan([a, b], {"artist": "Both"}))
    assert easy(a)["artist"] == easy(b)["artist"] == ["Both"] and easy(a)["title"] == ["One"] and easy(b)["title"] == ["Two"]
    assert mw.common_values([a, str(tmp_path / "x.cbz")]) == ("", {}, {})


def test_cancel_stops_before_the_next_file(tmp_path):
    a = make_mp3(tmp_path / "a.mp3", title="A")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        mw.apply(mw.plan([a], {"title": "B"}), cancel=token)
    assert easy(a)["title"] == ["A"] and os.listdir(tmp_path) == ["a.mp3"]


# comics ------------------------------------------------------------------------------------------------------------------------------------
COMIC_INFO = (b'<?xml version="1.0"?><ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Series>Old Series</Series>'
              b'<Number>1</Number><Writer>Someone</Writer><PageCount>3</PageCount><CustomThing>keep</CustomThing></ComicInfo>')


def make_cbz(path, info=COMIC_INFO, member="ComicInfo.xml"):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(3):
            z.writestr(f"page{n}.jpg", b"JPEG" + bytes([n]) * 50)
        if info is not None:
            z.writestr(member, info)
    return str(path)


def comic_root(path, member="ComicInfo.xml"):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(member))


def test_comicinfo_fields_change_and_everything_else_in_the_archive_stays(tmp_path):
    path = make_cbz(tmp_path / "a.cbz")
    bin_ = Bin()
    items = mw.plan([path], {"Series": "New Series", "Year": "2019", "Writer": ""})
    assert {c.key: (c.old, c.new) for c in items[0].changes} == {"Series": ("Old Series", "New Series"), "Year": ("", "2019"), "Writer": ("Someone", "")}
    assert mw.apply(items, trasher=bin_).done == 1
    root = comic_root(path)
    assert root.find("Series").text == "New Series" and root.find("Year").text == "2019" and root.find("Writer") is None
    assert root.find("Number").text == "1" and root.find("PageCount").text == "3" and root.find("CustomThing").text == "keep"   # unknown elements survive
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None and sorted(n for n in z.namelist() if n.endswith(".jpg")) == ["page0.jpg", "page1.jpg", "page2.jpg"]
        assert z.read("page1.jpg") == b"JPEG" + bytes([1]) * 50
    assert len(bin_.got) == 1 and os.listdir(tmp_path) == ["a.cbz"]


def test_new_elements_go_where_the_schema_puts_them(tmp_path):
    path = make_cbz(tmp_path / "a.cbz")
    mw.apply(mw.plan([path], {"Title": "T", "Publisher": "P", "Genre": "G", "Volume": "2"}))
    tags = [child.tag for child in comic_root(path)]
    assert tags.index("Title") < tags.index("Series") < tags.index("Number") < tags.index("Volume") < tags.index("Writer") < tags.index("Publisher") < tags.index("Genre")


def test_a_comic_without_comicinfo_gets_one_at_the_top(tmp_path):
    path = make_cbz(tmp_path / "a.cbz", info=None)
    assert mw.read_values(path)["Series"] == ""
    mw.apply(mw.plan([path], {"Series": "Fresh", "Number": "7"}))
    root = comic_root(path)
    assert (root.find("Series").text, root.find("Number").text) == ("Fresh", "7")
    with zipfile.ZipFile(path) as z:
        assert z.read("ComicInfo.xml").startswith(b"<?xml")


def test_an_existing_comicinfo_in_a_folder_is_changed_where_it_is(tmp_path):
    path = make_cbz(tmp_path / "a.cbz", member="meta/ComicInfo.xml")
    mw.apply(mw.plan([path], {"Series": "Deep"}))
    with zipfile.ZipFile(path) as z:
        assert [n for n in z.namelist() if n.lower().endswith("comicinfo.xml")] == ["meta/ComicInfo.xml"]
    assert comic_root(path, "meta/ComicInfo.xml").find("Series").text == "Deep"


def test_comic_values_are_checked(tmp_path):
    path = make_cbz(tmp_path / "a.cbz")
    for edits, text in (({"Year": "last year"}, "whole number"), ({"Month": "13"}, "1 to 12"), ({"Day": "40"}, "1 to 31"), ({"Manga": "maybe"}, "one of")):
        item = mw.plan([path], edits)[0]
        assert text in item.problem and not item.writable
    assert mw.plan([path], {"Manga": "YesAndRightToLeft", "Year": "2020"})[0].writable


def test_a_damaged_comicinfo_or_a_rar_is_left_alone(tmp_path):
    bad = make_cbz(tmp_path / "bad.cbz", info=b"<ComicInfo><Series>unclosed")
    before = open(bad, "rb").read()
    item = mw.plan([bad], {"Series": "X"})[0]
    assert "not valid XML" in item.problem and open(bad, "rb").read() == before
    notzip = tmp_path / "x.cbz"
    notzip.write_bytes(b"Rar!")
    assert "not a zip" in mw.plan([str(notzip)], {"Series": "X"})[0].problem
    assert "cannot be written yet" in mw.plan([str(tmp_path / "x.cbr")], {"Series": "X"})[0].problem


def test_an_unchanged_value_means_no_write(tmp_path):
    path = make_cbz(tmp_path / "a.cbz")
    before = os.path.getmtime(path)
    items = mw.plan([path], {"Series": "Old Series"})
    assert items[0].changes == [] and not items[0].writable
    assert mw.apply(items).done == 0 and os.path.getmtime(path) == before
