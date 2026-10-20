"""Writing zip files: pack, change a zip or zip-based file safely, convert other archives to zip."""
import os
import zipfile

import pytest

from dossier.core import zipwrite
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.zipwrite import ZipWriteError, convert_to_zip, pack, rewrite, unique_path, why_not_editable


def names(path):
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def read(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "src"
    (root / "album" / "cd1").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "album" / "cover.jpg").write_bytes(bytes(2000))
    (root / "album" / "cd1" / "t1.txt").write_text("track one " * 100)
    (root / "readme.txt").write_text("hello")
    os.utime(root / "readme.txt", (1_600_000_000, 1_600_000_000))
    return root


# pack ------------------------------------------------------------------------------------------------------------
def test_pack_writes_files_folders_and_empty_folders_under_their_own_names(tree, tmp_path):
    out = str(tmp_path / "out.zip")
    r = pack([str(tree / "album"), str(tree / "readme.txt"), str(tree / "empty")], out)
    assert sorted(names(out)) == ["album/", "album/cd1/", "album/cd1/t1.txt", "album/cover.jpg", "empty/", "readme.txt"]
    assert r.files == 3 and r.folders == 3 and r.bytes_in > 0 and not r.skipped
    assert read(out, "readme.txt") == b"hello" and zipfile.ZipFile(out).testzip() is None
    assert zipfile.ZipFile(out).getinfo("readme.txt").date_time[:3] == (2020, 9, 13)           # the file's own date is kept
    assert not os.path.exists(out + zipwrite.TEMP_SUFFIX)


def test_pack_stores_what_is_already_compressed_and_deflates_the_rest(tree, tmp_path):
    out = str(tmp_path / "o.zip")
    pack([str(tree / "album")], out)
    z = zipfile.ZipFile(out)
    assert z.getinfo("album/cover.jpg").compress_type == zipfile.ZIP_STORED
    assert z.getinfo("album/cd1/t1.txt").compress_type == zipfile.ZIP_DEFLATED
    out2 = str(tmp_path / "o2.zip")
    pack([str(tree / "album")], out2, level="store")
    assert zipfile.ZipFile(out2).getinfo("album/cd1/t1.txt").compress_type == zipfile.ZIP_STORED


def test_pack_will_not_overwrite_and_a_cancel_leaves_nothing_behind(tree, tmp_path):
    out = tmp_path / "o.zip"
    out.write_text("keep me")
    with pytest.raises(FileExistsError):
        pack([str(tree / "readme.txt")], str(out))
    assert out.read_text() == "keep me"
    token = CancelToken()
    token.cancel()
    target = str(tmp_path / "c.zip")
    with pytest.raises(Cancelled):
        pack([str(tree / "album")], target, cancel=token)
    assert not os.path.exists(target) and not os.path.exists(target + zipwrite.TEMP_SUFFIX)


def test_pack_reports_progress_up_to_the_total(tree, tmp_path):
    seen = []
    pack([str(tree / "album")], str(tmp_path / "p.zip"), progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1]


