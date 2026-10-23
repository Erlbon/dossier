"""The list of unfinished copies, moves and deletes (core part)."""
import json
import os

from dossier.core.ops import plan_copy, plan_move
from dossier.core.queue_journal import Entry, Journal, skip_identical
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


def test_an_entry_is_kept_found_again_and_taken_off(tmp_path):
    j = Journal(str(tmp_path / "sub" / "queue.json"))
    assert j.load() == []
    a = Entry("copy", ["C:/a", "C:/b"], "D:/x", title="Copy 2")
    b = Entry("delete", ["C:/c"], to_trash=False)
    j.add(a)
    j.add(b)
    loaded = j.load()
    assert [e.kind for e in loaded] == ["copy", "delete"] and loaded[0].sources == ["C:/a", "C:/b"] and loaded[0].dest == "D:/x"
    assert loaded[1].to_trash is False and loaded[0].id == a.id
    j.remove(a.id)
    assert [e.kind for e in j.load()] == ["delete"]
    j.remove("no-such-id")
    j.clear()
    assert j.load() == [] and not os.path.exists(j.path)


def test_a_damaged_or_foreign_file_is_an_empty_list_not_an_error(tmp_path):
    p = tmp_path / "queue.json"
    j = Journal(str(p))
    for junk in ("", "not json", "{}", "[1, 2, null]", json.dumps([{"kind": "explode", "sources": ["x"]}]),
                 json.dumps([{"kind": "copy", "sources": []}]), json.dumps([{"kind": "copy", "sources": "nope"}])):
        p.write_text(junk, encoding="utf-8")
        assert j.load() == []
    p.write_text(json.dumps([{"kind": "move", "sources": ["a"], "dest": "b"}, {"kind": "??"}]), encoding="utf-8")
    assert [e.kind for e in j.load()] == ["move"]


def test_the_list_is_capped_and_a_failed_write_never_raises(tmp_path):
    j = Journal(str(tmp_path / "q.json"))
    for i in range(70):
        j.add(Entry("copy", [f"C:/{i}"], "D:/"))
    assert len(j.load()) == 50 and j.load()[-1].sources == ["C:/69"]
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder should be")
    Journal(str(blocker / "q.json")).add(Entry("copy", ["x"], "y"))           # must not raise


def test_entries_describe_themselves_in_plain_words():
    assert Entry("copy", ["a", "b"], "D:/x").describe() == "Copy 2 items to D:/x"
    assert Entry("move", ["a"], "D:/x").describe() == "Move 1 item to D:/x"
    assert Entry("delete", ["a"], to_trash=False).describe() == "Delete 1 item permanently"


def write(path, text, mtime):
    path.write_text(text)
    os.utime(path, (mtime, mtime))


