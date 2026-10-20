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
