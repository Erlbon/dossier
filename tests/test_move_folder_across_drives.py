"""A folder moved to another drive is copied, and its originals removed only when every copy succeeded."""
import errno
import os

import pytest

from dossier.core import ops as ops_module
from dossier.core.memfs import MemoryFileSystem
from dossier.core.ops import ExecOptions, Kind, Resolution, execute, plan_move
from dossier.core.undo_log import UndoLog
from dossier.core.vfs import LocalFileSystem

REAL_SAME_VOLUME = ops_module.same_volume          # the autouse fixture below replaces it for the other tests


class OtherDrive(MemoryFileSystem):
    """A rename cannot cross to another drive, as between two disks."""

    def __init__(self):
        super().__init__()
        self.fail_copy_of = set()

    def rename(self, src, dst, *, overwrite=False):
        if self.basename(src).endswith(".dossier-part"):
            return super().rename(src, dst, overwrite=overwrite)
        raise OSError(errno.EXDEV, "cross-device link")

    def open_write(self, path, *, exclusive=False):
        name = self.basename(path)
        if name.endswith(".dossier-part") and name[:-len(".dossier-part")] in self.fail_copy_of:
            raise OSError(5, "disk error", path)
        return super().open_write(path, exclusive=exclusive)


@pytest.fixture(autouse=True)
def other_drive(monkeypatch):
    monkeypatch.setattr(ops_module, "same_volume", lambda fs, a, b: False)


def tree():
    fs = OtherDrive()
    fs.makedirs("mem://dst")
    fs.makedirs("mem://src/Photos/2022/empty")
    fs.put("mem://src/Photos/a.jpg", b"A" * 1000)
    fs.put("mem://src/Photos/2022/b.jpg", b"B" * 2000)
    fs.put("mem://src/Photos/2022/c.jpg", b"C" * 3000)
    return fs


def names(fs, path):
    return sorted(e.name for e in fs.list(path))


def test_the_plan_is_a_copy_of_the_tree_and_one_finishing_step(other_drive):
    fs = tree()
    plan = plan_move(fs, ["mem://src/Photos"], "mem://dst")
    kinds = [op.kind for op in plan.ops]
    assert kinds.count(Kind.COPY) == 3 and kinds[-1] is Kind.FINISH_MOVE and Kind.MOVE not in kinds
    assert all(op.group == 1 for op in plan.ops)
    assert plan.total_work == 6000 + 1 + 3                                    # file bytes, the finishing step, three folders


def test_a_folder_moves_with_everything_in_it_and_the_source_is_gone(other_drive):
    fs = tree()
    res = execute(plan_move(fs, ["mem://src/Photos"], "mem://dst"), fs)
    assert not res.failed and not res.cancelled
    assert names(fs, "mem://dst/Photos") == ["2022", "a.jpg"]
    assert names(fs, "mem://dst/Photos/2022") == ["b.jpg", "c.jpg", "empty"]
    assert fs.stat("mem://dst/Photos/2022/c.jpg").size == 3000
    assert names(fs, "mem://src") == []                                        # files and folders, all gone


def test_one_file_that_cannot_be_copied_keeps_every_original_in_place(other_drive):
    fs = tree()
    fs.fail_copy_of = {"b.jpg"}
    res = execute(plan_move(fs, ["mem://src/Photos"], "mem://dst"), fs, options=ExecOptions(retries=0))
    failed = {os.path.basename(r.op.src.rstrip("/")) or r.op.src: r.error for r in res.failed}
    assert "b.jpg" in failed and any("nothing was removed" in e for e in failed.values())
    assert names(fs, "mem://src/Photos") == ["2022", "a.jpg"]                  # the originals are all still there
    assert names(fs, "mem://src/Photos/2022") == ["b.jpg", "c.jpg", "empty"]
    assert fs.stat("mem://src/Photos/a.jpg").size == 1000


