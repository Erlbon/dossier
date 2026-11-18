import os
import sys

import pytest

from dossier.core.platform import IS_WINDOWS, decode_name, is_full_path, path_key
from dossier.core.selection import SelectionStore
from dossier.core.vfs import LocalFileSystem, natural_key, sort_entries

B = chr(92)


@pytest.mark.skipif(not IS_WINDOWS, reason="network paths with backslashes are Windows paths")
def test_a_share_root_is_a_full_path_on_every_python():
    # Python 3.10's isabs says no to \\nas\Media (it wants a backslash after the share); 3.12 says yes. CI runs both.
    assert is_full_path(B * 2 + "nas" + B + "Media") and is_full_path(B * 2 + "nas") and is_full_path("//nas/Media")
    assert is_full_path("C:" + B + "x") and not is_full_path("C:x") and not is_full_path("x") and not is_full_path("")


@pytest.mark.parametrize("windows", [True, False])
def test_a_case_only_change_follows_what_the_volume_does(tmp_path, monkeypatch, windows):
    # Off Windows the volume answers (macOS's APFS and a FAT stick ignore case, ext4 does not); the temp folder here
    # is whatever this system has, so the expected answer is read from the disk itself.
    from dossier.core import platform
    monkeypatch.setattr(platform, "IS_WINDOWS", windows and IS_WINDOWS)
    if windows and not IS_WINDOWS:
        pytest.skip("the Windows rule is tested on Windows")
    (tmp_path / "a.md").write_text("x")
    ignores_case = (tmp_path / "A.md").exists()
    assert platform.is_case_only_change(str(tmp_path / "a.md"), str(tmp_path / "A.md")) == ignores_case
    assert not platform.is_case_only_change(str(tmp_path / "a.md"), str(tmp_path / "b.md"))
    assert not platform.is_case_only_change(str(tmp_path / "a.md"), str(tmp_path / "a.md"))


def test_natural_sort_and_folders_first(tmp_path):
    (tmp_path / "file10.txt").write_text("x")
    (tmp_path / "file2.txt").write_text("x")
    (tmp_path / "zdir").mkdir()
    names = [e.name for e in sort_entries(LocalFileSystem().list(str(tmp_path)))]
    assert names == ["zdir", "file2.txt", "file10.txt"]


def test_sort_keeps_case_variants_distinct():
    assert natural_key("A.md") != natural_key("a.md")


@pytest.mark.skipif(IS_WINDOWS, reason="Windows paths are case-insensitive")
def test_case_sensitive_identity_on_linux():
    assert path_key("/x/A.md") != path_key("/x/a.md")
    s = SelectionStore()
    s.add(["/x/A.md", "/x/a.md"])
    assert len(s) == 2


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows only")
def test_case_insensitive_identity_on_windows():
    s = SelectionStore()
    s.add(["C:\\x\\A.md", "C:\\x\\a.md"])
    assert len(s) == 1


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="byte names are a Linux thing (macOS refuses a name that is not UTF-8)")
def test_undecodable_name_does_not_break_listing(tmp_path):
    bad = os.path.join(os.fsencode(str(tmp_path)), b"caf\xe9.txt")
    with open(bad, "wb") as f:
        f.write(b"x")
    names = [e.name for e in LocalFileSystem().list(str(tmp_path))]
    assert len(names) == 1
    assert "\ufffd" in names[0]
    assert decode_name(os.fsencode("plain")) == "plain"
