"""New files from pasted or dropped content, and staging items out of an archive for a drag to another program."""
import os
import tempfile
import time
import zipfile
from datetime import datetime

import pytest

from dossier.core import newfile, stage
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem
from dossier.core.zipfs import ZipFileSystem, archive_root

fs = LocalFileSystem()


def test_the_suggested_names():
    when = datetime(2026, 10, 24, 10, 30, 12)
    assert newfile.suggested_name(newfile.IMAGE, when) == "Pasted image 2026-10-24 10.30.12.png"
    assert newfile.suggested_name(newfile.TEXT, when) == "Pasted text 2026-10-24 10.30.12.txt"


def test_a_typed_name_gets_the_extension_it_lacks_and_bad_names_are_refused():
    assert newfile.clean_name("  notes ", newfile.TEXT) == "notes.txt"
    assert newfile.clean_name("shot.jpg", newfile.IMAGE) == "shot.jpg"
    assert newfile.clean_name("shot", newfile.IMAGE) == "shot.png"
    for bad in ("", "   ", "a/b.txt", ".."):
        with pytest.raises(ValueError):
            newfile.clean_name(bad, newfile.TEXT)


def test_a_file_is_made_and_a_taken_name_is_never_overwritten(tmp_path):
    first = newfile.write_new_file(fs, str(tmp_path), "note.txt", b"one")
    second = newfile.write_new_file(fs, str(tmp_path), "note.txt", b"two")
    third = newfile.write_new_file(fs, str(tmp_path), "note.txt", b"three")
    assert [os.path.basename(p) for p in (first, second, third)] == ["note.txt", "note (2).txt", "note (3).txt"]
    assert [open(p, "rb").read() for p in (first, second, third)] == [b"one", b"two", b"three"]


def test_a_failed_write_leaves_nothing(tmp_path):
    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            raise OSError("disk full")

    class BrokenFs(LocalFileSystem):
        def open_write(self, path, *, exclusive=False):
            super().open_write(path, exclusive=exclusive).close()          # the file exists now, empty
            return Broken()

    with pytest.raises(OSError):
        newfile.write_new_file(BrokenFs(), str(tmp_path), "x.txt", b"data")
    assert os.listdir(tmp_path) == []


# staging ------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def temp(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    os.makedirs(tmp_path / "tmp")
    return tmp_path / "tmp"


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readme.txt", "hello")
        z.writestr("docs/one.txt", "1" * 100)
        z.writestr("docs/deep/two.txt", "22")
    return str(path)


def test_items_of_an_archive_are_copied_out_in_order(temp, archive):
    zfs = ZipFileSystem()
    root = archive_root(archive)
    got = stage.stage(zfs, [root + "docs", root + "readme.txt"])
    assert [os.path.basename(p) for p in got] == ["docs", "readme.txt"]
    assert open(got[1]).read() == "hello" and open(os.path.join(got[0], "deep", "two.txt")).read() == "22"
    assert os.path.dirname(got[0]).startswith(stage.stage_root())


def test_two_items_with_one_name_do_not_overwrite_each_other(temp, archive):
    zfs = ZipFileSystem()
    root = archive_root(archive)
    got = stage.stage(zfs, [root + "docs/one.txt", root + "docs/one.txt"])
    assert [os.path.basename(p) for p in got] == ["one.txt", "one (2).txt"]


def test_more_than_the_limit_is_refused_while_copying(temp, archive):
    with pytest.raises(stage.TooBig):
        stage.stage(ZipFileSystem(), [archive_root(archive) + "docs"], limit=50)


def test_cancel_stops_staging(temp, archive):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        stage.stage(ZipFileSystem(), [archive_root(archive) + "readme.txt"], cancel=token)


def test_clean_up_removes_this_runs_folder_and_old_ones_only(temp, archive):
    stage.stage(ZipFileSystem(), [archive_root(archive) + "readme.txt"])
    other = temp / "dossier-drag-99999"
    other.mkdir()
    (other / "x").write_text("x")
    fresh = temp / "unrelated"
    fresh.mkdir()
    assert stage.clean_up(everything=True) == 1 and not os.path.exists(stage.stage_root()) and other.exists() and fresh.exists()
    old = time.time() - 3 * 24 * 3600
    os.utime(other, (old, old))
    os.utime(fresh, (old, old))
    assert stage.clean_up() == 1 and not other.exists() and fresh.exists()           # only dossier-drag folders, only old ones


def test_the_known_size_counts_files_only():
    from dossier.core.vfs import Entry
    assert stage.known_size([Entry("a", "a", False, 10), Entry("d", "d", True, 0), Entry("b", "b", False, 5)]) == 15


def test_a_link_name_always_ends_in_url():
    assert newfile.clean_name("example.org", newfile.LINK) == "example.org.url"
    assert newfile.clean_name("Site.URL", newfile.LINK) == "Site.URL"