def test_a_skipped_conflict_leaves_that_original_and_its_folder_behind(other_drive):
    fs = tree()
    fs.makedirs("mem://dst/Photos")
    fs.put("mem://dst/Photos/a.jpg", b"older, different")
    plan = plan_move(fs, ["mem://src/Photos"], "mem://dst")
    assert len(plan.conflicts) == 1
    res = execute(plan.resolve(Resolution.SKIP, fs), fs)
    assert not res.failed
    assert fs.stat("mem://dst/Photos/a.jpg").size == len(b"older, different")  # untouched
    assert names(fs, "mem://src/Photos") == ["a.jpg"]                          # the skipped original stays, the rest went
    assert names(fs, "mem://dst/Photos/2022") == ["b.jpg", "c.jpg", "empty"]


def test_moving_into_a_folder_of_the_same_name_merges_like_a_copy(other_drive):
    fs = tree()
    fs.makedirs("mem://dst/Photos/2022")
    fs.put("mem://dst/Photos/2022/x.jpg", b"x")
    res = execute(plan_move(fs, ["mem://src/Photos"], "mem://dst"), fs)
    assert not res.failed
    assert names(fs, "mem://dst/Photos/2022") == ["b.jpg", "c.jpg", "empty", "x.jpg"]
    assert names(fs, "mem://src") == []


def test_the_journal_never_holds_a_step_that_would_delete_the_only_copy(other_drive):
    fs = tree()
    log = UndoLog()
    res = execute(plan_move(fs, ["mem://src/Photos"], "mem://dst"), fs, undo_log=log)
    assert [s.kind for s in res.action.steps] == ["moved"]
    report = log.undo_last(fs)                                                 # cannot be undone across drives...
    assert report.problems                                                     # ...and says so,
    assert names(fs, "mem://dst/Photos") == ["2022", "a.jpg"]                  # but nothing was deleted


def test_progress_counts_the_bytes_and_ends_at_the_total(other_drive):
    fs = tree()
    plan = plan_move(fs, ["mem://src/Photos"], "mem://dst")
    seen = []
    execute(plan, fs, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1] == plan.total_work


def test_with_verify_the_originals_go_only_after_the_read_back_matches(other_drive):
    fs = tree()
    res = execute(plan_move(fs, ["mem://src/Photos"], "mem://dst"), fs, options=ExecOptions(verify=True))
    assert not res.failed and names(fs, "mem://src") == []


def test_on_the_same_volume_a_folder_is_still_one_rename(monkeypatch):
    monkeypatch.setattr(ops_module, "same_volume", lambda fs, a, b: True)
    fs = MemoryFileSystem()
    fs.makedirs("mem://dst")
    fs.makedirs("mem://src/Photos")
    fs.put("mem://src/Photos/a.jpg", b"A")
    plan = plan_move(fs, ["mem://src/Photos"], "mem://dst")
    assert [op.kind for op in plan.ops] == [Kind.MOVE]




@pytest.mark.skipif(os.name != "nt", reason="drive letters")
def test_drive_letters_tell_the_volumes_apart_on_windows():
    fs = LocalFileSystem()
    assert REAL_SAME_VOLUME(fs, r"C:\a\b", r"D:\x") is False
    assert REAL_SAME_VOLUME(fs, r"C:\a\b", r"c:\x\y") is True
    unc = chr(92) * 2                                    # two backslashes: a network path
    assert REAL_SAME_VOLUME(fs, unc + r"server\share\a", unc + r"server\other\b") is False
    assert REAL_SAME_VOLUME(fs, unc + r"server\share\a", unc + r"server\share\b") is True
    assert REAL_SAME_VOLUME(fs, "mem://a", "mem://b") is True


def test_two_folders_of_a_real_disk_are_one_volume(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert REAL_SAME_VOLUME(LocalFileSystem(), str(tmp_path / "a"), str(tmp_path / "b")) is True
