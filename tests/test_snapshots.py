"""Earlier versions that are folders (card 67B): the core finder, the read-only rule, and the window's command."""
import os
from datetime import datetime

import pytest

from dossier.core import snapshots as snap
from dossier.core.vfs import LocalFileSystem


def put(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def local(*args):
    return datetime(*args).timestamp()


def test_names_are_read_for_their_time():
    assert snap.parse_moment("GMT+01_2026-11-18_0100") == local(2026, 11, 18, 1, 0)
    assert snap.parse_moment("GMT+01-2026.11.18-01.30.05") == local(2026, 11, 18, 1, 30, 5)
    assert snap.parse_moment("zfs-auto-snap_daily-2026-11-17-0615") == local(2026, 11, 17, 6, 15)
    assert snap.parse_moment("autosnap_2026-11-18_01:00:01_daily") == local(2026, 11, 18, 1, 0, 1)
    assert snap.parse_moment("20261118-0230") == local(2026, 11, 18, 2, 30)
    assert snap.parse_moment("2026-11-18") == local(2026, 11, 18)
    assert snap.parse_moment("before-upgrade") is None
    assert snap.parse_moment("2026-13-45_9999") is None                 # not a date


def test_a_synology_share_lists_snapshots_that_hold_the_file_newest_first(tmp_path):
    share = tmp_path / "share"
    item = put(share / "docs" / "a.txt", "now")
    put(share / "#snapshot" / "GMT+01-2026.11.16-01.00.00" / "docs" / "a.txt", "old")
    put(share / "#snapshot" / "GMT+01-2026.11.18-01.00.00" / "docs" / "a.txt", "newer")
    (share / "#snapshot" / "GMT+01-2026.11.17-01.00.00" / "docs").mkdir(parents=True)        # this one does not hold a.txt
    found = snap.find_earlier_versions(str(item))
    assert [m.name for m in found.moments] == ["GMT+01-2026.11.18-01.00.00", "GMT+01-2026.11.16-01.00.00"]
    assert all(m.kind == snap.KIND_NAS for m in found.moments)
    assert found.moments[0].when == local(2026, 11, 18, 1, 0)
    assert open(found.moments[0].path).read() == "newer"
    assert found.moments[0].folder == str(share / "#snapshot" / "GMT+01-2026.11.18-01.00.00")


def test_a_folder_is_found_too_and_a_dot_snapshot_in_a_parent_works(tmp_path):
    vol = tmp_path / "vol"
    put(vol / "proj" / "sub" / "f.txt")
    put(vol / ".snapshot" / "hourly.2026-11-18_0100" / "proj" / "sub" / "f.txt")
    put(vol / "~snapshot" / "daily.2026-11-17_0000" / "proj" / "sub" / "f.txt")
    found = snap.find_earlier_versions(str(vol / "proj" / "sub"))
    assert [m.name for m in found.moments] == ["hourly.2026-11-18_0100", "daily.2026-11-17_0000"]
    assert os.path.isdir(found.moments[0].path)


def test_zfs_snapshot_folder_opened_by_name(tmp_path):
    ds = tmp_path / "tank"
    item = put(ds / "d" / "f.txt")
    put(ds / ".zfs" / "snapshot" / "auto-2026-11-18_01-00" / "d" / "f.txt")
    put(ds / ".zfs" / "snapshot" / "manual" / "d" / "f.txt")
    found = snap.find_earlier_versions(str(item))
    assert {m.name for m in found.moments} == {"auto-2026-11-18_01-00", "manual"}
    assert found.moments[0].name == "auto-2026-11-18_01-00" or found.moments[0].kind == snap.KIND_ZFS
    assert all(m.kind == snap.KIND_ZFS for m in found.moments)


def test_snapper_uses_info_xml_in_utc_and_the_snapshot_subfolder(tmp_path):
    vol = tmp_path / "home"
    item = put(vol / "me" / "n.txt")
    for n, date, desc in ((3, "2026-11-10 08:00:00", "before update"), (7, "2026-11-12 09:30:00", "")):
        base = vol / ".snapshots" / str(n)
        put(base / "snapshot" / "me" / "n.txt")
        put(base / "info.xml", f"<snapshot><num>{n}</num><date>{date}</date><description>{desc}</description></snapshot>")
    (vol / ".snapshots" / "9" / "snapshot").mkdir(parents=True)                           # holds nothing
    found = snap.find_earlier_versions(str(item))
    assert [m.name for m in found.moments] == ["7", "3  before update"]
    assert found.moments[1].when == datetime(2026, 11, 10, 8, 0, 0, tzinfo=snap.timezone.utc).timestamp()
    assert found.moments[0].path == str(vol / ".snapshots" / "7" / "snapshot" / "me" / "n.txt")
    assert all(m.kind == snap.KIND_BTRFS for m in found.moments)


def test_a_name_that_is_no_date_falls_back_to_the_folders_time(tmp_path):
    share = tmp_path / "s"
    item = put(share / "a.txt")
    old = put(share / "#snapshot" / "weekly-keep" / "a.txt").parent
    os.utime(old, (1_700_000_000, 1_700_000_000))
    found = snap.find_earlier_versions(str(item))
    assert found.moments[0].when == pytest.approx(1_700_000_000)


def test_the_item_missing_from_every_snapshot_gives_nothing_and_says_what_was_seen(tmp_path):
    share = tmp_path / "s"
    item = put(share / "a.txt")
    (share / "#snapshot" / "GMT+01-2026.11.18-01.00.00").mkdir(parents=True)
    found = snap.find_earlier_versions(str(item))
    assert not found.moments and found.kinds_seen == {snap.KIND_NAS}
    assert "none of the snapshots holds it" in snap.nothing_found_text(found, "a.txt")
    plain = put(tmp_path / "plain" / "b.txt")
    none = snap.find_earlier_versions(str(plain))
    assert not none.moments and not none.kinds_seen
    text = snap.nothing_found_text(none, "b.txt")
    assert "#snapshot" in text and ".zfs" in text and ".snapshots" in text
    assert str(tmp_path) not in text                                                       # kinds, not every path


def test_cancel_stops_the_search(tmp_path):
    share = tmp_path / "s"
    item = put(share / "a.txt")
    put(share / "#snapshot" / "GMT+01-2026.11.18-01.00.00" / "a.txt")
    assert snap.find_earlier_versions(str(item), cancel=lambda: True).moments == []


def test_an_item_already_in_a_snapshot_is_not_searched(tmp_path):
    inside = put(tmp_path / "s" / "#snapshot" / "GMT+01-2026.11.18-01.00.00" / "a.txt")
    found = snap.find_earlier_versions(str(inside))
    assert found.inside_snapshot and not found.moments
    assert "already in an earlier version" in snap.nothing_found_text(found, "a.txt")


@pytest.mark.parametrize("path,inside", [
    ("/nas/share/#snapshot/GMT+01-2026.11.18-01.00.00/a.txt", True),
    ("C:" + chr(92) + "x" + chr(92) + ".snapshot" + chr(92) + "daily.1" + chr(92) + "f", True),
    ("/tank/.zfs/snapshot/monthly/f", True),
    ("/home/.snapshots/12/snapshot/f", True),
    ("/home/.snapshots/12/info.xml", True),
    ("/home/.snapshots", False),                                  # the folder snapper keeps, not a snapshot yet
    ("/home/.snapshots/notes/f", False),
    ("/data/snapshot/f", False),
    ("/data/my.snapshots/f", False),
])
def test_what_is_inside_a_snapshot_by_name(path, inside):
    assert snap.is_inside_snapshot(path) is inside


def test_a_snapshot_is_read_only_for_every_command(tmp_path):
    fs = LocalFileSystem()
    plain = tmp_path / "plain"
    inside = tmp_path / "s" / "#snapshot" / "GMT+01-2026.11.18-01.00.00"
    plain.mkdir()
    inside.mkdir(parents=True)
    assert fs.is_writable(str(plain)) and not fs.is_writable(str(inside)) and not fs.is_writable(str(inside / "a.txt"))