def test_files_that_were_copied_before_the_interruption_are_skipped_and_the_rest_stay_planned(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    for n in ("a.txt", "b.txt", "c.txt"):
        write(src / n, n * 10, 1_700_000_000)
    write(dst / "a.txt", "a.txt" * 10, 1_700_000_000)                     # copied completely before the stop
    write(dst / "b.txt", "different", 1_700_000_000)                      # a different file with the same name
    plan = plan_copy(fs, [str(src / n) for n in ("a.txt", "b.txt", "c.txt")], str(dst))
    assert len(plan.conflicts) == 2
    after = skip_identical(plan, fs)
    assert [os.path.basename(op.dst) for op in after.ops] == ["b.txt", "c.txt"] and len(after.conflicts) == 1      # b still asks
    assert os.path.basename(after.ops[after.conflicts[0]].dst) == "b.txt"


def test_a_move_that_was_part_done_plans_only_what_is_left(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    write(src / "left.txt", "x", 1_700_000_000)
    write(dst / "gone.txt", "y", 1_700_000_000)                           # already moved: not in the source any more
    plan = plan_move(fs, [str(src / "left.txt")], str(dst))
    assert [os.path.basename(op.src) for op in plan.ops] == ["left.txt"] and not plan.conflicts
    assert skip_identical(plan, fs) is plan                               # nothing to settle: the same plan comes back


# plan entries: any settled plan (unpack, sync, flatten, the assistant) is kept as its steps ---------------------------------------------------
def make_files(folder, names, mtime=1_700_000_000):
    folder.mkdir(exist_ok=True)
    for n in names:
        (folder / n).write_text("x" + n)
        os.utime(folder / n, (mtime, mtime))


def test_a_plan_entry_keeps_its_steps_and_the_conflict_choices(tmp_path):
    from dossier.core.ops import Kind, Resolution
    from dossier.core.queue_journal import plan_entry
    src, dst = tmp_path / "s", tmp_path / "d"
    make_files(src, ["a.txt", "b.txt"])
    make_files(dst, ["a.txt"], mtime=1_600_000_000)                       # a different older file is in the way
    plan = plan_copy(fs, [str(src / "a.txt"), str(src / "b.txt")], str(dst))
    plan = plan.resolve(Resolution.OVERWRITE, fs)
    entry = plan_entry(plan)
    j = Journal(str(tmp_path / "queue.json"))
    j.add(entry)
    loaded = j.load()[0]
    assert loaded.kind == "plan" and len(loaded.ops) == 2 and loaded.title == "Copy"
    assert [op.overwrite for op in loaded.ops] == [op.overwrite for op in plan.ops] and any(op.overwrite for op in loaded.ops)
    assert all(op.conflict == "" for op in loaded.ops) and loaded.describe() == "Copy: 2 steps"


def test_a_plan_of_only_renames_or_new_folders_is_not_kept(tmp_path):
    from dossier.core.ops import plan_rename
    from dossier.core.queue_journal import plan_entry
    make_files(tmp_path, ["a.txt"])
    assert plan_entry(plan_rename(fs, str(tmp_path / "a.txt"), "b.txt")) is None


def test_the_remaining_plan_drops_what_is_done(tmp_path):
    from dossier.core.queue_journal import plan_entry, remaining_plan
    src, dst = tmp_path / "s", tmp_path / "d"
    make_files(src, ["a.txt", "b.txt", "c.txt"])
    plan = plan_copy(fs, [str(src / n) for n in ("a.txt", "b.txt", "c.txt")], str(dst))
    entry = plan_entry(plan)
    make_files(dst, ["a.txt"])                                           # copied before the stop (same size and time)
    (src / "b.txt").unlink()                                             # gone
    left = remaining_plan(entry, fs)
    assert [os.path.basename(op.src) for op in left.ops if op.src] == ["c.txt"]


def test_a_half_copied_file_with_another_size_is_copied_again(tmp_path):
    from dossier.core.queue_journal import plan_entry, remaining_plan
    src, dst = tmp_path / "s", tmp_path / "d"
    make_files(src, ["a.txt"])
    entry = plan_entry(plan_copy(fs, [str(src / "a.txt")], str(dst)))
    dst.mkdir()
    (dst / "a.txt").write_text("x")
    os.utime(dst / "a.txt", (1_700_000_000, 1_700_000_000))
    assert len(remaining_plan(entry, fs).ops) == 1


def test_a_slow_write_cannot_bring_back_an_entry_taken_off(tmp_path):
    j = Journal(str(tmp_path / "queue.json"))
    e = Entry("copy", ["a"], "d")
    with j._lock:                                                        # the writer is held back while the entry is taken off
        j.add_later(e)
        j._gone.add(e.id)
    j.flush()
    assert j.load() == []
    j.add_later(e)
    j.flush()
    assert [x.id for x in j.load()] == [e.id]


def test_writes_land_in_the_order_they_were_asked_for(tmp_path):
    j = Journal(str(tmp_path / "queue.json"))
    e = Entry("copy", ["a"], "d")
    j.add_later(e)
    j.add_later(Entry("copy", ["a"], "d", id=e.id, note="1 failed last time"))
    j.flush()
    assert [x.note for x in j.load()] == ["1 failed last time"]


def test_a_note_is_kept_and_shown(tmp_path):
    j = Journal(str(tmp_path / "queue.json"))
    j.add(Entry("copy", ["a"], "d", note="2 failed last time"))
    assert j.load()[0].describe() == "Copy 1 item to d (2 failed last time)"