# rewrite ---------------------------------------------------------------------------------------------------------
def make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype", (2020, 1, 1, 0, 0, 0)), "application/epub+zip")     # stored, first
        z.writestr("META-INF/container.xml", "<c/>", zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/ch1.xhtml", "one" * 500, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/ch2.xhtml", "two" * 500, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/img/a.png", bytes(300), zipfile.ZIP_STORED)
        z.comment = b"made by a test"


def test_remove_rename_and_add_in_one_pass_keeping_order_methods_and_comment(tmp_path):
    epub = str(tmp_path / "book.epub")
    make_epub(epub)
    new = tmp_path / "ch3.xhtml"
    new.write_text("three" * 100)
    binned = []
    r = rewrite(epub, remove=["OEBPS/ch2.xhtml"], rename={"OEBPS/img": "OEBPS/images"},
                add=[("OEBPS/ch3.xhtml", str(new)), ("OEBPS/notes", None)], trasher=binned.append)
    assert names(epub)[0] == "mimetype" and zipfile.ZipFile(epub).getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    assert names(epub) == ["mimetype", "META-INF/container.xml", "OEBPS/ch1.xhtml", "OEBPS/images/a.png",
                           "OEBPS/ch3.xhtml", "OEBPS/notes/"]
    assert read(epub, "OEBPS/ch3.xhtml") == b"three" * 100 and read(epub, "OEBPS/ch1.xhtml") == b"one" * 500
    assert zipfile.ZipFile(epub).comment == b"made by a test"
    assert zipfile.ZipFile(epub).getinfo("mimetype").date_time == (2020, 1, 1, 0, 0, 0)
    assert len(binned) == 1 and binned[0].endswith(".dossier-old") and r.files == 5
    assert sorted(os.listdir(tmp_path)) == sorted(["book.epub", "ch3.xhtml", os.path.basename(binned[0])])      # old file is where the bin took it from


def test_removing_a_folder_takes_everything_below_it_and_an_added_file_replaces_the_old_one(tmp_path):
    z = str(tmp_path / "a.zip")
    with zipfile.ZipFile(z, "w") as w:
        for n in ("d/", "d/x.txt", "d/sub/y.txt", "keep.txt", "dd/z.txt"):
            w.writestr(n, b"" if n.endswith("/") else n)
    new = tmp_path / "n.txt"
    new.write_text("NEW")
    rewrite(z, remove=["d"], add=[("keep.txt", str(new))], trasher=lambda p: os.remove(p))
    assert sorted(names(z)) == ["dd/z.txt", "keep.txt"] and read(z, "keep.txt") == b"NEW"


def test_a_failure_leaves_the_original_untouched_and_no_temporary_file(tmp_path, monkeypatch):
    epub = str(tmp_path / "book.epub")
    make_epub(epub)
    before = open(epub, "rb").read()
    calls = []
    real = zipwrite._copy_into

    def boom(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise OSError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(zipwrite, "_copy_into", boom)
    with pytest.raises(OSError):
        rewrite(epub, remove=["OEBPS/ch2.xhtml"], trasher=lambda p: None)
    assert open(epub, "rb").read() == before and sorted(os.listdir(tmp_path)) == ["book.epub"]


def test_a_cancel_leaves_the_original_untouched(tmp_path):
    epub = str(tmp_path / "book.epub")
    make_epub(epub)
    before = open(epub, "rb").read()
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        rewrite(epub, remove=["mimetype"], cancel=token)
    assert open(epub, "rb").read() == before and sorted(os.listdir(tmp_path)) == ["book.epub"]


def test_names_that_would_clash_are_refused_before_anything_is_written(tmp_path):
    z = str(tmp_path / "a.zip")
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("a.txt", "1")
        w.writestr("b.txt", "2")
    before = open(z, "rb").read()
    with pytest.raises(ZipWriteError, match="same name"):
        rewrite(z, rename={"a.txt": "b.txt"})
    assert open(z, "rb").read() == before and sorted(os.listdir(tmp_path)) == ["a.zip"]


def test_only_readable_unencrypted_zip_based_files_can_be_changed(tmp_path):
    other = tmp_path / "a.7z"
    other.write_bytes(b"x")
    assert "converted to zip" in why_not_editable(str(other))
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK not really")
    assert "not a readable zip" in why_not_editable(str(bad))
    enc = tmp_path / "enc.zip"
    with zipfile.ZipFile(enc, "w") as w:
        w.writestr("secret.txt", "x")
    raw = bytearray(enc.read_bytes())
    raw[raw.index(b"PK\x03\x04") + 6] |= 1                    # the "encrypted" bit, in the local header
    raw[raw.index(b"PK\x01\x02") + 8] |= 1                    # and in the central directory
    enc.write_bytes(bytes(raw))
    assert "encrypted" in why_not_editable(str(enc))
    assert why_not_editable(str(tmp_path / "missing.zip")) and why_not_editable(str(tmp_path))
    ok = tmp_path / "ok.cbz"
    with zipfile.ZipFile(ok, "w") as w:
        w.writestr("1.jpg", "x")
    assert why_not_editable(str(ok)) == ""


def test_unique_path_numbers_what_is_taken(tmp_path):
    (tmp_path / "a.zip").write_text("x")
    (tmp_path / "a (2).zip").write_text("x")
    assert unique_path(str(tmp_path / "a.zip")) == str(tmp_path / "a (3).zip") and unique_path(str(tmp_path / "n.zip")) == str(tmp_path / "n.zip")


# convert ---------------------------------------------------------------------------------------------------------
def test_a_7z_becomes_a_zip_beside_it_and_the_original_stays(tree, tmp_path):
    py7zr = pytest.importorskip("py7zr")
    archive = str(tmp_path / "album.7z")
    with py7zr.SevenZipFile(archive, "w") as z:
        z.writeall(str(tree / "album"), "album")
        z.writeall(str(tree / "readme.txt"), "readme.txt")
    out = convert_to_zip(archive)
    assert out.path == str(tmp_path / "album.zip") and os.path.exists(archive)
    assert sorted(n for n in names(out.path) if not n.endswith("/")) == ["album/cd1/t1.txt", "album/cover.jpg", "readme.txt"]
    assert read(out.path, "readme.txt") == b"hello"
    again = convert_to_zip(archive)
    assert again.path == str(tmp_path / "album (2).zip")                    # never over an existing file


def test_a_tar_is_converted_through_7zip_and_a_zip_or_a_non_archive_is_refused(tree, tmp_path):
    from dossier.core import archives
    if not archives.find_seven_zip():
        pytest.skip("7-Zip is not installed")
    import tarfile
    tar = str(tmp_path / "t.tar")
    with tarfile.open(tar, "w") as t:
        t.add(str(tree / "album"), arcname="album")
    out = convert_to_zip(tar)
    assert "album/cd1/t1.txt" in names(out.path)
    plain = str(tmp_path / "p.zip")
    pack([str(tree / "readme.txt")], plain)
    with pytest.raises(ZipWriteError, match="already a zip"):
        convert_to_zip(plain)
    txt = tmp_path / "x.txt"
    txt.write_text("x")
    with pytest.raises(ZipWriteError):
        convert_to_zip(str(txt))
    assert not [n for n in os.listdir(tmp_path) if n.startswith("dossier-convert")]


def test_the_convert_temp_folder_is_gone_after_a_failure(tmp_path, monkeypatch):
    import tempfile
    from dossier.core import archives
    bad = tmp_path / "b.7z"
    bad.write_bytes(b"7z\xbc\xaf\x27\x1c" + bytes(40))
    before = set(os.listdir(tempfile.gettempdir()))
    with pytest.raises(OSError):
        convert_to_zip(str(bad))
    assert not [n for n in set(os.listdir(tempfile.gettempdir())) - before if n.startswith("dossier-convert")]


def test_a_program_that_has_the_archive_open_for_a_moment_is_waited_for(tmp_path, monkeypatch):
    z = str(tmp_path / "a.zip")
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("a.txt", "1")
        w.writestr("b.txt", "2")
    real = os.replace
    refused = []

    def busy_twice(src, dst):
        if src == z and len(refused) < 2:
            refused.append(1)
            raise PermissionError(13, "in use")
        return real(src, dst)

    monkeypatch.setattr(zipwrite.os, "replace", busy_twice)
    monkeypatch.setattr(zipwrite, "REPLACE_WAIT", 0.01)
    rewrite(z, remove=["a.txt"], trasher=lambda p: os.remove(p))
    assert refused == [1, 1] and names(z) == ["b.txt"]


def test_an_archive_that_stays_in_use_is_reported_and_left_as_it_was(tmp_path, monkeypatch):
    z = str(tmp_path / "a.zip")
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("a.txt", "1")
    before = open(z, "rb").read()
    real = os.replace

    def always_busy(src, dst):
        if src == z:
            raise PermissionError(13, "in use")
        return real(src, dst)

    monkeypatch.setattr(zipwrite.os, "replace", always_busy)
    monkeypatch.setattr(zipwrite, "REPLACE_WAIT", 0.0)
    with pytest.raises(ZipWriteError, match="in use by another program"):
        rewrite(z, remove=["a.txt"], trasher=lambda p: None)
    assert open(z, "rb").read() == before and sorted(os.listdir(tmp_path)) == ["a.zip"]
