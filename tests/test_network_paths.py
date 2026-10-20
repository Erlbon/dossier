"""A network drive has no recycle bin: deleting there, and the older file an overwrite replaces, are for good, and the
program says so before it does it."""
import os
import shutil

import pytest

from dossier.core import ops as ops_module
from dossier.core.drives import Drive, is_network_path
from dossier.core.ops import Resolution, execute, plan_copy, plan_delete, plan_move
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()
BACKSLASH = chr(92)


class Bin:
    def __init__(self, folder):
        self.folder, self.items = folder, []

    def __call__(self, path):
        os.makedirs(self.folder, exist_ok=True)
        shutil.move(path, os.path.join(self.folder, os.path.basename(path)))
        self.items.append(os.path.basename(path))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# recognising a network path -------------------------------------------------------------------------------
def test_a_unc_path_and_a_mapped_or_mounted_network_drive_are_network_paths():
    drives = [Drive("C:" + BACKSLASH, "C:", "", "fixed"), Drive("Z:" + BACKSLASH, "Z:", "", "network"),
              Drive("D:" + BACKSLASH, "D:", "", "removable")]
    unc = BACKSLASH * 2 + "server" + BACKSLASH + "share" + BACKSLASH + "a.txt"
    if os.name == "nt":
        assert is_network_path(unc, drives)
        assert is_network_path(BACKSLASH * 2 + "?" + BACKSLASH + "UNC" + BACKSLASH + "server" + BACKSLASH + "share", drives)
        assert not is_network_path(BACKSLASH * 2 + "?" + BACKSLASH + "C:" + BACKSLASH + "x", drives)   # an extended LOCAL path
        assert is_network_path("Z:" + BACKSLASH + "Photos", drives) and is_network_path("z:" + BACKSLASH + "x", drives)
        assert not is_network_path("C:" + BACKSLASH + "x", drives) and not is_network_path("D:" + BACKSLASH + "x", drives)


def test_what_is_not_a_real_path_is_not_a_network_path():
    assert not is_network_path("") and not is_network_path("mem://a/b") and not is_network_path("home://")
    assert not is_network_path("zip://C:" + BACKSLASH + "a.zip!/x")


