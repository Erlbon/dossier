"""Rename by editing the names as text: the Qt-free part (core/rename_text.py)."""
import os

import pytest

from dossier.core.ops import execute
from dossier.core.platform import IS_WINDOWS
from dossier.core.rename_text import (COMMENT, RenameTextError, check_unchanged, pairs_from, parse, plan_text_renames,
                                      render, snapshot)
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


def make(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_text(n)
    return [str(tmp_path / n) for n in names]


def run(plan, log=None):
    assert plan.executable, (plan.blocking, plan.conflicts)
    return execute(plan, fs, trasher=lambda p: None, undo_log=log)


def listing(p):
    return sorted(os.listdir(p))


def test_render_has_a_header_that_can_be_left_out(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a.txt", "b.txt"))
    with_header = render(snap).split(chr(10))
    assert with_header[0].startswith(COMMENT) and with_header[-3:] == ["a.txt", "b.txt", ""]
    assert render(snap, header=False) == "a.txt" + chr(10) + "b.txt" + chr(10)


def test_the_header_and_other_comment_lines_are_ignored_when_read_back(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a.txt", "b.txt"))
    assert parse(render(snap), snap) == ["a.txt", "b.txt"]
    assert parse("// my own note" + chr(10) + "x.txt" + chr(10) + "y.txt", snap) == ["x.txt", "y.txt"]      # no final newline either
    assert parse("x.txt" + chr(13) + chr(10) + "y.txt" + chr(13) + chr(10), snap) == ["x.txt", "y.txt"]     # Windows line ends


def test_a_changed_line_count_is_refused(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a", "b", "c"))
    for text in ("a" + chr(10) + "b" + chr(10), "a" + chr(10) + "b" + chr(10) + "c" + chr(10) + "d" + chr(10)):
        with pytest.raises(RenameTextError, match="Nothing was renamed"):
            parse(text, snap)


def test_an_emptied_line_is_refused_and_never_a_delete(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a", "b"))
    with pytest.raises(RenameTextError, match="Line 2 is empty"):
        parse("a" + chr(10) + chr(10), snap)
    with pytest.raises(RenameTextError, match="empty"):
        parse("   " + chr(10) + "b" + chr(10), snap)


def test_unchanged_lines_are_skipped(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a", "b", "c"))
    assert pairs_from(snap, ["a", "B", "c"]) == [(str(tmp_path / "b"), "B")]
    assert pairs_from(snap, ["a", "b", "c"]) == []


def test_a_name_with_a_slash_or_a_bad_character_is_refused(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a", "b"))
    with pytest.raises(RenameTextError, match="Line 1.*path separator"):
        pairs_from(snap, ["x/y", "b"])
    if IS_WINDOWS:
        with pytest.raises(RenameTextError, match="Line 2"):
            pairs_from(snap, ["a", "b?"])


def test_a_folder_that_changed_while_editing_is_refused(tmp_path):
    snap = snapshot(fs, make(tmp_path, "a", "b"))
    check_unchanged(fs, snap)                                   # as it was: fine
    (tmp_path / "new").write_text("n")
    with pytest.raises(RenameTextError, match="New: new"):
        check_unchanged(fs, snap)
    os.remove(tmp_path / "new")
    os.rename(tmp_path / "b", tmp_path / "bb")                  # renamed: one gone, one new
    with pytest.raises(RenameTextError, match="Gone: b"):
        check_unchanged(fs, snap)


def test_items_in_two_folders_are_refused(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x").write_text("x")
    paths = make(tmp_path, "a") + [str(tmp_path / "sub" / "x")]
    with pytest.raises(RenameTextError, match="one folder"):
        snapshot(fs, paths)


def test_a_swap_goes_through_a_temporary_name_and_undoes(tmp_path):
    paths = make(tmp_path, "a", "b")
    plan = plan_text_renames(fs, [(paths[0], "b"), (paths[1], "a")])
    assert plan.executable and len(plan.ops) == 3 and plan.warnings
    log = UndoLog()
    run(plan, log)
    assert (tmp_path / "a").read_text() == "b" and (tmp_path / "b").read_text() == "a"
    assert listing(tmp_path) == ["a", "b"]                     # no temporary name left
    log.undo_last(fs)
    assert (tmp_path / "a").read_text() == "a" and (tmp_path / "b").read_text() == "b"


def test_a_ring_of_three_and_a_chain_into_it(tmp_path):
    paths = make(tmp_path, "a", "b", "c", "x")
    plan = plan_text_renames(fs, [(paths[0], "b"), (paths[1], "c"), (paths[2], "a"), (paths[3], "a2")])
    run(plan)
    assert [(tmp_path / n).read_text() for n in ("a", "b", "c", "a2")] == ["c", "a", "b", "x"]
    # a chain into a ring: x takes the name a, which is part of the ring a -> b -> a
    plan = plan_text_renames(fs, [(str(tmp_path / "a"), "b"), (str(tmp_path / "b"), "a"), (str(tmp_path / "a2"), "b2")])
    run(plan)
    assert (tmp_path / "a").read_text() == "a" and (tmp_path / "b").read_text() == "c" and (tmp_path / "b2").read_text() == "x"


def test_a_chain_without_a_ring_needs_no_temporary_name(tmp_path):
    paths = make(tmp_path, "a", "b")
    plan = plan_text_renames(fs, [(paths[0], "b"), (paths[1], "c")])        # b moves to c first, then a to b
    assert len(plan.ops) == 2 and not plan.warnings
    run(plan)
    assert listing(tmp_path) == ["b", "c"] and (tmp_path / "b").read_text() == "a"


def test_a_name_taken_by_an_item_outside_the_batch_or_wanted_twice_is_a_conflict(tmp_path):
    paths = make(tmp_path, "a", "b", "other")
    assert plan_text_renames(fs, [(paths[0], "other")]).conflicts == [0]
    plan = plan_text_renames(fs, [(paths[0], "z"), (paths[1], "z")])
    assert len(plan.conflicts) == 1 and not plan.executable


def test_a_name_that_cannot_be_used_blocks_the_plan(tmp_path):
    paths = make(tmp_path, "a")
    assert plan_text_renames(fs, [(paths[0], "x/y")]).blocking
