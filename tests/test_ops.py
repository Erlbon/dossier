"""Operation plans, conflicts, execution and undo (plan step 5)."""
import os
import shutil

import pytest

from dossier.core.ops import (Kind, PlanNotReady, Resolution, check_name, execute, plan_copy, plan_delete,
                              plan_move, plan_rename, plan_rename_many)
from dossier.core.platform import IS_WINDOWS
from dossier.core.progress import CancelToken
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


@pytest.fixture
def work(tmp_path):
    """tmp_path/src, tmp_path/dst and a fake recycle bin outside both."""
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    (tmp_path / "bin").mkdir()
    return tmp_path


class Bin:
    def __init__(self, folder):
        self.folder = folder
        self.items = []

    def __call__(self, path):
        target = os.path.join(self.folder, f"{len(self.items)}-{os.path.basename(path)}")
        shutil.move(path, target)
        self.items.append(path)


def listing(p):
    return sorted(os.listdir(p))


def write(p, text="x", mtime=None):
    p.write_text(text)
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def run(plan, bin_, log=None, **kw):
    return execute(plan, fs, trasher=bin_, undo_log=log, **kw)


# copy ----------------------------------------------------------------------------------
def test_copy_file_and_folder_tree(work):
    write(work / "src" / "a.txt", "A")
    (work / "src" / "tree" / "deep").mkdir(parents=True)
    write(work / "src" / "tree" / "deep" / "b.txt", "B")
    plan = plan_copy(fs, [str(work / "src" / "a.txt"), str(work / "src" / "tree")], str(work / "dst"))
    assert plan.executable and not plan.conflicts
    res = run(plan, Bin(work / "bin"))
    assert not res.failed
    assert (work / "dst" / "a.txt").read_text() == "A"
    assert (work / "dst" / "tree" / "deep" / "b.txt").read_text() == "B"
    assert (work / "src" / "a.txt").exists()           # a copy leaves the original


def test_flatten_puts_every_file_in_one_folder_and_flags_name_clashes(work):
    (work / "src" / "one").mkdir()
    (work / "src" / "two").mkdir()
    write(work / "src" / "one" / "same.txt", "1")
    write(work / "src" / "two" / "same.txt", "2")
    write(work / "src" / "two" / "other.txt", "3")
    plan = plan_copy(fs, [str(work / "src" / "one"), str(work / "src" / "two")], str(work / "dst"), flatten=True)
    assert len(plan.ops) == 3 and len(plan.conflicts) == 1
    assert not plan.executable
    with pytest.raises(PlanNotReady):
        run(plan, Bin(work / "bin"))
    plan = plan.resolve(Resolution.KEEP_BOTH, fs)
    run(plan, Bin(work / "bin"))
    assert listing(work / "dst") == ["other.txt", "same (2).txt", "same.txt"]


def test_copy_into_missing_destination_is_blocked(work):
    write(work / "src" / "a", "A")
    plan = plan_copy(fs, [str(work / "src" / "a")], str(work / "nope"))
    assert plan.blocking and not plan.executable


def test_copy_folder_into_itself_is_blocked(work):
    (work / "src" / "f").mkdir()
    plan = plan_copy(fs, [str(work / "src" / "f")], str(work / "src" / "f"))
    assert plan.blocking


def test_copy_a_vanished_source_is_left_out_with_a_warning(work):
    write(work / "src" / "a", "A")
    plan = plan_copy(fs, [str(work / "src" / "a"), str(work / "src" / "gone")], str(work / "dst"))
    assert len(plan.ops) == 1 and plan.warnings and len(plan.skipped) == 1


# conflicts -------------------------------------------------------------------------------------
def test_conflict_overwrite_sends_the_old_file_to_the_bin(work):
    write(work / "src" / "a", "NEW")
    write(work / "dst" / "a", "OLD")
    plan = plan_copy(fs, [str(work / "src" / "a")], str(work / "dst"))
    assert plan.conflicts == [0] and not plan.executable
    bin_ = Bin(work / "bin")
    run(plan.resolve(Resolution.OVERWRITE, fs), bin_)
    assert (work / "dst" / "a").read_text() == "NEW"
    assert len(bin_.items) == 1
    assert (work / "bin" / "0-a.dossier-old").read_text() == "OLD"          # the older file, under its set-aside name


