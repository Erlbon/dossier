"""Checksums: computed on request, compared, never written to disk."""
import hashlib
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.checksums import algorithm_of, clean_value, hash_file, match  # noqa: E402
from dossier.core.vfs import LocalFileSystem  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_hashes_equal_hashlib_and_several_algorithms_share_one_read(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(os.urandom(3_000_000))
    h = hash_file(LocalFileSystem(), str(f), ("md5", "sha256"))
    data = f.read_bytes()
    assert h.digests == {"md5": hashlib.md5(data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}
    assert h.size == len(data)


def test_an_unreadable_file_reports_an_error_not_a_crash(tmp_path):
    h = hash_file(LocalFileSystem(), str(tmp_path / "missing.bin"))
    assert h.error and not h.digests


def test_pasted_values_are_cleaned_and_their_algorithm_found_by_length():
    sha = hashlib.sha256(b"x").hexdigest()
    assert clean_value(f"  SHA256: {sha.upper()} *x.txt ") == sha
    assert algorithm_of(sha) == "sha256" and algorithm_of(hashlib.md5(b"x").hexdigest()) == "md5"
    assert clean_value("not a hash") == ""


def test_show_and_verify_through_the_window_without_writing_any_file(world):
    win, d, left, *_ = world
    (left / "a.txt").write_text("alpha")
    (left / "b.txt").write_text("beta")
    win.left.refresh()
    before = sorted(os.listdir(left))
    win.select_all()
    win.show_checksums()
    pump(win, lambda: d.outputs)
    expected = hashlib.sha256(b"alpha").hexdigest()
    assert f"{expected} *a.txt" in d.outputs[-1][1]
    assert QApplication.clipboard().text() == d.outputs[-1][1]
    d.texts.append(hashlib.sha256(b"beta").hexdigest())
    win.verify_checksum()
    pump(win, lambda: d.infos)
    assert "matches: b.txt" in d.infos[-1][1]
    d.texts.append(hashlib.sha256(b"other").hexdigest())
    win.verify_checksum()
    pump(win, lambda: len(d.infos) > 1)
    assert "No match" in d.infos[-1][1]
    assert sorted(os.listdir(left)) == before                  # no sidecar file anywhere


def test_a_folder_is_not_hashed(world):
    win, d, left, *_ = world
    (left / "sub").mkdir()
    win.left.refresh()
    win.select_all()
    win.show_checksums()
    assert "Mark files" in win.status.text() and not d.outputs
