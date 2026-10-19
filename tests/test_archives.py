"""7z, RAR and the rest as read-only folders: py7zr and 7-Zip behind the same file system as zip."""
import os
import subprocess
import tarfile

import pytest

from dossier.core import archives, zipfs
from dossier.core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.ops import execute, plan_copy, plan_delete
from dossier.core.vfs import LocalFileSystem, NotWritable
from dossier.core.zipfs import ZipFileSystem, archive_root

SEVEN = archives.find_seven_zip()
needs_7z = pytest.mark.skipif(SEVEN is None, reason="7-Zip is not installed")
needs_py7zr = pytest.mark.skipif(not archives.have_py7zr(), reason="py7zr is not installed")

FILES = {"readme.txt": b"hello", "docs/one.txt": b"1" * 100, "docs/deep/two.txt": b"22", "r\u00e6d/gr\u00f8d.txt": b"norsk"}


def source_tree(tmp_path, files=FILES):
    root = tmp_path / "tree"
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def make_7z_with_exe(tmp_path, extra=(), name="a.7z"):
    root = source_tree(tmp_path)
    out = tmp_path / name
    subprocess.run([SEVEN, "a", "-y", "-sccUTF-8", *extra, str(out), "*"], cwd=root, check=True, capture_output=True)
    return str(out)


def make_7z_with_py7zr(tmp_path):
    import py7zr
    root = source_tree(tmp_path)
    out = tmp_path / "p.7z"
    with py7zr.SevenZipFile(out, "w") as z:
        z.writeall(root, arcname="")
    return str(out)


def make_tar(tmp_path):
    root = source_tree(tmp_path)
    out = tmp_path / "t.tar"
    with tarfile.open(out, "w") as t:
        for name in FILES:
            t.add(root / name, arcname=name)
    return str(out)


def names(entries):
    return sorted(e.name for e in entries)


def check_tree(fs, archive):
    root = archive_root(archive)
    assert names(fs.list(root)) == ["docs", "readme.txt", "r\u00e6d"]
    assert names(fs.list(root + "docs")) == ["deep", "one.txt"]
    assert fs.stat(root + "docs/one.txt").size == 100
    with fs.open_read(root + "docs/deep/two.txt") as f:
        assert f.read() == b"22"
    with fs.open_read(root + "r\u00e6d/gr\u00f8d.txt") as f:                  # non-ASCII names survive
        assert f.read() == b"norsk"
    with fs.open_read(root + "readme.txt") as f:                             # also read in pieces
        assert f.read(2) == b"he" and f.read(2) == b"ll" and f.read() == b"o" and f.read() == b""


# reader choice --------------------------------------------------------------------------------------------
def test_the_kind_of_a_file_comes_from_its_content_and_its_name(tmp_path):
    z = tmp_path / "x.zip"
    import zipfile
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a", "a")
    assert archives.kind_of(str(z)) == "zip"
    (tmp_path / "s.7z").write_bytes(archives.SEVEN_ZIP_MAGIC + b"\x00\x04" + b"x" * 40)
    assert archives.kind_of(str(tmp_path / "s.7z")) == "7z"
    (tmp_path / "r.bin").write_bytes(archives.RAR_MAGICS[1] + b"x" * 40)
    assert archives.kind_of(str(tmp_path / "r.bin")) == "rar"                  # by content, whatever the name
    (tmp_path / "b.cab").write_bytes(b"MSCF" + b"x" * 40)
    assert archives.kind_of(str(tmp_path / "b.cab")) == "other"
    (tmp_path / "plain.txt").write_text("not an archive")
    assert archives.kind_of(str(tmp_path / "plain.txt")) == ""
    assert archives.kind_of(str(tmp_path / "missing.7z")) == ""


