"""dossier tag: show and change the tags inside mp3 and cbz files from the command line."""
import os

import pytest

pytest.importorskip("mutagen")

from tests.test_cli import bin_dir, run, run_json  # noqa: E402,F401
from tests.test_metawrite import easy, make_cbz, make_mp3  # noqa: E402


def test_tag_shows_what_the_files_carry(tmp_path, capsys):
    path = make_mp3(tmp_path / "a.mp3", title="Song", artist="Band")
    code, out, _err = run(capsys, "tag", path)
    assert code == 0 and "Title: Song" in out and "Artist: Band" in out and "Genre" not in out
    code, doc, _err = run_json(capsys, "tag", path)
    assert doc["results"][0]["tags"]["title"] == "Song"


def test_tag_previews_then_changes_and_the_old_file_goes_to_the_bin(tmp_path, capsys, bin_dir):
    path = make_mp3(tmp_path / "a.mp3", title="Old")
    code, doc, _err = run_json(capsys, "tag", path, "--set", "title=New title", "--set", "year=2019", "--set", "track=3/12", "--dry-run")
    assert code == 0 and doc["dry_run"] and doc["files"] == 1 and easy(path)["title"] == ["Old"]
    changes = {c["key"]: (c["old"], c["new"]) for c in doc["results"][0]["changes"]}
    assert changes == {"title": ("Old", "New title"), "date": ("", "2019"), "tracknumber": ("", "3/12")}      # year and track are aliases
    code, doc, _err = run_json(capsys, "tag", path, "--set", "title=New title", "--set", "year=2019", "--set", "track=3/12")
    assert code == 0 and doc["done"] == 1
    assert (easy(path)["title"], easy(path)["date"], easy(path)["tracknumber"]) == (["New title"], ["2019"], ["3/12"])
    assert len(os.listdir(bin_dir)) == 1                                                                     # the old file, in the bin
    run_json(capsys, "tag", path, "--clear", "year")
    assert "date" not in easy(path)


def test_tag_changes_a_comic(tmp_path, capsys, bin_dir):
    path = make_cbz(tmp_path / "a.cbz")
    code, doc, _err = run_json(capsys, "tag", path, "--set", "series=Fresh Series", "--set", "Writer=Someone Else", "--set", "cover-artist=Cover Person")
    assert code == 0 and doc["done"] == 1
    code, out, _err = run(capsys, "tag", path)
    assert "Series: Fresh Series" in out and "Writer: Someone Else" in out and "Cover artist: Cover Person" in out


def test_tag_refuses_nonsense_and_names_what_could_not_be_changed(tmp_path, capsys):
    mp3 = make_mp3(tmp_path / "a.mp3", title="T")
    cbz = make_cbz(tmp_path / "b.cbz")
    code, _out, err = run(capsys, "tag", mp3, cbz, "--set", "title=x")
    assert code == 2 and "one kind" in err
    code, _out, err = run(capsys, "tag", mp3, "--set", "nonsense=x")
    assert code == 2 and "no field" in err
    code, _out, err = run(capsys, "tag", mp3, "--set", "title")
    assert code == 2 and "KEY=VALUE" in err or "FIELD=VALUE" in err or "needs" in err
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not audio")
    code, _out, err = run(capsys, "tag", str(broken), "--set", "title=x")
    assert code == 1 and "broken.mp3" in err
    code, _out, err = run(capsys, "tag", str(tmp_path / "a.txt"))
    assert code == 2


def test_fields_lists_both_kinds(capsys):
    code, out, _err = run(capsys, "tag", "--fields")
    assert code == 0 and "title" in out and "Series" in out and "tracknumber" in out
