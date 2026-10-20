"""Dossier's own copy and move carry the tags of a file along (they live in a stream Python's copy leaves behind)."""
import os
import sys

import pytest

from dossier.core import filetags
from dossier.core.filetags import Tags, read_tags, write_tags
from dossier.core.ops import ExecOptions, Resolution, execute, plan_copy, plan_move
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


@pytest.fixture
def folders(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    if not filetags.can_hold_tags(str(tmp_path)):
        pytest.skip("no place for tags here")
    return tmp_path / "src", tmp_path / "dst"


def run(plan, **kw):
    return execute(plan, fs, options=ExecOptions(**kw))


def test_a_small_and_a_big_file_and_a_folder_keep_their_tags_when_copied(folders):
    src, dst = folders
    small, big = src / "small.txt", src / "big.bin"
    small.write_text("x")
    big.write_bytes(os.urandom(12_000_000))
    (src / "album").mkdir()
    (src / "album" / "inner.txt").write_text("i")
    for p, t in ((small, Tags(tags=["s"], rating=1)), (big, Tags(tags=["b"])), (src / "album", Tags(tags=["folder"])),
                 (src / "album" / "inner.txt", Tags(tags=["inner"]))):
        write_tags(str(p), t)
    result = run(plan_copy(fs, [str(small), str(big), str(src / "album")], str(dst)))
    assert not result.failed and result.tags_lost == []
    assert read_tags(str(dst / "small.txt")).tags == ["s"] and read_tags(str(dst / "small.txt")).rating == 1
    assert read_tags(str(dst / "big.bin")).tags == ["b"]
    assert read_tags(str(dst / "album")).tags == ["folder"] and read_tags(str(dst / "album" / "inner.txt")).tags == ["inner"]
    assert read_tags(str(small)).tags == ["s"]                                  # the original keeps them too


def test_copying_over_an_existing_file_gives_it_the_tags_of_the_new_one(folders):
    src, dst = folders
    (src / "a.txt").write_text("new")
    (dst / "a.txt").write_text("old")
    write_tags(str(src / "a.txt"), Tags(tags=["new"]))
    write_tags(str(dst / "a.txt"), Tags(tags=["old"]))
    plan = plan_copy(fs, [str(src / "a.txt")], str(dst)).resolve(Resolution.OVERWRITE, fs)
    run(plan, native_copy=False)
    assert (dst / "a.txt").read_text() == "new" and read_tags(str(dst / "a.txt")).tags == ["new"]


def test_a_move_on_the_same_drive_keeps_the_tags(folders):
    src, dst = folders
    (src / "m.txt").write_text("m")
    write_tags(str(src / "m.txt"), Tags(tags=["moved"]))
    run(plan_move(fs, [str(src / "m.txt")], str(dst)))
    assert read_tags(str(dst / "m.txt")).tags == ["moved"]


def test_a_file_without_tags_stays_without_and_costs_nothing_visible(folders):
    src, dst = folders
    (src / "plain.txt").write_text("p")
    result = run(plan_copy(fs, [str(src / "plain.txt")], str(dst)))
    assert read_tags(str(dst / "plain.txt")).is_empty() and result.tags_lost == [] and not result.failed
    assert sorted(os.listdir(dst)) == ["plain.txt"]


def test_when_the_destination_cannot_hold_tags_the_copy_succeeds_and_says_so(folders, monkeypatch):
    src, dst = folders
    (src / "t.txt").write_text("t")
    write_tags(str(src / "t.txt"), Tags(tags=["x"]))
    real = filetags.write_tags

    def refuse(path, t, backend=None):
        if os.path.dirname(path) == str(dst):
            raise filetags.CannotHoldTags("no room")
        return real(path, t, backend)

    monkeypatch.setattr(filetags, "write_tags", refuse)
    result = run(plan_copy(fs, [str(src / "t.txt")], str(dst)))
    assert not result.failed and (dst / "t.txt").read_text() == "t"
    assert result.tags_lost == [str(dst / "t.txt")]


pytest.importorskip("PyQt6")
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


@pytest.mark.skipif(sys.platform != "win32", reason="real streams")
def test_the_window_says_once_when_tags_could_not_follow(world, monkeypatch):
    win, d, left, right, *_ = world
    if not filetags.can_hold_tags(str(left)):
        pytest.skip("no place for tags here")
    for n in ("a.txt", "b.txt"):
        (left / n).write_text(n)
        write_tags(str(left / n), Tags(tags=["x"]))
    win.left.refresh()
    real = filetags.write_tags
    monkeypatch.setattr(filetags, "write_tags", lambda p, t, backend=None: (_ for _ in ()).throw(filetags.CannotHoldTags("no"))
                        if os.path.dirname(p) == str(right) else real(p, t, backend))
    win.select_all()
    win.copy()
    pump(win, lambda: not win.busy and "copied without tags" in win.status.text())
    assert "2 items were copied without tags" in win.status.text()
