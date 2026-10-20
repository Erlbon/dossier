"""Comparing two folders and synchronising them (core): what is reported, what each mode does, and that the plans really make them alike."""
import os
import shutil

import pytest

from dossier.core import compare as cmp
from dossier.core import sync
from dossier.core.ops import execute
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()
T0 = 1_700_000_000


def put(path, data, mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def trash(tmp):
    def go(path):
        shutil.move(path, str(tmp / ("bin_" + os.path.basename(path))))
    return go


@pytest.fixture
def pair(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return left, right


def statuses(result):
    return {r.rel: r.status for r in result.rows}


def build_example(left, right):
    put(left / "same.txt", b"same")
    put(right / "same.txt", b"same")
    put(left / "only_l.txt", b"L")
    put(right / "only_r.txt", b"R")
    put(left / "new_l.txt", b"newer on the left", T0 + 500)
    put(right / "new_l.txt", b"older", T0)
    put(left / "new_r.txt", b"old", T0)
    put(right / "new_r.txt", b"newer on the right", T0 + 500)
    put(left / "diff.txt", b"aaaa")
    put(right / "diff.txt", b"bbbbb")                               # a different size at the same time
    put(left / "sub" / "deep" / "x.txt", b"x")                      # a folder only on the left: one row
    put(left / "both" / "inner_l.txt", b"i")
    put(right / "both" / "inner_r.txt", b"i")
    (left / "kind").mkdir()
    put(right / "kind", b"a file where the left has a folder")


def test_every_kind_of_difference_is_found_and_same_files_and_shared_folders_are_not_listed(pair):
    left, right = pair
    build_example(left, right)
    r = cmp.compare_trees(fs, str(left), str(right))
    assert statuses(r) == {"both/inner_l.txt": "only_left", "both/inner_r.txt": "only_right", "diff.txt": "different",
                           "kind": "type", "new_l.txt": "left_newer", "new_r.txt": "right_newer", "only_l.txt": "only_left",
                           "only_r.txt": "only_right", "sub": "only_left"}
    assert r.same == 1 and r.unreadable == 0 and r.count("only_left") == 3
    assert [row.rel for row in r.rows] == sorted(row.rel for row in r.rows)             # in order


def test_not_looking_below_leaves_the_subfolders_out_and_include_same_lists_the_alike(pair):
    left, right = pair
    build_example(left, right)
    flat = cmp.compare_trees(fs, str(left), str(right), recursive=False)
    assert "both/inner_l.txt" not in statuses(flat) and "only_l.txt" in statuses(flat)
    everything = cmp.compare_trees(fs, str(left), str(right), include_same=True)
    assert statuses(everything)["same.txt"] == "same"


def test_the_way_two_files_are_told_apart_is_the_owners_choice(pair):
    left, right = pair
    put(left / "a", b"1234", T0 + 100)
    put(right / "a", b"1234", T0)                                   # the same size, another time
    put(left / "b", b"AAAA", T0)
    put(right / "b", b"BBBB", T0)                                   # the same size and time, other bytes
    by = lambda how: statuses(cmp.compare_trees(fs, str(left), str(right), by=how))             # noqa: E731
    assert by("size_time") == {"a": "left_newer"}                    # b has the same size and time: alike, however different inside
    assert by("size") == {}                                         # sizes only
    assert by("content") == {"b": "different"}                      # bytes: a is alike whatever its time, b is not


def test_times_agree_within_the_tolerance_and_an_hour_of_summer_time_is_optional(pair):
    left, right = pair
    put(left / "close", b"x", T0 + 2)
    put(right / "close", b"x", T0)
    put(left / "hour", b"x", T0 + 3600)
    put(right / "hour", b"x", T0)
    assert statuses(cmp.compare_trees(fs, str(left), str(right))) == {}
    assert statuses(cmp.compare_trees(fs, str(left), str(right), ignore_hour=False)) == {"hour": "left_newer"}
    assert statuses(cmp.compare_trees(fs, str(left), str(right), tolerance=0.0, ignore_hour=False)) == \
        {"close": "left_newer", "hour": "left_newer"}


def test_two_files_are_compared_to_the_first_different_byte(pair):
    left, right = pair
    a = put(left / "f", b"hello world")
    b = put(right / "f", b"hello there")
    c = put(right / "g", b"hello world")
    d = put(right / "short", b"hello")
    assert cmp.first_difference(fs, a, b) == 6 and cmp.first_difference(fs, a, c) == -1
    assert cmp.first_difference(fs, a, d) == 5                       # the shorter one differs where it ends
    assert cmp.same_content(fs, a, c) and not cmp.same_content(fs, a, b) and not cmp.same_content(fs, a, str(left / "nope"))


def test_a_cancel_stops_the_walk_and_a_missing_side_counts_as_empty(pair, tmp_path):
    left, right = pair
    for i in range(5):
        put(left / f"f{i}", b"x")
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        cmp.compare_trees(fs, str(left), str(right), cancel=token)
    r = cmp.compare_trees(fs, str(left), str(tmp_path / "gone"))
    assert r.count("only_left") == 5 and r.unreadable == 1


# the modes -----------------------------------------------------------------------------------------------------------------------
def kinds(rows, mode):
    return {a.row.rel: a.kind for a in sync.decide_all(rows, mode) if a.kind}


def test_each_mode_decides_each_difference(pair):
    left, right = pair
    build_example(left, right)
    rows = cmp.compare_trees(fs, str(left), str(right)).rows
    assert kinds(rows, "update_right") == {"both/inner_l.txt": "copy_right", "new_l.txt": "copy_right", "only_l.txt": "copy_right",
                                           "sub": "copy_right"}                         # nothing newer on the right is touched
    assert kinds(rows, "update_left") == {"both/inner_r.txt": "copy_left", "new_r.txt": "copy_left", "only_r.txt": "copy_left"}
    assert kinds(rows, "both") == {"both/inner_l.txt": "copy_right", "both/inner_r.txt": "copy_left", "new_l.txt": "copy_right",
                                   "new_r.txt": "copy_left", "only_l.txt": "copy_right", "only_r.txt": "copy_left", "sub": "copy_right"}
    mirror = kinds(rows, "mirror_right")
    assert mirror["diff.txt"] == "copy_right" and mirror["new_r.txt"] == "copy_right" and mirror["only_r.txt"] == "delete_right"
    assert "kind" not in mirror and "kind" not in kinds(rows, "both")                    # a file against a folder is never decided
    ml = kinds(rows, "mirror_left")
    assert ml["only_l.txt"] == "delete_left" and ml["new_l.txt"] == "copy_left" and ml["diff.txt"] == "copy_left"
    s = sync.summarise(sync.decide_all(rows, "mirror_right"))
    assert s.deletes_right == 2 and s.replaced_newer == 1 and s.replaced >= 3 and "newer" in s.text()
    assert sync.summarise([]).text() == "nothing to do"


def test_update_right_makes_the_right_side_hold_everything_new_and_changes_nothing_else(pair, tmp_path):
    left, right = pair
    build_example(left, right)
    cmpres = cmp.compare_trees(fs, str(left), str(right))
    actions = sync.decide_all(cmpres.rows, "update_right")
    plans = sync.build_plans(fs, str(left), str(right), actions)
    assert len(plans) == 1 and plans[0].executable
    result = execute(plans[0], fs, trasher=trash(tmp_path))
    assert not result.failed
    assert (right / "only_l.txt").read_bytes() == b"L" and (right / "new_l.txt").read_bytes() == b"newer on the left"
    assert (right / "sub" / "deep" / "x.txt").read_bytes() == b"x" and (right / "both" / "inner_l.txt").exists()
    assert (right / "new_r.txt").read_bytes() == b"newer on the right"                   # the newer file of the right stays
    assert (right / "only_r.txt").exists() and (left / "only_r.txt").exists() is False   # nothing deleted, nothing copied back
    again = cmp.compare_trees(fs, str(left), str(right))
    assert {r.status for r in again.rows} <= {"only_right", "right_newer", "different", "type"}


def test_mirror_right_makes_the_sides_equal_and_deletes_go_to_the_bin(pair, tmp_path):
    left, right = pair
    put(left / "a.txt", b"A")
    put(left / "keep.txt", b"new", T0 + 900)
    put(right / "keep.txt", b"old", T0)
    put(right / "extra.txt", b"extra")
    put(right / "extra_dir" / "f.txt", b"f")
    put(left / "newfolder" / "n.txt", b"n")
    actions = sync.decide_all(cmp.compare_trees(fs, str(left), str(right)).rows, "mirror_right")
    plans = sync.build_plans(fs, str(left), str(right), actions)
    assert [p.title for p in plans][0] == "Copy" and len(plans) == 2
    for p in plans:
        assert not execute(p, fs, trasher=trash(tmp_path)).failed
    assert cmp.compare_trees(fs, str(left), str(right)).rows == []
    assert not (right / "extra.txt").exists() and (tmp_path / "bin_extra.txt").exists()      # to the bin, not gone for good
    assert (right / "keep.txt").read_bytes() == b"new"


def test_both_ways_leaves_what_it_cannot_decide(pair, tmp_path):
    left, right = pair
    build_example(left, right)
    actions = sync.decide_all(cmp.compare_trees(fs, str(left), str(right)).rows, "both")
    for p in sync.build_plans(fs, str(left), str(right), actions):
        assert not execute(p, fs, trasher=trash(tmp_path)).failed
    left_over = statuses(cmp.compare_trees(fs, str(left), str(right)))
    assert left_over == {"diff.txt": "different", "kind": "type"}


def test_a_chosen_subset_is_all_that_runs(pair, tmp_path):
    left, right = pair
    put(left / "one.txt", b"1")
    put(left / "two.txt", b"2")
    actions = [a for a in sync.decide_all(cmp.compare_trees(fs, str(left), str(right)).rows, "update_right") if a.row.rel == "two.txt"]
    for p in sync.build_plans(fs, str(left), str(right), actions):
        execute(p, fs, trasher=trash(tmp_path))
    assert (right / "two.txt").exists() and not (right / "one.txt").exists()
    assert sync.build_plans(fs, str(left), str(right), []) == []