def test_without_any_reader_the_archive_is_not_openable_and_the_message_says_what_would_help(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "have_py7zr", lambda: False)
    monkeypatch.setattr(archives, "find_seven_zip", lambda: None)
    sevenz = tmp_path / "s.7z"
    sevenz.write_bytes(archives.SEVEN_ZIP_MAGIC + b"x" * 40)
    rar = tmp_path / "r.rar"
    rar.write_bytes(archives.RAR_MAGICS[0] + b"x" * 40)
    assert archives.backend_for(str(sevenz)) is None and not zipfs.is_archive(str(sevenz))
    assert "py7zr" in archives.missing_reader(str(sevenz)) and "7-Zip" in archives.missing_reader(str(sevenz))
    assert "7-Zip" in archives.missing_reader(str(rar)) and "py7zr" not in archives.missing_reader(str(rar))
    (tmp_path / "plain.txt").write_text("x")
    assert archives.missing_reader(str(tmp_path / "plain.txt")) == ""
    with pytest.raises(OSError, match="7-Zip"):
        ZipFileSystem().list(archive_root(str(rar)))


def test_a_zip_is_always_read_by_the_standard_library(tmp_path):
    import zipfile
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a", "a")
    assert isinstance(archives.backend_for(str(z)), archives.ZipBackend)


# the listing parser ---------------------------------------------------------------------------------------
def test_the_7zip_listing_parser_reads_blocks_and_skips_the_archive_itself():
    text = "\n".join([
        "Path = C:\\data\\a.rar", "Type = Rar5", "Physical Size = 999", "",
        "Path = docs", "Folder = +", "Size = 0", "Modified = 2020-02-03 04:05:06", "Attributes = D", "Encrypted = -", "",
        "Path = docs\\one.txt", "Folder = -", "Size = 100", "Modified = 2020-02-03 04:05:06", "Attributes = A",
        "Encrypted = +", "",
        "Path = zero.bin", "Size = 0", "Attributes = A", ""])
    members = archives.parse_listing(text)
    assert [(m.name, m.is_dir, m.size, m.encrypted) for m in members] == [
        ("docs", True, 0, False), ("docs/one.txt", False, 100, True), ("zero.bin", False, 0, False)]
    assert members[1].ref == "docs\\one.txt" and members[1].mtime > 0 and members[2].mtime == 0.0


# py7zr ----------------------------------------------------------------------------------------------------
@needs_py7zr
def test_7z_made_by_py7zr_is_a_folder_tree(tmp_path):
    path = make_7z_with_py7zr(tmp_path)
    assert isinstance(archives.backend_for(path), archives.SevenZipBackend)
    check_tree(ZipFileSystem(), path)


@needs_py7zr
def test_a_member_of_a_7z_is_extracted_to_a_temp_folder_that_goes_when_the_stream_closes(tmp_path):
    path = make_7z_with_py7zr(tmp_path)
    fs = ZipFileSystem()
    stream = fs.open_read(archive_root(path) + "readme.txt")
    folder = os.path.dirname(stream._inner.name)
    assert os.path.isdir(folder)
    stream.close()
    assert not os.path.exists(folder)


@needs_py7zr
@needs_7z
def test_an_encrypted_7z_is_reported_not_read_as_empty(tmp_path):
    path = make_7z_with_exe(tmp_path, extra=("-pSECRET",))
    fs = ZipFileSystem()
    with pytest.raises(PermissionError):
        fs.open_read(archive_root(path) + "readme.txt")


# 7-Zip ----------------------------------------------------------------------------------------------------
@needs_7z
def test_7z_through_the_7zip_program(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "have_py7zr", lambda: False)                 # force the program
    path = make_7z_with_exe(tmp_path)
    assert isinstance(archives.backend_for(path), archives.ExternalBackend)
    check_tree(ZipFileSystem(), path)


@needs_7z
def test_a_tar_is_a_folder_tree_through_7zip(tmp_path):
    path = make_tar(tmp_path)
    assert isinstance(archives.backend_for(path), archives.ExternalBackend)
    check_tree(ZipFileSystem(), path)


