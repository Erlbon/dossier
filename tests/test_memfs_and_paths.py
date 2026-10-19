"""Path functions of the file systems, the in-memory system, and the planner / undo / notes / selection
running on it: proof that none of them depends on os.path or on Windows rules (plan step H0)."""
import os

import pytest

from dossier.core.memfs import MemoryFileSystem
from dossier.core.notes import find_notes
from dossier.core.ops import (Resolution, execute, plan_copy, plan_delete, plan_move, plan_rename,
                              plan_rename_many)
from dossier.core.selection import SelectionStore
from dossier.core.transfer import copy_file
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem, walk


@pytest.fixture
def mem():
    fs = MemoryFileSystem()
    fs.put("mem://src/a.txt", b"AAAA", mtime=1000.0)
    fs.put("mem://src/b.txt", b"BB")
    fs.put("mem://src/tree/deep/c.txt", b"C")
    fs.makedirs("mem://dst")
    return fs


def names(fs, folder):
    return sorted(fs.basename(e.path) for e in fs.list(folder))


# path functions -------------------------------------------------------------------------------------------------
def test_virtual_paths_use_forward_slashes_whatever_the_platform():
    fs = MemoryFileSystem()
    assert fs.sep == "/" and fs.root == "mem://" and fs.case_sensitive
    assert fs.join("mem://a", "b", "c.txt") == "mem://a/b/c.txt"
    assert fs.join("mem://", "x") == "mem://x"
    assert fs.join("mem://a/", "/b/") == "mem://a/b"
    assert fs.basename("mem://a/b/c.txt") == "c.txt" and fs.basename("mem://a/b/") == "b"
    assert fs.dirname("mem://a/b/c.txt") == "mem://a/b"
    assert fs.dirname("mem://a") == "mem://" and fs.dirname("mem://") == "mem://"
    assert fs.is_root("mem://") and not fs.is_root("mem://a")


def test_the_local_system_still_uses_the_platform_rules(tmp_path):
    fs = LocalFileSystem()
    assert fs.join(str(tmp_path), "x", "y") == os.path.join(str(tmp_path), "x", "y")
    assert fs.basename(os.path.join(str(tmp_path), "f.txt")) == "f.txt"
    assert fs.dirname(os.path.join(str(tmp_path), "f.txt")) == str(tmp_path)
    assert fs.sep == os.sep and fs.is_root(os.path.abspath(os.sep)) and not fs.is_root(str(tmp_path))


# the in-memory system obeys the same contract as the disk ------------------------------------------------------------
def test_memory_system_contract(mem):
    assert names(mem, "mem://src") == ["a.txt", "b.txt", "tree"]
    e = mem.stat("mem://src/a.txt")
    assert e.size == 4 and not e.is_dir and e.mtime == 1000.0 and e.name == "a.txt"
    with mem.open_read("mem://src/a.txt") as f:
        assert f.read() == b"AAAA"
    mem.mkdir("mem://new/deeper", parents=True)
    with pytest.raises(FileExistsError):
        mem.mkdir("mem://new")
    mem.mkdir("mem://new", exist_ok=True)
    with pytest.raises(FileNotFoundError):
        mem.mkdir("mem://missing/x")
    with mem.open_write("mem://new/f.bin") as w:
        w.write(b"1234")
    assert mem.stat("mem://new/f.bin").size == 4
    with pytest.raises(FileExistsError):
        mem.open_write("mem://new/f.bin", exclusive=True)
    with pytest.raises(OSError):
        mem.remove("mem://new")                                # not empty
    mem.rename("mem://new/f.bin", "mem://new/g.bin")
    assert names(mem, "mem://new") == ["deeper", "g.bin"]
    with pytest.raises(FileExistsError):
        mem.rename("mem://new/g.bin", "mem://new/deeper")
    mem.set_mtime("mem://new/g.bin", 5.0)
    assert mem.stat("mem://new/g.bin").mtime == 5.0
    assert [x.name for x in walk(mem, "mem://src")] == ["tree", "deep", "c.txt", "a.txt", "b.txt"]


def test_names_are_case_sensitive_in_memory(mem):
    mem.put("mem://src/Readme.md", b"x")
    mem.put("mem://src/readme.md", b"y")
    assert names(mem, "mem://src").count("Readme.md") == 1 and "readme.md" in names(mem, "mem://src")


def test_copy_file_between_systems_with_progress(mem, tmp_path):
    local = LocalFileSystem()
    seen = []
    copy_file(mem, "mem://src/a.txt", local, str(tmp_path / "a.txt"), progress=lambda d, t: seen.append((d, t)))
    assert (tmp_path / "a.txt").read_bytes() == b"AAAA" and seen[-1] == (4, 4)
    copy_file(local, str(tmp_path / "a.txt"), mem, "mem://dst/from-disk.txt")
    assert mem.stat("mem://dst/from-disk.txt").size == 4


