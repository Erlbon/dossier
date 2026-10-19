import os
import sys

import pytest

from dossier.core.platform import IS_WINDOWS, decode_name, path_key
from dossier.core.selection import SelectionStore
from dossier.core.vfs import LocalFileSystem, natural_key, sort_entries


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


@pytest.mark.skipif(sys.platform == "win32", reason="byte names are a Linux thing")
def test_undecodable_name_does_not_break_listing(tmp_path):
    bad = os.path.join(os.fsencode(str(tmp_path)), b"caf\xe9.txt")
    with open(bad, "wb") as f:
        f.write(b"x")
    names = [e.name for e in LocalFileSystem().list(str(tmp_path))]
    assert len(names) == 1
    assert "\ufffd" in names[0]
    assert decode_name(os.fsencode("plain")) == "plain"
