"""The metadata columns (core): which values come out of a reader's result, which files get opened, and the cache."""
import os
import zipfile
from dataclasses import dataclass

import pytest

pytest.importorskip("redactor_common")

from redactor_common.core.meta_fields import Field, MetaResult  # noqa: E402
from redactor_common.core.meta_video import parse_probe  # noqa: E402

from dossier.core import metacolumns as mc  # noqa: E402
from dossier.core.columns import DEFAULT_HIDDEN, KEYS, LEGACY_KEYS, META_KEYS, newly_hidden  # noqa: E402
from dossier.core.layouts import Layout, LayoutStore  # noqa: E402


def result(kind, **fields):
    return MetaResult(kind, [Field(k.replace("__", "."), k, v) for k, v in fields.items()])


def test_audio_values_come_from_the_tags_and_a_track_of_3_of_12_is_3():
    r = result("audio", title="Song", artist="Band", album="LP", track="03/12", date="1999-05-01", genre="Rock", length="3:07",
               bitrate="320 kbps (CBR)", publisher="Label")
    v = mc.values_from("audio", r)
    assert v == {"m_title": "Song", "m_artist": "Band", "m_album": "LP", "m_track": "3", "m_year": "1999", "m_genre": "Rock",
                 "m_length": "3:07", "m_bitrate": "320 kbps (CBR)".replace(" kbps", ""), "m_publisher": "Label"}


def test_comic_values_come_from_comicinfo():
    r = result("comic", title="Issue", series="Saga", number="12", writer="B. Vaughan", publisher="Image", date="2014-03", pages="22",
               genre="Fantasy")
    v = mc.values_from("comic", r)
    assert v["m_series"] == "Saga" and v["m_number"] == "12" and v["m_writer"] == "B. Vaughan" and v["m_year"] == "2014"
    assert v["m_pages"] == "22" and "m_artist" not in v


def test_video_values_come_from_the_first_video_track_and_all_audio_languages():
    probe = {"format": {"format_name": "matroska", "duration": "5400.5", "bit_rate": "4500000", "tags": {"title": "Film"}},
             "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080, "avg_frame_rate": "24/1"},
                         {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "eng"}},
                         {"codec_type": "audio", "codec_name": "ac3", "channels": 6, "tags": {"language": "nor"}},
                         {"codec_type": "audio", "codec_name": "ac3", "channels": 6, "tags": {"language": "eng"}}]}
    v = mc.values_from("video", parse_probe(probe))
    assert v["m_resolution"] == "1920x1080" and v["m_length"] == "1:30:00" and v["m_title"] == "Film"
    assert v["m_languages"] == "eng, nor" and v["m_bitrate"] == "4500" and "hevc" in v["m_codec"].lower()


def test_nothing_is_invented_for_a_field_the_file_does_not_have():
    assert mc.values_from("audio", MetaResult("audio")) == {}
    assert mc.values_from("audio", result("audio", date="x")) == {}                  # not a year


def test_only_the_kinds_the_visible_columns_need_are_opened():
    assert mc.kinds_needed(["m_artist"]) == {"audio"}
    assert mc.kinds_needed(["m_series", "m_pages"]) == {"comic"}
    assert mc.kinds_needed(["m_resolution"]) == {"video"} and mc.kinds_needed(["m_title"]) == {"audio", "comic", "video"}
    assert mc.kinds_needed([]) == set() and mc.kinds_needed(["size"]) == set()
    assert set(mc.KINDS_OF) == set(META_KEYS)                                          # every column says who can fill it


def test_a_real_cbz_is_read_in_process_and_a_damaged_or_foreign_file_gives_nothing(tmp_path):
    cbz = tmp_path / "Saga 012.cbz"
    xml = "<ComicInfo><Series>Saga</Series><Number>12</Number><Writer>Vaughan</Writer><Year>2014</Year></ComicInfo>"
    with zipfile.ZipFile(cbz, "w") as z:
        z.writestr("ComicInfo.xml", xml)
        z.writestr("p1.jpg", b"x")
    v = mc.read_values(str(cbz), {"comic"})
    assert v["m_series"] == "Saga" and v["m_number"] == "12" and v["m_year"] == "2014" and v["m_pages"] == "1"
    assert mc.read_values(str(cbz), {"audio"}) == {}                                    # not a kind that was asked for
    (tmp_path / "bad.cbz").write_bytes(b"not a zip")
    assert mc.read_values(str(tmp_path / "bad.cbz"), {"comic"}) == {}
    assert mc.read_values(str(tmp_path / "notes.txt"), {"audio", "comic", "video"}) == {}
    assert mc.read_values(str(tmp_path / "missing.cbz"), {"comic"}) == {}


