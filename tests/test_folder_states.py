"""Remembered folder states: keeping, listing, forgetting, and telling what changed since (card 65)."""
import os

from dossier.core import folder_states as fs_
from dossier.core import manifest
from dossier.core.vfs import LocalFileSystem


def item(rel, digest, size=10, mtime=100.0):
    return manifest.Item(rel, size, mtime, digest)


def by_status(changes):
    out = {}
    for r in changes.rows:
        out.setdefault(r.status, []).append(r)
    return out


def test_added_removed_changed_moved_and_unchanged_left_out():
    old = [item("same.txt", "a"), item("edit.txt", "b", 10), item("gone.txt", "c"), item("old/place.txt", "d"), item("dup1.txt", "e")]
    new = [item("same.txt", "a"), item("edit.txt", "x", 12), item("new.txt", "n"), item("new/place.txt", "d"), item("dup1.txt", "e")]
    got = fs_.compare(old, new)
    s = by_status(got)
    assert [r.rel for r in s[fs_.ADDED]] == ["new.txt"]
    assert [r.rel for r in s[fs_.REMOVED]] == ["gone.txt"]
    assert [(r.rel, r.old_size, r.size) for r in s[fs_.CHANGED]] == [("edit.txt", 10, 12)]
    assert [(r.rel, r.old_rel) for r in s[fs_.MOVED]] == [("new/place.txt", "old/place.txt")]
    assert got.same == 2 and len(got.rows) == 4                    # the moved file is not also listed as added and removed
    assert (got.files_before, got.files_now) == (5, 5)


def test_a_new_time_with_the_same_content_is_not_a_change():
    got = fs_.compare([item("a.txt", "a", mtime=100)], [item("a.txt", "a", mtime=5000)])
    assert got.rows == [] and got.same == 1 and got.touched == 1


def test_a_file_that_could_not_be_read_is_compared_by_size_and_time():
    bad_old = manifest.Item("x.bin", 5, 100.0, "", "denied")
    assert fs_.compare([bad_old], [manifest.Item("x.bin", 5, 100.0, "", "denied")]).rows == []
    got = fs_.compare([bad_old], [manifest.Item("x.bin", 9, 100.0, "", "denied")])
    assert [r.status for r in got.rows] == [fs_.CHANGED]


def test_two_copies_moved_pair_up_one_to_one_and_the_extra_one_is_added():
    old = [item("a/one.txt", "h")]
    new = [item("b/one.txt", "h"), item("c/other.txt", "h")]
    got = fs_.compare(old, new)
    s = by_status(got)
    assert [r.rel for r in s[fs_.MOVED]] == ["b/one.txt"]           # the same name wins
    assert [r.rel for r in s[fs_.ADDED]] == ["c/other.txt"] and fs_.REMOVED not in s


def test_case_insensitive_names_are_the_same_file():
    got = fs_.compare([item("Doc.TXT", "a")], [item("doc.txt", "a")], case_sensitive=False)
    assert got.rows == [] and got.same == 1


def test_save_list_load_and_forget(tmp_path):
    folder = tmp_path / "work"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_bytes(b"hello")
    (folder / "sub" / "b.txt").write_bytes(b"world!")
    other = tmp_path / "other"
    other.mkdir()
    (other / "o.txt").write_bytes(b"o")
    states = tmp_path / "settings" / "folder-states"
    fs = LocalFileSystem()
    first = fs_.save_state(str(states), str(folder), manifest.build(fs, str(folder)), when=1000.0)
    second = fs_.save_state(str(states), str(folder), manifest.build(fs, str(folder)), when=2000.0)
    third = fs_.save_state(str(states), str(other), manifest.build(fs, str(other)), when=1500.0)
    assert first.id != second.id and (first.files, first.bytes) == (2, 11)
    assert [s.id for s in fs_.list_states(str(states), str(folder))] == [second.id, first.id]      # newest first, this folder only
    assert [s.id for s in fs_.list_states(str(states))] == [second.id, third.id, first.id]
    assert sorted(i.rel for i in fs_.load_items(first)) == ["a.txt", "sub/b.txt"]
    again = fs_.save_state(str(states), str(folder), [], when=1000.0)                              # same second: a new id, nothing overwritten
    assert again.id not in (first.id, second.id)
    fs_.forget_state(first)
    assert first.id not in [s.id for s in fs_.list_states(str(states))]
    assert not os.path.exists(first.csv_path)
    fs_.forget_state(first)                                                                       # forgetting twice is harmless
    assert os.listdir(str(folder)) == ["a.txt", "sub"] or sorted(os.listdir(str(folder))) == ["a.txt", "sub"]   # nothing was written there


def test_a_state_missing_its_manifest_or_with_a_broken_note_is_skipped(tmp_path):
    states = tmp_path / "s"
    state = fs_.save_state(str(states), str(tmp_path / "f"), [item("a", "a")], when=10.0)
    (states / "junk.json").write_text("not json", encoding="utf-8")
    os.remove(state.csv_path)
    assert fs_.list_states(str(states)) == []
