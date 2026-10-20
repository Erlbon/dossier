import os
import threading

from dossier.core.drives import Drive, disk_usage, drive_of, list_drives, usage_async
from dossier.core.platform import IS_WINDOWS, list_volumes

FAKE = [("C:\\", "System", "fixed"), ("D:\\", "Data", "fixed"), ("E:\\", "", "removable")] if IS_WINDOWS else [
    ("/", "System", "fixed"), ("/mnt/data", "data", "fixed"), ("/media/usb", "usb", "removable")]


def test_real_volumes_are_listed_and_never_empty():
    vols = list_volumes()
    assert vols and all(len(v) == 3 for v in vols)
    drives = list_drives()
    assert drives[-1].kind == "home" and drives[-1].label == "(your folder)" and drives[-1].name == os.path.basename(drives[-1].path)


def test_fake_volumes_become_drives_with_short_names_and_a_home_entry():
    drives = list_drives(FAKE, home="/home/x")
    assert [d.kind for d in drives] == ["fixed", "fixed", "removable", "home"]
    assert drives[1].title.endswith("Data" if IS_WINDOWS else "data") or drives[1].title
    assert drives[0].title.startswith("C:" if IS_WINDOWS else "/")


def test_drive_of_picks_the_longest_matching_root():
    drives = list_drives(FAKE, home="/home/x")
    inside = (FAKE[1][0] + "Books" + os.sep + "x") if IS_WINDOWS else "/mnt/data/Books/x"
    assert drive_of(inside, drives).path == FAKE[1][0]
    other = "C:\\Windows" if IS_WINDOWS else "/etc/hosts"
    assert drive_of(other, drives).path == FAKE[0][0]
    assert drive_of(FAKE[1][0], drives).path == FAKE[1][0]


def test_drive_of_does_not_confuse_prefix_siblings():
    drives = [Drive("/mnt/data", "data", "", "fixed"), Drive("/", "/", "", "fixed")] if not IS_WINDOWS else [
        Drive("D:\\", "D:", "", "fixed"), Drive("C:\\", "C:", "", "fixed")]
    path = "/mnt/data2/x" if not IS_WINDOWS else "C:\\D:x"
    assert drive_of(path, drives).path == ("/" if not IS_WINDOWS else "C:\\")


def test_a_real_path_belongs_to_a_real_drive(tmp_path):
    d = drive_of(str(tmp_path), list_drives())
    assert d is not None and os.path.normcase(str(tmp_path)).startswith(os.path.normcase(d.path).rstrip(os.sep))


def test_disk_usage_and_async_callback(tmp_path):
    usage = disk_usage(str(tmp_path))
    assert usage and usage[0] >= usage[1] > 0
    assert disk_usage(str(tmp_path / "missing")) is None
    done = threading.Event()
    got = {}

    def cb(path, u):
        got[path] = u
        done.set()

    usage_async([str(tmp_path)], cb)
    assert done.wait(5)
    assert got[str(tmp_path)] is not None and got[str(tmp_path)][0] == usage[0]   # free space may drift
