"""Replacing duplicates with clones (card 66B). NTFS cannot clone, so the dance is tested with a plain copy as the "clone"."""
import os
import shutil

import pytest

from dossier.core import clone, platform
from dossier.core.duplicates import Group
from dossier.core.progress import CancelToken
from dossier.core.vfs import Entry


def put(path, data, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def fake_clone(src, dst):
    shutil.copyfile(src, dst)


def test_clone_filesystems_are_apfs_btrfs_xfs_and_refs_and_not_ntfs():
    for name in ("apfs", "btrfs", "xfs", "refs", "APFS", "ReFS"):
        assert clone.supports_clone("/x", fstype=lambda p, n=name: n)
    for name in ("ntfs", "ext4", "exfat", "fat32", "", "nfs"):
        assert not clone.supports_clone("/x", fstype=lambda p, n=name: n)


@pytest.mark.skipif(not platform.IS_WINDOWS, reason="the machine's own volume")
def test_this_windows_volume_is_not_reported_as_cloning_unless_it_is_refs(tmp_path):
    name = clone.filesystem_of(str(tmp_path))
    assert clone.supports_clone(str(tmp_path)) == (name == "refs")


def test_the_mount_table_picks_the_longest_mount_point():
    mounts = [("ext4", "/"), ("btrfs", "/data"), ("xfs", "/data/big"), ("apfs", "/dat")]
    assert platform.fstype_from_mounts("/data/big/x/y", mounts) == "xfs"
    assert platform.fstype_from_mounts("/data/other", mounts) == "btrfs"
    assert platform.fstype_from_mounts("/dat", mounts) == "apfs"
    assert platform.fstype_from_mounts("/home/me", mounts) == "ext4"
    assert platform.fstype_from_mounts("/home", []) == ""


def test_clone_file_says_clearly_when_the_system_cannot(tmp_path):
    src = put(tmp_path / "a", b"x" * 100, 1)
    if clone.supports_clone(str(tmp_path)):
        pytest.skip("this volume really clones")
    with pytest.raises(clone.CloneError):
        clone.clone_file(src, str(tmp_path / "b"))
    assert not (tmp_path / "b").exists()


def test_replace_keeps_name_and_dates_and_the_data(tmp_path):
    keep = put(tmp_path / "keep.bin", b"D" * 5000, 5000)
    dup = put(tmp_path / "sub" / "dup.bin", b"D" * 5000, 1234)
    clone.replace_with_clone(keep, dup, clone=fake_clone)
    assert (tmp_path / "sub" / "dup.bin").read_bytes() == b"D" * 5000
    assert int(os.stat(dup).st_mtime) == 1234                                      # its own date, not the kept one's
    assert os.listdir(tmp_path / "sub") == ["dup.bin"]                              # no temp file left
    assert (tmp_path / "keep.bin").exists()


def test_a_file_that_changed_since_the_scan_is_refused(tmp_path):
    keep = put(tmp_path / "keep", b"A" * 100, 1)
    same_size = put(tmp_path / "d1", b"B" * 100, 1)                                # same size, other bytes
    other_size = put(tmp_path / "d2", b"A" * 99, 1)
    for dup, before in ((same_size, b"B" * 100), (other_size, b"A" * 99)):
        with pytest.raises(clone.CloneError, match="changed"):
            clone.replace_with_clone(keep, dup, clone=fake_clone)
        assert open(dup, "rb").read() == before
    assert sorted(os.listdir(tmp_path)) == ["d1", "d2", "keep"]


def test_a_failing_clone_leaves_the_duplicate_and_no_temp_file(tmp_path):
    keep = put(tmp_path / "keep", b"A" * 100, 1)
    dup = put(tmp_path / "dup", b"A" * 100, 2)

    def broken(src, dst):
        open(dst, "wb").write(b"half")
        raise OSError(95, "not supported")
    with pytest.raises(clone.CloneError, match="could not clone"):
        clone.replace_with_clone(keep, dup, clone=broken)
    assert open(dup, "rb").read() == b"A" * 100 and sorted(os.listdir(tmp_path)) == ["dup", "keep"]


def test_the_same_file_and_links_are_refused(tmp_path):
    keep = put(tmp_path / "keep", b"A" * 100, 1)
    with pytest.raises(clone.CloneError, match="same file"):
        clone.replace_with_clone(keep, keep, clone=fake_clone)
    try:
        os.symlink(keep, tmp_path / "link")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(clone.CloneError, match="link"):
        clone.replace_with_clone(keep, str(tmp_path / "link"), clone=fake_clone)


def groups_of(tmp_path):
    a1 = put(tmp_path / "a1", b"A" * 4000, 1)
    a2 = put(tmp_path / "a2", b"A" * 4000, 2)
    a3 = put(tmp_path / "a3", b"A" * 4000, 3)
    b1 = put(tmp_path / "b1", b"B" * 700, 4)
    b2 = put(tmp_path / "b2", b"B" * 700, 5)

    def e(p, size):
        return Entry(name=os.path.basename(p), path=p, is_dir=False, size=size, mtime=os.stat(p).st_mtime)
    return [Group(4000, "x", [e(a1, 4000), e(a2, 4000), e(a3, 4000)]), Group(700, "y", [e(b1, 700), e(b2, 700)])], (a1, a2, a3, b1, b2)


def test_the_plan_counts_files_and_space_and_keeps_the_first_unchecked(tmp_path):
    groups, (a1, a2, a3, b1, b2) = groups_of(tmp_path)
    plan = clone.build_plan(groups, [a2, a3, b2], fstype_of=lambda p: "btrfs")
    assert [(i.keep, i.dup) for i in plan.items] == [(a1, a2), (a1, a3), (b1, b2)]
    assert plan.space == 4000 * 2 + 700 and plan.skipped == []


def test_the_plan_skips_what_cannot_be_done_and_says_why(tmp_path):
    groups, (a1, a2, a3, b1, b2) = groups_of(tmp_path)
    plan = clone.build_plan(groups, [a2, a3, b1, b2], fstype_of=lambda p: "ntfs")
    assert plan.items == [] and len(plan.skipped) == 4 and "NTFS" in plan.skipped[0][1]
    plan = clone.build_plan(groups, [b1, b2], fstype_of=lambda p: "xfs")                # the whole group is chosen
    assert plan.items == [] and "one must stay" in plan.skipped[0][1]


def test_run_plan_replaces_reports_failures_and_goes_on(tmp_path):
    groups, (a1, a2, a3, b1, b2) = groups_of(tmp_path)
    open(a3, "wb").write(b"changed!" * 500)                                              # changed since the scan
    plan = clone.build_plan(groups, [a2, a3, b2], fstype_of=lambda p: "btrfs")
    seen = []
    report = clone.run_plan(plan, clone=fake_clone, progress=lambda d, t: seen.append((d, t)))
    assert report.done == 2 and report.freed == 4700 and not report.cancelled
    assert [p for p, _why in report.failures] == [a3] and open(a3, "rb").read() == b"changed!" * 500
    assert seen[-1] == (3, 3)


def test_run_plan_stops_on_cancel(tmp_path):
    groups, (a1, a2, a3, b1, b2) = groups_of(tmp_path)
    plan = clone.build_plan(groups, [a2, a3], fstype_of=lambda p: "btrfs")
    token = CancelToken()
    token.cancel()
    report = clone.run_plan(plan, cancel=token, clone=fake_clone)
    assert report.cancelled and report.done == 0