@needs_7z
def test_a_name_with_wildcard_characters_is_read_as_the_file_it_is(tmp_path):
    files = {"a[1].txt": b"bracket", "star*.txt": b"star", "other.txt": b"other"}
    root = source_tree(tmp_path, {k: v for k, v in files.items() if "*" not in k})
    out = tmp_path / "w.7z"
    subprocess.run([SEVEN, "a", "-y", str(out), "a[1].txt", "other.txt", "-spd"], cwd=root, check=True,
                   capture_output=True)
    fs = ZipFileSystem()
    with fs.open_read(archive_root(str(out)) + "a[1].txt") as f:
        assert f.read() == b"bracket"


@needs_7z
def test_an_archive_with_encrypted_names_is_an_error_at_once_and_does_not_wait_for_a_password(tmp_path):
    path = make_7z_with_exe(tmp_path, extra=("-pSECRET", "-mhe=on"))
    with pytest.raises(OSError):
        ZipFileSystem().list(archive_root(path))


@needs_7z
def test_encrypted_members_are_marked_and_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "have_py7zr", lambda: False)
    path = make_7z_with_exe(tmp_path, extra=("-pSECRET",))
    fs = ZipFileSystem()
    entry = fs.stat(archive_root(path) + "readme.txt")
    assert entry.size == 5
    with pytest.raises(PermissionError):
        fs.open_read(archive_root(path) + "readme.txt")


@needs_7z
def test_a_damaged_archive_is_an_error_not_an_empty_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "have_py7zr", lambda: False)
    path = make_7z_with_exe(tmp_path)
    data = open(path, "rb").read()
    open(path, "wb").write(data[:20])
    with pytest.raises(OSError):
        ZipFileSystem().list(archive_root(path))


@needs_7z
def test_closing_a_member_stream_early_stops_the_process(tmp_path):
    root = source_tree(tmp_path, {"big.bin": os.urandom(5_000_000)})
    out = tmp_path / "big.tar"
    with tarfile.open(out, "w") as t:
        t.add(root / "big.bin", arcname="big.bin")
    stream = ZipFileSystem().open_read(archive_root(str(out)) + "big.bin")
    assert len(stream.read(1000)) == 1000
    process = stream._p
    stream.close()
    assert process.poll() is not None


# in the file system and the plans -----------------------------------------------------------------------------
@pytest.fixture
def router():
    return RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider()))


@needs_7z
def test_copying_out_of_a_tar_and_refusing_changes_work_like_for_zip(tmp_path, router):
    path = make_tar(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()
    root = archive_root(path)
    plan = plan_copy(router, [root + "docs", root + "readme.txt"], str(dest))
    assert not plan.blocking
    res = execute(plan, router)
    assert not res.failed
    assert (dest / "readme.txt").read_bytes() == b"hello" and (dest / "docs" / "deep" / "two.txt").read_bytes() == b"22"
    assert plan_delete(router, [root + "readme.txt"]).blocking
    assert plan_copy(router, [str(dest / "readme.txt")], root).blocking
    with pytest.raises(NotWritable):
        router.mkdir(root + "new")


# in the window --------------------------------------------------------------------------------------------
def test_enter_on_an_archive_nobody_can_read_says_what_helps_and_does_not_crash(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QApplication
    from dossier.gui import panel as panel_module
    from dossier.gui.main_window import MainWindow
    from tests.test_gui_commander import FakeDialogs, key
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(archives, "have_py7zr", lambda: False)
    monkeypatch.setattr(archives, "find_seven_zip", lambda: None)
    opened = []
    monkeypatch.setattr(panel_module.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    left, right = tmp_path / "l", tmp_path / "r"
    left.mkdir()
    right.mkdir()
    (left / "a.rar").write_bytes(archives.RAR_MAGICS[0] + b"x" * 40)
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=FakeDialogs())
    try:
        win.show()
        win.left.refresh()
        win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.rar"), 0))
        key(win, Qt.Key.Key_Return)
        assert "7-Zip" in win.status.text() and len(opened) == 1 and not win.left.path.startswith("zip://")
    finally:
        win.close()
