"""Step 3 of docs/review-and-plan.md: write operations, progress and cancel, prefixed keys, long paths."""
import os

import pytest

from dossier.core.platform import IS_WINDOWS, longpath, path_key, strip_longpath
from dossier.core.progress import Cancelled, CancelToken
from dossier.core.selection import SelectionStore
from dossier.core.transfer import copy_file
from dossier.core.vfs import FileSystem, LocalFileSystem, NotWritable


# identity keys ------------------------------------------------------------
def test_scheme_paths_are_case_sensitive_and_distinct_from_local():
    assert path_key("zip://a.zip/X.md") != path_key("zip://a.zip/x.md")
    assert path_key("ZIP://a.zip/x") == path_key("zip://a.zip/x")
    assert path_key("zip://a.zip/x") != path_key("a.zip/x")


def test_selection_holds_local_and_virtual_items_side_by_side():
    s = SelectionStore()
    s.add(["zip://a.zip/x.md", os.path.join("a.zip", "x.md")])
    assert len(s) == 2


@pytest.mark.skipif(not IS_WINDOWS, reason="extended-length prefix is Windows only")
def test_long_path_prefix_is_one_identity():
    assert path_key("\\\\?\\C:\\x\\a.md") == path_key("C:\\x\\a.md")
    assert path_key("\\\\?\\UNC\\srv\\sh\\a") == path_key("\\\\srv\\sh\\a")


@pytest.mark.skipif(not IS_WINDOWS, reason="extended-length prefix is Windows only")
def test_longpath_helper_adds_and_strips_prefix_only_when_needed():
    short = "C:\\x\\a.md"
    assert longpath(short) == short
    long = "C:\\" + "\\".join(["d" * 50] * 6) + "\\f.txt"
    assert longpath(long).startswith("\\\\?\\C:\\")
    assert strip_longpath(longpath(long)) == long
    assert longpath("\\\\srv\\sh\\" + "d" * 300).startswith("\\\\?\\UNC\\srv\\sh\\")


def test_longpath_is_identity_on_this_system_for_short_paths(tmp_path):
    p = str(tmp_path / "f")
    assert longpath(p) == p


@pytest.mark.skipif(not IS_WINDOWS, reason="long paths are a Windows limit")
def test_local_fs_works_beyond_260_characters(tmp_path):
    fs = LocalFileSystem()
    deep = str(tmp_path)
    for _ in range(6):
        deep = os.path.join(deep, "d" * 50)
        fs.mkdir(deep)
    assert len(deep) > 260
    target = os.path.join(deep, "f.txt")
    with fs.open_write(target) as f:
        f.write(b"hi")
    assert [e.name for e in fs.list(deep)] == ["f.txt"]
    assert fs.stat(target).size == 2
    with fs.open_read(target) as f:
        assert f.read() == b"hi"
    fs.remove(target)


# write operations -------------------------------------------------------------
def test_mkdir_rename_remove(tmp_path):
    fs = LocalFileSystem()
    d = str(tmp_path / "a")
    fs.mkdir(d)
    with pytest.raises(FileExistsError):
        fs.mkdir(d)
    fs.mkdir(d, exist_ok=True)
    fs.rename(d, str(tmp_path / "b"))
    assert [e.name for e in fs.list(str(tmp_path))] == ["b"]
    fs.remove(str(tmp_path / "b"))
    assert fs.list(str(tmp_path)) == []


def test_rename_refuses_to_overwrite_unless_asked(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "a").write_text("A")
    (tmp_path / "b").write_text("B")
    with pytest.raises(FileExistsError):
        fs.rename(str(tmp_path / "a"), str(tmp_path / "b"))
    assert (tmp_path / "b").read_text() == "B"
    fs.rename(str(tmp_path / "a"), str(tmp_path / "b"), overwrite=True)
    assert (tmp_path / "b").read_text() == "A"


def test_case_only_rename_is_allowed(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "a.md").write_text("x")
    fs.rename(str(tmp_path / "a.md"), str(tmp_path / "A.md"))
    assert [e.name for e in fs.list(str(tmp_path))] == ["A.md"]


