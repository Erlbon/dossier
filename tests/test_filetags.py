"""Tags kept on the file itself: the record, the logic with a fake backend, and the real NTFS stream where there is one."""
import hashlib
import json
import os
import stat
import sys

import pytest

from dossier.core import filetags
from dossier.core.filetags import (CannotHoldTags, StreamBackend, Tags, XattrBackend, can_hold_tags, clean_tags, edit_tags,
                                   from_bytes, read_tags, to_bytes, write_tags)


class FakeBackend:
    """A file system that keeps one blob per path (and can be told it has no room for tags)."""

    def __init__(self, holds=True):
        self.blobs, self.holds = {}, holds

    def can_hold(self, path):
        return self.holds

    def read(self, path):
        return self.blobs.get(path)

    def write(self, path, data):
        self.blobs[path] = data

    def remove(self, path):
        self.blobs.pop(path, None)


@pytest.fixture
def f(tmp_path):
    p = tmp_path / "photo.jpg"
    p.write_bytes(b"picture")
    return str(p)


def test_the_record_round_trips_and_is_cleaned():
    t = Tags(tags=["Holiday", "holiday", " 2019 ", "a,b", ""], rating=9, label="  green  ", note="line one")
    back = from_bytes(to_bytes(t))
    assert back.tags == ["Holiday", "2019", "a b"] and back.rating == 5 and back.label == "green" and back.note == "line one"
    assert json.loads(to_bytes(Tags(tags=["x"])))["v"] == 1
    assert Tags().is_empty() and not Tags(rating=1).is_empty()
    assert back.has("HOLIDAY") and not back.has("2020")


def test_unknown_keys_survive_a_rewrite_so_a_newer_version_loses_nothing():
    blob = json.dumps({"v": 2, "tags": ["a"], "colour_space": "srgb", "people": ["Ann"]}).encode()
    t = from_bytes(blob)
    assert t.extra == {"colour_space": "srgb", "people": ["Ann"]}
    again = json.loads(to_bytes(t))
    assert again["colour_space"] == "srgb" and again["people"] == ["Ann"] and again["tags"] == ["a"]


@pytest.mark.parametrize("junk", [b"", b"not json", b"[1, 2]", b"\xff\xfe\x00", b'{"tags": "x", "rating": "high", "label": 3}'])
def test_damaged_or_foreign_data_gives_empty_tags_not_an_error(junk):
    t = from_bytes(junk)
    assert t.tags == [] and t.rating == 0 and t.label == ""


def test_limits_hold():
    assert len(clean_tags([f"t{i}" for i in range(500)])) == filetags.MAX_TAGS
    assert len(clean_tags(["x" * 500])[0]) == filetags.MAX_TAG_LENGTH


def test_write_read_edit_and_clear_with_a_fake_backend(f):
    b = FakeBackend()
    assert read_tags(f, b).is_empty()
    write_tags(f, Tags(tags=["a", "b"], rating=4, note="n"), b)
    assert read_tags(f, b).tags == ["a", "b"] and read_tags(f, b).rating == 4
    saved = edit_tags(f, add=["C", "a"], remove=["B"], backend=b)
    assert saved.tags == ["a", "C"] and read_tags(f, b).rating == 4 and read_tags(f, b).note == "n"
    write_tags(f, Tags(), b)
    assert f not in b.blobs                                       # an empty record leaves nothing behind


def test_a_drive_that_cannot_hold_tags_says_so_before_trying(f):
    b = FakeBackend(holds=False)
    assert not can_hold_tags(f, b)
    with pytest.raises(CannotHoldTags):
        write_tags(f, Tags(tags=["a"]), b)
    assert b.blobs == {} and read_tags(f, b).is_empty()


def test_a_read_only_file_is_tagged_and_put_back_with_its_time_unchanged(f):
    os.utime(f, (1_600_000_000, 1_600_000_000))
    os.chmod(f, stat.S_IREAD)
    before = os.stat(f)
    try:
        write_tags(f, Tags(tags=["x"]), FakeBackend())
        after = os.stat(f)
        assert not after.st_mode & stat.S_IWRITE and after.st_mtime_ns == before.st_mtime_ns
    finally:
        os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


# the real thing ---------------------------------------------------------------------------------------------------
windows = pytest.mark.skipif(sys.platform != "win32", reason="NTFS streams are Windows only")


