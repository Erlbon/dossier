"""The quarantine folder: where a file goes, how it is put back, and that nothing is deleted or overwritten.

Tests that touch the disk use the one-folder mode inside ``tmp_path``: the drive mode would make ``<drive>:\\Temp\\Quarantine`` for real.
"""
import os

import pytest

from dossier.core import quarantine as q
from dossier.core.ops import Kind, execute
from dossier.core.platform import IS_WINDOWS
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


def make(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return str(path)


# where things go (names only, no disk) --------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not IS_WINDOWS, reason="drive letters")
def test_the_default_is_temp_quarantine_on_the_files_own_drive():
    s = q.Settings()
    assert q.root_for("D:\\Photos\\a.jpg", s) == "D:\\Temp\\Quarantine"
    assert q.destination("D:\\Photos\\2019\\a.jpg", s) == "D:\\Temp\\Quarantine\\Photos\\2019\\a.jpg"
    assert q.destination("c:\\x.txt", s) == "c:\\Temp\\Quarantine\\x.txt"
    assert q.original_of("D:\\Temp\\Quarantine\\Photos\\2019\\a.jpg", s) == "D:\\Photos\\2019\\a.jpg"


@pytest.mark.skipif(not IS_WINDOWS, reason="drive letters")
def test_one_folder_keeps_each_drive_in_a_folder_of_its_own():
    s = q.Settings(q.FOLDER, "E:\\Safe")
    assert q.destination("D:\\Photos\\a.jpg", s) == "E:\\Safe\\D\\Photos\\a.jpg"
    assert q.destination("C:\\Users\\me\\b.txt", s) == "E:\\Safe\\C\\Users\\me\\b.txt"
    assert q.original_of("E:\\Safe\\D\\Photos\\a.jpg", s) == "D:\\Photos\\a.jpg"
    assert q.original_of("E:\\Safe\\Photos\\a.jpg", s) is None             # not a drive folder: where it came from is not known
    assert q.original_of("D:\\Photos\\a.jpg", s) is None


def test_a_folder_mode_without_a_folder_is_the_drive_mode():
    assert q.Settings(q.FOLDER, "   ").cleaned() == q.Settings(q.DRIVE, "")
    assert q.Settings("nonsense", "x").cleaned().mode == q.DRIVE


def test_what_is_already_quarantined_or_cannot_be_is_refused(tmp_path):
    s = q.Settings(q.FOLDER, str(tmp_path / "Q"))
    inside = str(tmp_path / "Q" / "D" / "a.txt")
    assert q.is_quarantined(inside, s) and q.is_quarantined(str(tmp_path / "Q"), s) and not q.is_quarantined(str(tmp_path / "Qx" / "a"), s)
    with pytest.raises(q.QuarantineError, match="already"):
        q.destination(inside, s)
    with pytest.raises(q.QuarantineError, match="drive of this computer"):
        q.destination("sftp://host/a.txt", s)
    with pytest.raises(q.QuarantineError, match="whole drive"):
        q.destination(q.volume_root(str(tmp_path)), s)


# on disk ----------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def tree(tmp_path):
    work = tmp_path / "work"
    a = make(work / "photos" / "2019" / "a.jpg", "A")
    b = make(work / "photos" / "b.jpg", "B")
    c = make(work / "docs" / "c.txt", "C")
    return tmp_path, str(work), a, b, c, q.Settings(q.FOLDER, str(tmp_path / "Q"))


def rel_to_q(tmp_path, path):
    return os.path.relpath(path, tmp_path / "Q")


def test_files_move_into_the_quarantine_in_the_same_layout_and_nothing_is_deleted(tree):
    tmp_path, work, a, b, c, s = tree
    plan = q.plan_quarantine(fs, [a, b, c], s)
    assert plan.title == "Move to quarantine" and not plan.blocking and len([o for o in plan.ops if o.kind is Kind.MOVE]) == 3
    result = execute(plan, fs)
    assert not result.failed
    label = q._label(a)
    expect = [os.path.join(*([label] if label else []), *os.path.relpath(p, q.volume_root(p)).split(os.sep)) for p in (a, b, c)]
    for path, rel in zip((a, b, c), expect):
        assert not os.path.exists(path)
        assert open(os.path.join(tmp_path, "Q", rel)).read() == os.path.basename(path)[0].upper()


def test_a_file_can_be_put_back_even_when_its_folder_is_gone(tree):
    tmp_path, work, a, b, c, s = tree
    execute(q.plan_quarantine(fs, [a], s), fs)
    os.rmdir(os.path.dirname(a))                                           # 2019 is gone
    inside = q.destination(a, s)
    back = q.plan_put_back(fs, [inside], s)
    assert back.title == "Put back" and not back.blocking
    execute(back, fs)
    if IS_WINDOWS:
        assert open(a).read() == "A"
    else:
        pytest.skip("put back from a one-folder quarantine needs drive labels")


def test_a_name_already_in_the_quarantine_is_a_conflict_not_an_overwrite(tree):
    tmp_path, work, a, b, c, s = tree
    execute(q.plan_quarantine(fs, [c], s), fs)
    make(c, "newer C")                                                      # a new file with the same name and place
    plan = q.plan_quarantine(fs, [c], s)
    assert plan.conflicts and not plan.executable                           # the usual conflict dialog decides: nothing is replaced silently
    assert open(q.destination(c, s)).read() == "C"


def test_items_that_cannot_be_quarantined_are_left_out_with_a_reason(tree):
    tmp_path, work, a, b, c, s = tree
    execute(q.plan_quarantine(fs, [a], s), fs)
    plan = q.plan_quarantine(fs, [q.destination(a, s), "sftp://host/x", b], s)
    assert len([o for o in plan.ops if o.kind is Kind.MOVE]) == 1 and any("already" in w for w in plan.warnings) and any("drive of this computer" in w for w in plan.warnings)


def test_a_folder_moves_whole(tree):
    tmp_path, work, a, b, c, s = tree
    folder = os.path.join(work, "photos")
    execute(q.plan_quarantine(fs, [folder], s), fs)
    assert not os.path.exists(folder) and os.path.isfile(os.path.join(q.destination(folder, s), "2019", "a.jpg"))


def test_a_quarantine_folder_that_cannot_be_made_blocks_the_plan(tree, tmp_path):
    work = tree[1]
    afile = make(tmp_path / "notafolder", "x")
    s = q.Settings(q.FOLDER, os.path.join(afile, "inside"))                 # a file is in the way of the folder
    plan = q.plan_quarantine(fs, [tree[2]], s)
    assert plan.blocking and not plan.executable
    assert os.path.exists(tree[2])


def test_planning_makes_nothing_the_plan_does(tree):
    tmp_path, work, a, b, c, s = tree
    plan = q.plan_quarantine(fs, [a], s)
    assert not (tmp_path / "Q").exists() and os.path.exists(a)                 # a dry run leaves the disk alone
    assert plan.ops[0].kind is Kind.MKDIR and plan.ops[0].src == ""
    folders = [o.dst for o in plan.ops if o.kind is Kind.MKDIR]
    assert folders == sorted(folders, key=len) and len(folders) == len(set(folders))   # parents first, each once
    execute(plan, fs)
    assert os.path.isfile(q.destination(a, s))