def test_conflict_skip_leaves_the_target_alone(work):
    write(work / "src" / "a", "NEW")
    write(work / "dst" / "a", "OLD")
    plan = plan_copy(fs, [str(work / "src" / "a")], str(work / "dst")).resolve(Resolution.SKIP, fs)
    assert plan.ops == () and not plan.executable
    assert (work / "dst" / "a").read_text() == "OLD"


def test_conflict_overwrite_if_newer(work):
    write(work / "src" / "newer", "S1", mtime=2_000_000_000)
    write(work / "dst" / "newer", "D1", mtime=1_000_000_000)
    write(work / "src" / "older", "S2", mtime=1_000_000_000)
    write(work / "dst" / "older", "D2", mtime=2_000_000_000)
    sources = [str(work / "src" / "newer"), str(work / "src" / "older")]
    plan = plan_copy(fs, sources, str(work / "dst")).resolve(Resolution.OVERWRITE_IF_NEWER, fs)
    run(plan, Bin(work / "bin"))
    assert (work / "dst" / "newer").read_text() == "S1"
    assert (work / "dst" / "older").read_text() == "D2"


def test_folders_merge_and_only_clashing_files_conflict(work):
    (work / "src" / "d").mkdir()
    (work / "dst" / "d").mkdir()
    write(work / "src" / "d" / "new.txt", "N")
    write(work / "src" / "d" / "both.txt", "S")
    write(work / "dst" / "d" / "both.txt", "D")
    plan = plan_copy(fs, [str(work / "src" / "d")], str(work / "dst"))
    assert len(plan.conflicts) == 1
    assert plan.ops[plan.conflicts[0]].dst.endswith("both.txt")


def test_a_folder_cannot_be_overwritten(work):
    (work / "src" / "x").mkdir()
    write(work / "dst" / "x", "i am a file")
    plan = plan_copy(fs, [str(work / "src" / "x")], str(work / "dst")).resolve(Resolution.OVERWRITE, fs)
    assert not plan.executable and plan.conflicts


def test_copy_into_the_same_folder_keeps_both(work):
    write(work / "src" / "a.txt", "A")
    plan = plan_copy(fs, [str(work / "src" / "a.txt")], str(work / "src"))
    assert plan.conflicts == [0]
    assert not plan.resolve(Resolution.OVERWRITE, fs).executable      # never overwrite itself
    run(plan.resolve(Resolution.KEEP_BOTH, fs), Bin(work / "bin"))
    assert listing(work / "src") == ["a (2).txt", "a.txt"]


def test_copy_folder_into_its_own_parent_keeps_both_and_remaps_children(work):
    (work / "src" / "f").mkdir()
    write(work / "src" / "f" / "c.txt", "C")
    plan = plan_copy(fs, [str(work / "src" / "f")], str(work / "src"))
    run(plan.resolve(Resolution.KEEP_BOTH, fs), Bin(work / "bin"))
    assert (work / "src" / "f (2)" / "c.txt").read_text() == "C"
    assert (work / "src" / "f" / "c.txt").read_text() == "C"


# move and rename --------------------------------------------------------------------------------
def test_move_file_and_folder_then_undo(work):
    write(work / "src" / "a.txt", "A")
    (work / "src" / "d").mkdir()
    write(work / "src" / "d" / "b.txt", "B")
    log = UndoLog()
    plan = plan_move(fs, [str(work / "src" / "a.txt"), str(work / "src" / "d")], str(work / "dst"))
    run(plan, Bin(work / "bin"), log)
    assert listing(work / "src") == [] and listing(work / "dst") == ["a.txt", "d"]
    report = log.undo_last(fs)
    assert report.reverted == 2 and not report.problems
    assert listing(work / "src") == ["a.txt", "d"] and listing(work / "dst") == []
    assert len(log) == 0