@windows
def test_a_real_stream_holds_the_tags_and_leaves_the_file_exactly_as_it_was(f):
    b = StreamBackend()
    if not can_hold_tags(f, b):
        pytest.skip("the temp folder is not on a volume with streams")
    os.utime(f, (1_600_000_000, 1_600_000_000))
    digest = hashlib.sha256(open(f, "rb").read()).hexdigest()
    size, mtime = os.stat(f).st_size, os.stat(f).st_mtime_ns
    write_tags(f, Tags(tags=["holiday", "2019"], rating=3, label="green", note="Ålesund"), b)
    back = read_tags(f, b)
    assert back.tags == ["holiday", "2019"] and back.rating == 3 and back.note == "Ålesund"
    assert hashlib.sha256(open(f, "rb").read()).hexdigest() == digest          # the content is untouched
    assert os.stat(f).st_size == size and os.stat(f).st_mtime_ns == mtime       # so are its size and modified time
    assert sorted(os.listdir(os.path.dirname(f))) == ["photo.jpg"]              # no second file anywhere
    write_tags(f, Tags(), b)
    assert read_tags(f, b).is_empty()


@windows
def test_a_folder_can_be_tagged_and_a_real_read_only_file_too(tmp_path):
    b = StreamBackend()
    if not can_hold_tags(str(tmp_path), b):
        pytest.skip("the temp folder is not on a volume with streams")
    d = tmp_path / "album"
    d.mkdir()
    write_tags(str(d), Tags(tags=["music"]), b)
    assert read_tags(str(d), b).tags == ["music"]
    ro = tmp_path / "locked.txt"
    ro.write_text("x")
    os.chmod(ro, stat.S_IREAD)
    try:
        write_tags(str(ro), Tags(tags=["locked"]), b)
        assert read_tags(str(ro), b).tags == ["locked"] and not os.stat(ro).st_mode & stat.S_IWRITE
    finally:
        os.chmod(ro, stat.S_IREAD | stat.S_IWRITE)


@windows
def test_a_missing_file_reads_as_no_tags_and_a_copy_by_the_system_keeps_the_stream(tmp_path, f):
    b = StreamBackend()
    if not can_hold_tags(f, b):
        pytest.skip("the temp folder is not on a volume with streams")
    assert read_tags(str(tmp_path / "gone.txt"), b).is_empty()
    write_tags(f, Tags(tags=["kept"]), b)
    import shutil
    copy = str(tmp_path / "copy.jpg")
    os.system(f'copy /Y "{f}" "{copy}" >nul')                      # what Explorer and cmd do: copies the streams too
    assert read_tags(copy, b).tags == ["kept"]
    shutil.copyfile(f, str(tmp_path / "py.jpg"))
    assert read_tags(str(tmp_path / "py.jpg"), b).is_empty()       # Python's own copy drops them: Dossier must copy them itself


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="extended attributes are Linux only")
def test_xattr_backend_keeps_the_record_and_the_names_other_tools_read(f):
    b = XattrBackend()
    if not b.can_hold(f):
        pytest.skip("the temp folder cannot hold extended attributes")
    write_tags(f, Tags(tags=["a", "b"], rating=3), b)
    assert os.getxattr(f, filetags.XDG_TAGS) == b"a,b" and os.getxattr(f, filetags.BALOO_RATING) == b"6"
    os.removexattr(f, filetags.XATTR)
    assert read_tags(f, b).tags == ["a", "b"]                       # the freedesktop names alone are read as tags


def test_copy_tags_carries_them_and_says_when_it_could_not(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("a", "b", "c"))
    for p in (a, b, c):
        open(p, "w").write("x")
    src = FakeBackend()
    assert filetags.copy_tags(a, b, src) == "none"                    # nothing to carry
    write_tags(a, Tags(tags=["x"], rating=2), src)
    assert filetags.copy_tags(a, b, src) == "copied" and read_tags(b, src).tags == ["x"] and read_tags(b, src).rating == 2
    assert filetags.copy_tags(a, c, src, FakeBackend(holds=False)) == "lost"      # a drive without room for tags: no error


@windows
def test_copy_tags_repairs_what_a_plain_python_copy_drops(tmp_path, f):
    import shutil
    if not can_hold_tags(f):
        pytest.skip("the temp folder is not on a volume with streams")
    write_tags(f, Tags(tags=["kept"], rating=5))
    dst = str(tmp_path / "py.jpg")
    shutil.copyfile(f, dst)
    assert read_tags(dst).is_empty()
    assert filetags.copy_tags(f, dst) == "copied" and read_tags(dst).tags == ["kept"] and read_tags(dst).rating == 5
