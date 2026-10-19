"""Regression tests for the defects found in the 2026-10-19 review (docs/review-and-plan.md, section 3)."""
import itertools
import os
import subprocess

import pytest

from dossier.core.platform import IS_WINDOWS, REPLACEMENT, decode_name
from dossier.core.selection import SelectionStore
from dossier.core.vfs import LocalFileSystem, walk


# decode_name -------------------------------------------------------------
def test_decode_name_bytes_never_raises():
    # Not valid UTF-8 and not a valid single-byte name on every system.
    out = decode_name(b"caf\xe9.txt")
    assert isinstance(out, str)
    assert out.endswith(".txt")
    assert REPLACEMENT in out


def test_decode_name_plain_bytes_roundtrip():
    assert decode_name(b"plain.txt") == "plain.txt"


def test_decode_name_replaces_any_lone_surrogate():
    # NTFS allows unpaired UTF-16 surrogates; Python shows them as U+D800..U+DFFF.
    assert decode_name("a\ud800b") == "a" + REPLACEMENT + "b"
    assert decode_name("a\udc80b") == "a" + REPLACEMENT + "b"


# stat --------------------------------------------------------------------
def test_stat_directory_has_no_size_and_is_dir(tmp_path):
    d = tmp_path / "sub"
    d.mkdir()
    e = LocalFileSystem().stat(str(d))
    assert e.is_dir and e.size == 0 and e.name == "sub"


def test_stat_file_size(tmp_path):
    f = tmp_path / "f.txt"
    f.write_bytes(b"12345")
    e = LocalFileSystem().stat(str(f))
    assert not e.is_dir and e.size == 5 and not e.is_link


def test_list_directory_entry_has_no_size(tmp_path):
    (tmp_path / "sub").mkdir()
    (e,) = LocalFileSystem().list(str(tmp_path))
    assert e.is_dir and e.size == 0


# walk --------------------------------------------------------------------
def _make_junction(link, target):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("cannot create a junction here")


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are a Windows thing")
def test_walk_does_not_follow_junction_cycle(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_text("x")
    _make_junction(tmp_path / "a" / "loop", tmp_path)
    found = list(itertools.islice(walk(LocalFileSystem(), str(tmp_path)), 50))
    assert len(found) < 50
    loop = [e for e in found if e.name == "loop"]
    assert loop and loop[0].is_link


@pytest.mark.skipif(IS_WINDOWS, reason="symlinks need privileges on Windows")
def test_walk_does_not_follow_symlink_cycle(tmp_path):
    (tmp_path / "a").mkdir()
    os.symlink(str(tmp_path), str(tmp_path / "a" / "loop"))
    found = list(itertools.islice(walk(LocalFileSystem(), str(tmp_path)), 50))
    assert len(found) < 50


def test_walk_skips_unreadable_subfolder(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "f.txt").write_text("x")
    (tmp_path / "bad").mkdir()

    class Flaky(LocalFileSystem):
        def list(self, path):
            if os.path.basename(path) == "bad":
                raise PermissionError(path)
            return super().list(path)

    names = [e.name for e in walk(Flaky(), str(tmp_path))]
    assert "f.txt" in names and "bad" in names


def test_walk_still_raises_for_unreadable_root(tmp_path):
    missing = str(tmp_path / "nope")
    with pytest.raises(OSError):
        list(walk(LocalFileSystem(), missing))


# selection ---------------------------------------------------------------
def test_invert_with_nothing_to_flip_does_not_notify():
    s = SelectionStore()
    calls = []
    s.subscribe(lambda st: calls.append(1))
    s.invert([])
    assert calls == []


def test_a_failing_observer_does_not_stop_the_others():
    s = SelectionStore()
    seen = []

    def bad(st):
        raise RuntimeError("boom")

    s.subscribe(bad)
    s.subscribe(lambda st: seen.append(len(st)))
    s.add(["/a"])
    assert seen == [1]
    assert s.paths() == ["/a"]


def test_recall_unknown_name_is_a_clear_keyerror():
    s = SelectionStore()
    with pytest.raises(KeyError, match="nope"):
        s.recall("nope")