def test_a_reader_that_raises_is_an_empty_row_not_an_error(monkeypatch):
    def boom(path, kind):
        raise RuntimeError("bad file")
    monkeypatch.setattr(mc, "read_metadata", boom)
    assert mc.read_values("C:/x/a.mp3", {"audio"}) == {}


def test_the_cache_keeps_the_newest_and_a_changed_file_is_a_new_key():
    c = mc.MetaCache(limit=2)
    k1, k2, k3 = (mc.MetaCache.key(f"f{i}", 10, 100.9) for i in range(3))
    c.put(k1, {"a": "1"})
    c.put(k2, {"a": "2"})
    assert c.get(k1) == {"a": "1"}                                                      # reading it makes it the newest
    c.put(k3, {"a": "3"})
    assert c.get(k2) is None and c.get(k1) == {"a": "1"} and len(c) == 2
    assert mc.MetaCache.key("f", 10, 100.2) == mc.MetaCache.key("f", 10, 100.9)       # the time is compared to the second
    assert mc.MetaCache.key("f", 10, 100) != mc.MetaCache.key("f", 11, 100)
    c.clear()
    assert len(c) == 0


@dataclass
class E:
    path: str
    size: int = 1
    mtime: float = 1.0


def test_read_many_reads_the_wanted_kinds_once_hands_over_in_batches_and_uses_the_cache():
    entries = [E(f"C:/m/{i}.mp3") for i in range(7)] + [E("C:/m/a.cbz"), E("C:/m/readme.txt")]
    calls, batches = [], []

    def reader(path, kinds):
        calls.append(path)
        return {"m_artist": os.path.basename(path)}
    cache = mc.MetaCache()
    mc.read_many(entries, {"audio"}, cache, batches.append, reader=reader, batch=3)
    assert sorted(calls) == sorted(e.path for e in entries[:7])                         # only audio files were opened
    assert [len(b) for b in batches] == [3, 3, 1] and sum(len(b) for b in batches) == 7
    calls.clear()
    batches.clear()
    mc.read_many(entries, {"audio"}, cache, batches.append, reader=reader)
    assert calls == [] and len(batches) == 1 and len(batches[0]) == 7                   # all from the cache, in one go
    entries[0] = E("C:/m/0.mp3", size=99)                                               # this file changed
    mc.read_many(entries, {"audio"}, cache, batches.append, reader=reader)
    assert calls == ["C:/m/0.mp3"]


def test_read_many_stops_when_cancelled():
    entries = [E(f"C:/m/{i}.mp3") for i in range(30)]
    seen, calls = [], []

    def reader(path, kinds):
        calls.append(path)
        return {"m_artist": "x"}
    mc.read_many(entries, {"audio"}, mc.MetaCache(), seen.append, reader=reader, batch=5, workers=1,
                 cancelled=lambda: len(seen) >= 1)
    assert 0 < len(seen) <= 2 and sum(len(b) for b in seen) < 30


def test_a_column_added_later_starts_hidden_in_old_choices_and_old_layouts():
    assert newly_hidden(LEGACY_KEYS) == frozenset(META_KEYS)
    assert newly_hidden(KEYS) == frozenset()
    assert set(META_KEYS) <= DEFAULT_HIDDEN
    old = '[{"path": "%s", "scope": "only", "hidden": ["size"], "order": ["name"], "mode": "details", "size": 128, "sort": "name", "desc": false}]' \
          % os.path.join(os.path.abspath(os.sep), "work").replace("\\", "/")
    rule = LayoutStore.from_json(old).rules()[0]
    assert set(META_KEYS) <= set(rule.layout.cleaned().hidden) and "size" in rule.layout.cleaned().hidden
    new = Layout(["size"], ["name"]).cleaned()                                          # one made now: what is not hidden is shown
    assert "m_artist" not in new.hidden
