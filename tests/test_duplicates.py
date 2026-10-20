"""Finding files with the same content (core): the three steps, what they must never report, and the keep rules."""
import os

import pytest

from dossier.core import duplicates as dup
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


def put(path, data, mtime=1_700_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


def names(group):
    return [os.path.basename(e.path) for e in group.files]


def test_the_same_content_under_other_names_and_folders_is_a_group(tmp_path):
    put(tmp_path / "a" / "photo.jpg", b"PIC" * 1000, 100)
    put(tmp_path / "b" / "copy of photo.jpg", b"PIC" * 1000, 200)
    put(tmp_path / "b" / "other.jpg", b"DIFFERENT" * 400)                        # 3600 bytes: another size, left alone
    put(tmp_path / "c" / "alone.txt", b"unique")
    r = dup.find_duplicates(fs, [str(tmp_path)])
    assert len(r.groups) == 1 and names(r.groups[0]) == ["photo.jpg", "copy of photo.jpg"]          # the oldest first
    assert r.groups[0].size == 3000 and r.groups[0].wasted == 3000 and r.wasted == 3000 and r.copies == 2
    assert r.scanned >= 4 and r.unreadable == 0


def test_the_same_size_with_different_content_is_never_reported(tmp_path):
    put(tmp_path / "x.bin", b"A" * 5000)
    put(tmp_path / "y.bin", b"B" * 5000)
    put(tmp_path / "z.bin", b"A" * 4999 + b"B")                                  # differs only in the last byte
    r = dup.find_duplicates(fs, [str(tmp_path)])
    assert r.groups == [] and r.candidates == 3


def test_big_files_that_differ_only_in_the_middle_are_told_apart_by_the_full_read(tmp_path):
    size = 400 * 1024
    base = bytearray(b"S" * size)
    other = bytearray(base)
    other[size // 2] = ord("X")                                                  # the first and last 64 KB are identical
    put(tmp_path / "one.dat", bytes(base))
    put(tmp_path / "two.dat", bytes(other))
    put(tmp_path / "three.dat", bytes(base))
    r = dup.find_duplicates(fs, [str(tmp_path)])
    assert len(r.groups) == 1 and sorted(names(r.groups[0])) == ["one.dat", "three.dat"]
    assert r.bytes_read >= 2 * size                                              # the two that matched were read completely


def test_a_file_that_is_alone_with_its_size_is_never_opened(tmp_path, monkeypatch):
    put(tmp_path / "a.bin", b"1" * 100)
    put(tmp_path / "b.bin", b"2" * 200)
    opened = []
    real = fs.open_read
    monkeypatch.setattr(type(fs), "open_read", lambda self, p: (opened.append(p), real(p))[1])
    r = dup.find_duplicates(fs, [str(tmp_path)])
    assert r.groups == [] and opened == [] and r.bytes_read == 0


def test_empty_files_and_files_under_the_minimum_are_left_out_and_a_name_filter_narrows(tmp_path):
    for n in ("e1", "e2"):
        put(tmp_path / n, b"")
    put(tmp_path / "s1.txt", b"tiny")
    put(tmp_path / "s2.txt", b"tiny")
    put(tmp_path / "p1.jpg", b"J" * 3000)
    put(tmp_path / "p2.jpg", b"J" * 3000)
    assert [g.size for g in dup.find_duplicates(fs, [str(tmp_path)]).groups] == [3000, 4]          # biggest waste first, no empties
    assert [g.size for g in dup.find_duplicates(fs, [str(tmp_path)], min_size=1000).groups] == [3000]
    assert [g.size for g in dup.find_duplicates(fs, [str(tmp_path)], name="*.txt").groups] == [4]


def test_two_folders_are_compared_with_each_other_and_overlapping_folders_count_a_file_once(tmp_path):
    put(tmp_path / "left" / "a.dat", b"Z" * 2000)
    put(tmp_path / "right" / "a-backup.dat", b"Z" * 2000)
    r = dup.find_duplicates(fs, [str(tmp_path / "left"), str(tmp_path / "right")])
    assert len(r.groups) == 1 and r.copies == 2
    again = dup.find_duplicates(fs, [str(tmp_path), str(tmp_path / "left")])            # "left" is inside the first folder
    assert again.copies == 2 and len(again.groups) == 1


def test_a_file_that_cannot_be_read_is_counted_and_left_out(tmp_path, monkeypatch):
    a, b, c = (put(tmp_path / n, b"Q" * 3000) for n in ("a", "b", "c"))
    real = fs.open_read

    def picky(self, p):
        if p == b:
            raise PermissionError("locked")
        return real(p)
    monkeypatch.setattr(type(fs), "open_read", picky)
    r = dup.find_duplicates(fs, [str(tmp_path)])
    assert r.unreadable == 1 and len(r.groups) == 1 and sorted(names(r.groups[0])) == ["a", "c"]


def test_cancelling_stops_the_search(tmp_path):
    for i in range(6):
        put(tmp_path / f"f{i}", b"C" * 3000)
    token = CancelToken()
    seen = []

    def progress(stage, done, total):
        seen.append(stage)
        token.cancel()
    with pytest.raises(Cancelled):
        dup.find_duplicates(fs, [str(tmp_path)], cancel=token, progress=progress)
    assert seen


def test_progress_names_the_stages_and_ends_at_the_total(tmp_path):
    put(tmp_path / "big1", b"B" * 300_000)
    put(tmp_path / "big2", b"B" * 300_000)
    stages = []
    dup.find_duplicates(fs, [str(tmp_path)], progress=lambda s, d, t: stages.append((s, d, t)))
    assert {s for s, _d, _t in stages} >= {"Comparing the start and the end of files", "Reading whole files that look the same"}
    last = [x for x in stages if x[0] == "Reading whole files that look the same"][-1]
    assert last[1] == last[2] == 600_000


def test_keep_rules_and_the_groups_that_would_lose_everything(tmp_path):
    put(tmp_path / "old" / "x.dat", b"K" * 2000, 100)
    put(tmp_path / "new" / "x.dat", b"K" * 2000, 300)
    put(tmp_path / "mid" / "deeper" / "x.dat", b"K" * 2000, 200)
    put(tmp_path / "n1.dat", b"L" * 2500, 500)
    put(tmp_path / "n2.dat", b"L" * 2500, 400)
    r = dup.find_duplicates(fs, [str(tmp_path)])
    first = r.groups[0]
    rel = lambda paths: sorted(os.path.relpath(p, tmp_path).replace(os.sep, "/") for p in paths)       # noqa: E731
    assert rel(dup.extras([first], "oldest")) == ["mid/deeper/x.dat", "new/x.dat"]
    assert rel(dup.extras([first], "newest")) == ["mid/deeper/x.dat", "old/x.dat"]
    assert rel(dup.extras([first], "shortest")) == ["mid/deeper/x.dat", "new/x.dat"]            # a tie in length: the older one stays
    assert dup.groups_left_empty(r.groups, [e.path for e in first.files]) == [first]
    assert dup.groups_left_empty(r.groups, dup.extras(r.groups, "oldest")) == []                  # the keep rule never removes a group
    assert len(dup.extras(r.groups, "newest")) == sum(len(g.files) - 1 for g in r.groups)