def test_a_failing_drive_list_never_stops_an_operation(monkeypatch):
    import dossier.core.drives as drives_module
    monkeypatch.setattr(drives_module, "list_drives", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert is_network_path("X:" + BACKSLASH + "y") is False


# delete -----------------------------------------------------------------------------------------------------
@pytest.fixture
def pretend_network(tmp_path, monkeypatch):
    """Everything under tmp_path / "net" is on a network drive."""
    net = str(tmp_path / "net")
    monkeypatch.setattr(ops_module, "is_network_path", lambda path: os.path.normcase(path).startswith(os.path.normcase(net)))
    (tmp_path / "net").mkdir()
    (tmp_path / "local").mkdir()
    return tmp_path


def test_deleting_on_a_network_drive_is_permanent_and_the_plan_says_so(pretend_network):
    t = pretend_network
    write(t / "net" / "a.txt", "A")
    write(t / "local" / "b.txt", "B")
    plan = plan_delete(fs, [str(t / "net" / "a.txt"), str(t / "local" / "b.txt")], to_trash=True)
    assert [op.to_trash for op in plan.ops] == [False, True]
    assert any("network drive" in w and "no recycle bin" in w for w in plan.warnings)
    bin_ = Bin(t / "bin")
    res = execute(plan, fs, trasher=bin_)
    assert not res.failed and not (t / "net" / "a.txt").exists() and not (t / "local" / "b.txt").exists()
    assert bin_.items == ["b.txt"]                                   # only the local one was offered to the bin


def test_a_plain_permanent_delete_has_its_usual_warning_only(pretend_network):
    t = pretend_network
    write(t / "net" / "a.txt", "A")
    plan = plan_delete(fs, [str(t / "net" / "a.txt")], to_trash=False)
    assert [op.to_trash for op in plan.ops] == [False] and not any("network" in w for w in plan.warnings)


# overwrite --------------------------------------------------------------------------------------------------
def test_overwriting_on_a_network_drive_deletes_the_older_file_and_the_plan_warns(pretend_network):
    t = pretend_network
    write(t / "local" / "a.txt", "NEW")
    write(t / "net" / "a.txt", "OLD")
    plan = plan_copy(fs, [str(t / "local" / "a.txt")], str(t / "net")).resolve(Resolution.OVERWRITE, fs)
    assert any("network drive" in w and "cannot be undone" in w for w in plan.warnings)
    bin_ = Bin(t / "bin")
    res = execute(plan, fs, trasher=bin_)
    assert not res.failed and (t / "net" / "a.txt").read_text() == "NEW"
    assert bin_.items == [] and sorted(os.listdir(t / "net")) == ["a.txt"]      # no set-aside file left behind


def test_the_warning_appears_once_and_not_for_skip_or_keep_both_or_local_targets(pretend_network):
    t = pretend_network
    write(t / "local" / "a.txt", "NEW")
    write(t / "net" / "a.txt", "OLD")
    write(t / "local" / "b.txt", "NEW")
    plan = plan_copy(fs, [str(t / "local" / "a.txt")], str(t / "net"))
    assert not any("network" in w for w in plan.resolve(Resolution.SKIP, fs).warnings)
    assert not any("network" in w for w in plan.resolve(Resolution.KEEP_BOTH, fs).warnings)
    once = plan.resolve(Resolution.OVERWRITE, fs)
    assert sum("network" in w for w in once.warnings) == 1
    write(t / "local" / "c.txt", "NEW")
    write(t / "local" / "sub" / "c.txt", "OLD")
    local_plan = plan_copy(fs, [str(t / "local" / "c.txt")], str(t / "local" / "sub")).resolve(Resolution.OVERWRITE, fs)
    assert not any("network" in w for w in local_plan.warnings)


def test_a_failed_overwrite_on_a_network_drive_still_leaves_the_older_file(pretend_network):
    t = pretend_network
    write(t / "local" / "a.txt", "NEW")
    write(t / "net" / "a.txt", "OLD")
    plan = plan_copy(fs, [str(t / "local" / "a.txt")], str(t / "net")).resolve(Resolution.OVERWRITE, fs)
    os.remove(t / "local" / "a.txt")                                             # the source vanishes
    res = execute(plan, fs, trasher=Bin(t / "bin"))
    assert [r.status for r in res.results] == ["failed"] and (t / "net" / "a.txt").read_text() == "OLD"


def test_a_move_over_an_older_file_on_a_network_drive_is_also_permanent(pretend_network):
    t = pretend_network
    write(t / "local" / "a.txt", "NEW")
    write(t / "net" / "a.txt", "OLD")
    plan = plan_move(fs, [str(t / "local" / "a.txt")], str(t / "net")).resolve(Resolution.OVERWRITE, fs)
    bin_ = Bin(t / "bin")
    res = execute(plan, fs, trasher=bin_)
    assert not res.failed and (t / "net" / "a.txt").read_text() == "NEW" and bin_.items == []


# the confirmation in the window ------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def test_the_delete_confirmation_says_there_is_no_recycle_bin_on_a_network_drive(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    (left / "a.txt").write_text("A")
    monkeypatch.setattr(ops_module, "is_network_path", lambda path: str(left) in path)
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.delete()
    title, text = dialogs.confirms[-1]
    assert "Network" in title and "no " in text and "permanently" in text and "cannot be brought back" in text


def test_a_mixed_delete_names_how_many_go_where(world, monkeypatch):
    win, dialogs, left, right, tmp = world
    (left / "net.txt").write_text("A")
    (left / "loc.txt").write_text("B")
    monkeypatch.setattr(ops_module, "is_network_path", lambda path: path.endswith("net.txt"))
    win.left.refresh()
    win.select_all()
    win.delete()
    text = dialogs.confirms[-1][1]
    assert "1 of 2" in text and "The other 1 go to the" in text


def test_a_normal_delete_still_asks_about_the_recycle_bin(world):
    win, dialogs, left, right, tmp = world
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    win.delete()
    assert dialogs.confirms[-1][0] == "Delete" and "to the" in dialogs.confirms[-1][1]