def test_remove_refuses_non_empty_folder(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f").write_text("x")
    with pytest.raises(OSError):
        fs.remove(str(tmp_path / "d"))


def test_open_write_exclusive_refuses_existing(tmp_path):
    fs = LocalFileSystem()
    p = str(tmp_path / "f")
    with fs.open_write(p, exclusive=True) as f:
        f.write(b"1")
    with pytest.raises(FileExistsError):
        fs.open_write(p, exclusive=True)


def test_set_mtime(tmp_path):
    fs = LocalFileSystem()
    p = tmp_path / "f"
    p.write_text("x")
    fs.set_mtime(str(p), 1_000_000_000.0)
    assert fs.stat(str(p)).mtime == pytest.approx(1_000_000_000.0, abs=2)


def test_read_only_source_says_so():
    class Ro(FileSystem):
        def list(self, path): return []
        def stat(self, path): raise FileNotFoundError(path)
        def open_read(self, path): raise FileNotFoundError(path)

    ro = Ro()
    assert ro.writable is False
    for call in (lambda: ro.mkdir("x"), lambda: ro.remove("x"), lambda: ro.rename("a", "b"),
                 lambda: ro.open_write("x"), lambda: ro.set_mtime("x", 0.0)):
        with pytest.raises(NotWritable):
            call()


def test_scan_is_lazy_and_matches_list(tmp_path):
    for n in "abc":
        (tmp_path / n).write_text("x")
    fs = LocalFileSystem()
    it = fs.scan(str(tmp_path))
    first = next(it)
    assert first.name in "abc"
    assert sorted(e.name for e in fs.scan(str(tmp_path))) == ["a", "b", "c"]


# copy with progress and cancel ----------------------------------------------------
def test_copy_file_reports_progress_and_keeps_mtime(tmp_path):
    fs = LocalFileSystem()
    src = tmp_path / "s.bin"
    src.write_bytes(b"x" * 10_000)
    os.utime(src, (1_000_000_000, 1_000_000_000))
    seen = []
    copy_file(fs, str(src), fs, str(tmp_path / "d.bin"), progress=lambda done, total: seen.append((done, total)),
              chunk_size=4096)
    assert (tmp_path / "d.bin").read_bytes() == b"x" * 10_000
    assert seen[-1] == (10_000, 10_000)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen) and len(seen) >= 3
    assert fs.stat(str(tmp_path / "d.bin")).mtime == pytest.approx(1_000_000_000.0, abs=2)


def test_copy_file_refuses_to_overwrite_by_default(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "s").write_text("S")
    (tmp_path / "d").write_text("D")
    with pytest.raises(FileExistsError):
        copy_file(fs, str(tmp_path / "s"), fs, str(tmp_path / "d"))
    assert (tmp_path / "d").read_text() == "D"
    copy_file(fs, str(tmp_path / "s"), fs, str(tmp_path / "d"), overwrite=True)
    assert (tmp_path / "d").read_text() == "S"


def test_cancel_removes_the_partial_copy_and_keeps_the_original(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "s").write_bytes(b"x" * 10_000)
    (tmp_path / "d").write_text("OLD")
    token = CancelToken()

    def progress(done, total):
        token.cancel()

    with pytest.raises(Cancelled):
        copy_file(fs, str(tmp_path / "s"), fs, str(tmp_path / "d"), progress=progress, cancel=token,
                  overwrite=True, chunk_size=1000)
    assert (tmp_path / "d").read_text() == "OLD"          # target untouched
    assert sorted(os.listdir(tmp_path)) == ["d", "s"]      # no temp file left behind


def test_cancelled_before_start_does_nothing(tmp_path):
    fs = LocalFileSystem()
    (tmp_path / "s").write_text("S")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        copy_file(fs, str(tmp_path / "s"), fs, str(tmp_path / "d"), cancel=token)
    assert not (tmp_path / "d").exists()