# the planner on the in-memory system ---------------------------------------------------------------------------------
def test_copy_a_tree_with_the_same_planner_code(mem):
    plan = plan_copy(mem, ["mem://src/a.txt", "mem://src/tree"], "mem://dst")
    assert plan.executable
    res = execute(plan, mem)
    assert not res.failed
    assert names(mem, "mem://dst") == ["a.txt", "tree"]
    assert mem.stat("mem://dst/tree/deep/c.txt").size == 1
    assert mem.stat("mem://dst/a.txt").mtime == 1000.0           # the date came along


def test_flatten_and_keep_both_number_names_with_forward_slashes(mem):
    mem.put("mem://src/tree/a.txt", b"other")
    plan = plan_copy(mem, ["mem://src/a.txt", "mem://src/tree"], "mem://dst", flatten=True)
    assert plan.conflicts                                         # two a.txt into one folder
    plan = plan.resolve(Resolution.KEEP_BOTH, mem)
    execute(plan, mem)
    assert names(mem, "mem://dst") == ["a (2).txt", "a.txt", "c.txt"]
    assert all("\\" not in e.path for e in mem.list("mem://dst"))


def test_copy_folder_into_its_parent_keeps_both_and_remaps_children(mem):
    plan = plan_copy(mem, ["mem://src/tree"], "mem://src")
    assert 0 in plan.conflicts                                    # the folder is the same item as its own copy
    execute(plan.resolve(Resolution.KEEP_BOTH, mem), mem)
    assert "tree (2)" in names(mem, "mem://src")
    assert mem.stat("mem://src/tree (2)/deep/c.txt").size == 1


def test_copying_a_folder_into_itself_is_blocked(mem):
    assert plan_copy(mem, ["mem://src/tree"], "mem://src/tree/deep").blocking


def test_move_rename_and_undo_in_memory(mem):
    log = UndoLog()
    execute(plan_move(mem, ["mem://src/a.txt", "mem://src/tree"], "mem://dst"), mem, undo_log=log)
    assert names(mem, "mem://src") == ["b.txt"] and names(mem, "mem://dst") == ["a.txt", "tree"]
    execute(plan_rename(mem, "mem://dst/a.txt", "z.txt"), mem, undo_log=log)
    assert "z.txt" in names(mem, "mem://dst")
    log.undo_last(mem)
    assert "a.txt" in names(mem, "mem://dst")
    log.undo_last(mem)
    assert names(mem, "mem://src") == ["a.txt", "b.txt", "tree"]


def test_rename_to_a_name_that_differs_only_in_case_is_a_plain_rename_on_a_case_sensitive_system(mem):
    plan = plan_rename(mem, "mem://src/a.txt", "A.txt")
    assert plan.executable and not plan.conflicts                 # 'a.txt' and 'A.txt' are different names here
    execute(plan, mem)
    assert "A.txt" in names(mem, "mem://src") and "a.txt" not in names(mem, "mem://src")


def test_batch_rename_swap_is_a_conflict_in_memory_too(mem):
    plan = plan_rename_many(mem, [("mem://src/a.txt", "b.txt"), ("mem://src/b.txt", "a.txt")])
    assert len(plan.conflicts) == 2 and not plan.executable


def test_permanent_delete_of_a_tree_in_memory(mem):
    plan = plan_delete(mem, ["mem://src/tree", "mem://src/b.txt"], to_trash=False)
    assert any("permanent" in w for w in plan.warnings)
    res = execute(plan, mem)
    assert not res.failed and names(mem, "mem://src") == ["a.txt"]


def test_delete_to_the_bin_goes_through_the_trasher_and_overwrite_uses_it(mem):
    binned = []

    def trasher(path):
        binned.append(path)
        mem.remove(path)

    mem.put("mem://dst/a.txt", b"OLD")
    plan = plan_copy(mem, ["mem://src/a.txt"], "mem://dst").resolve(Resolution.OVERWRITE, mem)
    execute(plan, mem, trasher=trasher)
    assert binned == ["mem://dst/a.txt"] and mem.stat("mem://dst/a.txt").size == 4


# notes and selection --------------------------------------------------------------------------------------------------
def test_notes_are_found_in_a_virtual_folder(mem):
    mem.put("mem://src/about.md", b"---\ntitle: About\n---\nTop")
    mem.put("mem://src/README.md", b"Bottom")
    notes = find_notes(mem, "mem://src")
    assert [n.body for n in notes] == ["Top", "Bottom"] and notes[0].title == "About"
    assert notes[0].path == "mem://src/about.md"


def test_selection_keeps_virtual_and_local_items_apart_and_follows_moves_with_forward_slashes():
    s = SelectionStore()
    s.add(["mem://a/File.txt", "mem://a/file.txt", "mem://a/sub/in.txt", os.path.join("x", "y")])
    assert len(s) == 4                                              # case-sensitive for a virtual path
    s.remap({"mem://a/sub": "mem://b/sub", "mem://a/File.txt": "mem://b/File.txt"})
    assert sorted(p for p in s.paths() if p.startswith("mem://")) == ["mem://a/file.txt", "mem://b/File.txt",
                                                                       "mem://b/sub/in.txt"]
    assert os.path.join("x", "y") in s.paths()
