"""A save must survive another program holding the new file for a moment, and the editor and the archive writer must use the one rule."""
import os

import pytest

from dossier.core import fsretry, textedit, zipwrite


def flaky_replace(monkeypatch, failures):
    real = os.replace
    calls = []

    def replace(src, dst):
        calls.append(1)
        if len(calls) <= failures:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    return calls


def test_it_waits_and_then_replaces(tmp_path, monkeypatch):
    src, dst = tmp_path / "new", tmp_path / "old"
    src.write_text("new")
    dst.write_text("old")
    calls = flaky_replace(monkeypatch, 3)
    fsretry.replace_with_retry(str(src), str(dst), wait=0.001)
    assert dst.read_text() == "new" and len(calls) == 4 and not src.exists()


def test_it_gives_up_with_the_original_error_after_the_last_try(tmp_path, monkeypatch):
    src, dst = tmp_path / "new", tmp_path / "old"
    src.write_text("new")
    dst.write_text("old")
    calls = flaky_replace(monkeypatch, 99)
    with pytest.raises(PermissionError):
        fsretry.replace_with_retry(str(src), str(dst), tries=3, wait=0.001)
    assert len(calls) == 3 and dst.read_text() == "old"


def test_saving_a_text_file_survives_a_scanner_holding_the_new_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fsretry, "WAIT", 0.001)
    monkeypatch.setattr(fsretry.replace_with_retry, "__defaults__", (fsretry.TRIES, 0.001))
    path = tmp_path / "a.txt"
    path.write_text("one\n")
    doc = textedit.load_document(str(path))
    calls = flaky_replace(monkeypatch, 2)
    saved = textedit.save_document(doc, "two\n")
    assert path.read_text() == "two\n" and saved.text == "two\n" and len(calls) == 3
    assert not (tmp_path / "a.txt.dossier-save").exists()


def test_the_editor_uses_the_shared_rule_and_the_archive_writer_the_tag_writers_one():
    """Since 2026-11-04 the archive writer is redactor_common's zip_rewrite, whose swap waits through a lock with os_utils.retry_on_lock."""
    from redactor_common.core import zip_rewrite
    assert textedit.replace_with_retry is fsretry.replace_with_retry
    assert zipwrite.rewrite_archive is zip_rewrite.rewrite_archive