def test_move_onto_existing_name_conflicts_even_for_folders(work):
    (work / "src" / "d").mkdir()
    (work / "dst" / "d").mkdir()
    plan = plan_move(fs, [str(work / "src" / "d")], str(work / "dst"))
    assert plan.conflicts == [0]
    assert not plan.resolve(Resolution.OVERWRITE, fs).executable


def test_move_to_same_folder_is_a_noop_and_into_itself_is_blocked(work):
    write(work / "src" / "a", "A")
    (work / "src" / "f").mkdir()
    plan = plan_move(fs, [str(work / "src" / "a")], str(work / "src"))
    assert plan.ops == () and plan.skipped
    plan = plan_move(fs, [str(work / "src" / "f")], str(work / "src" / "f"))
    assert plan.blocking


def test_rename_and_undo(work):
    write(work / "src" / "a.txt", "A")
    log = UndoLog()
    run(plan_rename(fs, str(work / "src" / "a.txt"), "b.txt"), Bin(work / "bin"), log)
    assert listing(work / "src") == ["b.txt"]
    log.undo_last(fs)
    assert listing(work / "src") == ["a.txt"]


def test_case_only_rename_is_not_a_conflict(work):
    write(work / "src" / "a.md", "A")
    plan = plan_rename(fs, str(work / "src" / "a.md"), "A.md")
    assert plan.executable
    run(plan, Bin(work / "bin"))
    assert listing(work / "src") == ["A.md"]


def test_rename_to_an_existing_name_conflicts(work):
    write(work / "src" / "a", "A")
    write(work / "src" / "b", "B")
    plan = plan_rename(fs, str(work / "src" / "a"), "b")
    assert plan.conflicts == [0]


def test_rename_swap_is_a_conflict_not_a_half_done_swap(work):
    write(work / "src" / "a", "A")
    write(work / "src" / "b", "B")
    plan = plan_rename_many(fs, [(str(work / "src" / "a"), "b"), (str(work / "src" / "b"), "a")])
    assert len(plan.conflicts) == 2 and not plan.executable


def test_rename_blocks_bad_names(work):
    write(work / "src" / "a", "A")
    for bad in ("", "..", "x/y", "a\x00b"):
        assert plan_rename(fs, str(work / "src" / "a"), bad).blocking
    assert check_name("fine.txt") == ""


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows name rules")
def test_windows_name_rules():
    for bad in ("a:b", "CON", "nul.txt", "x.", "x "):
        assert check_name(bad)


def test_batch_rename_with_counters_runs_in_one_action(work):
    for n in "abc":
        write(work / "src" / n, n)
    log = UndoLog()
    pairs = [(str(work / "src" / n), f"{i}-{n}") for i, n in enumerate("abc", 1)]
    run(plan_rename_many(fs, pairs), Bin(work / "bin"), log)
    assert listing(work / "src") == ["1-a", "2-b", "3-c"]
    assert len(log) == 1
    log.undo_last(fs)
    assert listing(work / "src") == ["a", "b", "c"]


# delete ---------------------------------------------------------------------------------------------
def test_delete_to_bin_uses_the_trasher(work):
    write(work / "src" / "a", "A")
    (work / "src" / "d").mkdir()
    write(work / "src" / "d" / "b", "B")
    bin_ = Bin(work / "bin")
    log = UndoLog()
    plan = plan_delete(fs, [str(work / "src" / "a"), str(work / "src" / "d")])
    res = run(plan, bin_, log)
    assert listing(work / "src") == [] and len(bin_.items) == 2 and not res.failed
    assert len(log) == 0                     # the bin keeps it; not undoable from here


def test_permanent_delete_warns_and_removes_trees(work):
    (work / "src" / "d" / "e").mkdir(parents=True)
    write(work / "src" / "d" / "e" / "b", "B")
    plan = plan_delete(fs, [str(work / "src" / "d")], to_trash=False)
    assert any("permanent" in w for w in plan.warnings)
    run(plan, Bin(work / "bin"))
    assert listing(work / "src") == []


def test_failing_trash_keeps_the_item_and_reports(work):
    write(work / "src" / "a", "A")

    def broken(path):
        raise OSError("bin unavailable")

    res = execute(plan_delete(fs, [str(work / "src" / "a")]), fs, trasher=broken)
    assert len(res.failed) == 1 and "bin unavailable" in res.failed[0].error
    assert (work / "src" / "a").exists()


# progress, cancel, failures --------------------------------------------------------------------------
def test_progress_reaches_total(work):
    write(work / "src" / "a", "x" * 5000)
    write(work / "src" / "b", "y" * 3000)
    plan = plan_copy(fs, [str(work / "src" / "a"), str(work / "src" / "b")], str(work / "dst"))
    seen = []
    run(plan, Bin(work / "bin"), progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (plan.total_work, plan.total_work)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_cancel_stops_between_steps_and_what_was_done_can_be_undone(work):
    for n in "abc":
        write(work / "src" / n, n * 100)
    token = CancelToken()
    log = UndoLog()
    plan = plan_copy(fs, [str(work / "src" / n) for n in "abc"], str(work / "dst"))
    calls = []

    def progress(done, total):
        calls.append(done)
        if len(calls) >= 3:      # cancel after the first file finished
            token.cancel()

    res = run(plan, Bin(work / "bin"), log, progress=progress, cancel=token)
    assert res.cancelled
    done_names = listing(work / "dst")
    assert 1 <= len(done_names) < 3
    assert not any(n.endswith(".dossier-part") for n in done_names)
    log.undo_last(fs)
    assert listing(work / "dst") == []


def test_one_failure_does_not_stop_the_rest(work):
    write(work / "src" / "a", "A")
    write(work / "src" / "b", "B")
    plan = plan_copy(fs, [str(work / "src" / "a"), str(work / "src" / "b")], str(work / "dst"))
    os.remove(work / "src" / "a")            # vanishes between plan and execute
    res = run(plan, Bin(work / "bin"))
    assert len(res.failed) == 1 and len(res.done) == 1
    assert (work / "dst" / "b").exists()


# undo safety ------------------------------------------------------------------------------------------
def test_undo_copy_removes_what_it_created_but_not_edited_files(work):
    write(work / "src" / "a", "A")
    write(work / "src" / "b", "B")
    log = UndoLog()
    run(plan_copy(fs, [str(work / "src" / "a"), str(work / "src" / "b")], str(work / "dst")), Bin(work / "bin"), log)
    write(work / "dst" / "b", "edited afterwards, longer")
    report = log.undo_last(fs)
    assert report.reverted == 1 and len(report.problems) == 1
    assert listing(work / "dst") == ["b"]
    assert len(log) == 1                      # the unreverted step stays for another try


def test_undo_move_refuses_when_the_original_place_is_taken(work):
    write(work / "src" / "a", "A")
    log = UndoLog()
    run(plan_move(fs, [str(work / "src" / "a")], str(work / "dst")), Bin(work / "bin"), log)
    write(work / "src" / "a", "someone made a new one")
    report = log.undo_last(fs)
    assert report.problems and report.reverted == 0
    assert (work / "dst" / "a").read_text() == "A"
    assert (work / "src" / "a").read_text() == "someone made a new one"


def test_undo_created_folder_stays_if_not_empty(work):
    (work / "src" / "d").mkdir()
    write(work / "src" / "d" / "f", "F")
    log = UndoLog()
    run(plan_copy(fs, [str(work / "src" / "d")], str(work / "dst")), Bin(work / "bin"), log)
    write(work / "dst" / "d" / "mine", "added by the user")
    report = log.undo_last(fs)
    assert any("not empty" in p for p in report.problems)
    assert (work / "dst" / "d" / "mine").exists()


def test_undo_log_is_bounded_and_can_be_saved_only_on_request(work, tmp_path):
    log = UndoLog(max_entries=2)
    for n in "abc":
        write(work / "src" / n, n)
        run(plan_rename(fs, str(work / "src" / n), n + "2"), Bin(work / "bin"), log)
    assert len(log) == 2 and log.labels() == ["Rename", "Rename"]
    saved = str(tmp_path / "undo.json")
    log.save(saved)
    other = UndoLog()
    other.load(saved)
    assert len(other) == 2
    assert other.undo_last(fs).reverted == 1
    assert UndoLog().undo_last(fs) is None
