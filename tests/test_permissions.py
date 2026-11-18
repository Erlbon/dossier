"""Change permissions (card 53): the mode arithmetic, the plan, writing it, and the Permissions tab of Properties."""
import os
import stat
import sys
from types import SimpleNamespace

import pytest

from dossier.core import permissions as pm
from dossier.core import properties
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()
F, D = stat.S_IFREG, stat.S_IFDIR
OWNER_X, GROUP_R, GROUP_W, OTHERS_R = 0o100, 0o040, 0o020, 0o004


def test_modes_as_text_and_back():
    assert pm.format_mode(0o755) == "rwxr-xr-x" and pm.format_mode(0o600) == "rw-------" and pm.format_mode(0o100644) == "rw-r--r--"
    assert pm.parse_mode("755") == 0o755 and pm.parse_mode("rw-r-----") == 0o640 and pm.parse_mode("0644") == 0o644
    for bad in ("", "999", "rwxrwxrwxx", "rwxr-xr-q", "abc"):
        with pytest.raises(ValueError):
            pm.parse_mode(bad)


def test_new_mode_keeps_special_bits_and_untouched_bits():
    assert pm.new_mode(0o4644, OWNER_X, 0) == 0o4744                       # set-user-id stays
    assert pm.new_mode(0o755, 0, 0o022) == 0o755 & ~0o022
    assert pm.new_mode(0o644, 0o111, 0) == 0o755
    assert pm.new_mode(0o644, GROUP_W, GROUP_W) == 0o664                  # a bit asked for both ways is given


def test_a_folder_inside_keeps_its_run_bits_but_a_chosen_folder_does_not():
    assert pm.new_mode(0o755, 0, 0o111, is_dir=True, inside=True) == 0o755
    assert pm.new_mode(0o644, 0o111, 0, is_dir=True, inside=True) == 0o644
    assert pm.new_mode(0o755, 0, 0o111, is_dir=True, inside=False) == 0o644
    assert pm.new_mode(0o644, 0o111, 0, is_dir=False, inside=True) == 0o755               # a file inside gets run


def fake_tree():
    """/r (folder 755), /r/a.sh (file 644), /r/sub (folder 750), /r/sub/b.txt (file 600), /r/link (a link)."""
    modes = {"/r": D | 0o755, "/r/a.sh": F | 0o644, "/r/sub": D | 0o750, "/r/sub/b.txt": F | 0o600, "/r/link": stat.S_IFLNK | 0o777}
    kids = {"/r": ["a.sh", "sub", "link"], "/r/sub": ["b.txt"]}

    def lstat(p):
        p = p.replace(os.sep, "/")
        if p not in modes:
            raise FileNotFoundError(2, "No such file")
        return SimpleNamespace(st_mode=modes[p], st_gid=100)

    def listdir(p):
        return kids.get(p.replace(os.sep, "/"), [])
    return lstat, listdir


def test_plan_walks_a_tree_skips_links_and_spares_inner_folders():
    lstat, listdir = fake_tree()
    got = pm.plan(["/r"], on=0o111, off=0o022, recursive=True, lstat=lstat, listdir=listdir)
    by = {c.path.replace(os.sep, "/"): c for c in got}
    assert set(by) == {"/r", "/r/a.sh", "/r/sub", "/r/sub/b.txt"}                      # the link is not in it
    assert by["/r"].new_mode & 0o777 == 0o755                                            # the chosen folder gets what was asked
    assert by["/r/a.sh"].new_mode & 0o777 == 0o755                                       # a file gets run, group/others lose write
    assert by["/r/sub"].new_mode & 0o777 == 0o750                                        # an inner folder keeps its own run bits
    assert by["/r/sub/b.txt"].new_mode & 0o777 == 0o711                                  # a file inside gets run
    only = pm.plan(["/r"], on=OTHERS_R, lstat=lstat, listdir=listdir)
    assert [c.path.replace(os.sep, "/") for c in only] == ["/r"]                          # not recursive: only the item


def test_plan_names_an_unreadable_item_and_can_be_cancelled():
    lstat, listdir = fake_tree()
    got = pm.plan(["/nope"], on=0o4, lstat=lstat, listdir=listdir)
    assert got[0].problem and not got[0].changes
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        pm.plan(["/r"], on=0o4, recursive=True, cancel=token, lstat=lstat, listdir=listdir)


def test_apply_writes_each_change_lists_failures_and_orders_closing_folders_last():
    lstat, listdir = fake_tree()
    plan = pm.plan(["/r"], off=0o100, recursive=False, lstat=lstat, listdir=listdir)
    plan += pm.plan(["/r/a.sh"], on=0o1, lstat=lstat, listdir=listdir)
    plan += pm.plan(["/r/sub/b.txt"], on=0o4, lstat=lstat, listdir=listdir)
    done = []

    def chmod(path, mode):
        if path.endswith("b.txt"):
            raise PermissionError(1, "Operation not permitted")
        done.append((path.replace(os.sep, "/"), mode))
    result = pm.apply(plan, chmod=chmod)
    assert result.done == 2 and [p.replace(os.sep, "/") for p, _w in result.failed] == ["/r/sub/b.txt"]
    assert done[0] == ("/r/a.sh", 0o645)
    assert done[-1][0] == "/r"                                                           # the folder losing its run bit is last
    assert done[-1][1] & 0o100 == 0


def test_apply_changes_the_group_with_chown_and_cancel_stops_it():
    c = pm.PermChange("/x", False, F | 0o644, F | 0o644, old_gid=1, new_gid=7)
    calls = []
    result = pm.apply([c], chmod=lambda *a: calls.append("chmod"), chown=lambda p, u, g: calls.append((u, g)))
    assert result.done == 1 and calls == [(-1, 7)]                                       # the owner (-1) is never changed
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        pm.apply([c], cancel=token, chmod=lambda *a: None, chown=lambda *a: None)


def test_read_info_counts_each_bit_and_marks_mixed_items():
    st = {"/a": SimpleNamespace(st_mode=F | 0o644, st_uid=1, st_gid=5), "/b": SimpleNamespace(st_mode=D | 0o755, st_uid=1, st_gid=5)}
    info = pm.read_info(["/a", "/b"], lstat=lambda p: st[p], user_name=lambda u: "erl", group_name=lambda g: "staff", my_groups=[5, 20])
    assert info.count == 2 and info.folders == 1 and info.owners == ["erl"] and info.groups == [(5, "staff")]
    assert info.state(0o400) == 2 and info.state(0o100) == 1 and info.state(0o002) == 0
    assert [g for g, _n in info.mine] == [5, 20]


@pytest.mark.skipif(sys.platform == "win32", reason="chmod only toggles read-only on Windows")
def test_real_chmod_through_a_plan(tmp_path):
    top = tmp_path / "top"
    (top / "inner").mkdir(parents=True)
    f = top / "inner" / "run.sh"
    f.write_text("echo hi")
    os.chmod(f, 0o644)
    got = pm.plan([str(top)], on=0o111, recursive=True)
    result = pm.apply(got)
    assert not result.failed
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o755 and os.access(top / "inner", os.X_OK)


# the Permissions tab -----------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from dossier.gui.properties import PropertiesDialog  # noqa: E402


def test_the_permissions_tab_is_there_on_posix_and_not_on_windows(world):
    win, _dialogs, _left, _right, tmp_path = world
    world = win
    (tmp_path / "f.txt").write_text("x")
    on = properties.gather(fs, [str(tmp_path / "f.txt")], posix=True)
    off = properties.gather(fs, [str(tmp_path / "f.txt")], posix=False)
    tabs = lambda d: [PropertiesDialog(world, d, set()).tabs.tabText(i) for i in range(PropertiesDialog(world, d, set()).tabs.count())]  # noqa: E731
    assert "Permissions" in tabs(on) and "Permissions" not in tabs(off) and off.perm is None


def test_ticks_ask_only_for_what_was_changed_and_apply_hands_over_a_request(world):
    from PyQt6.QtCore import Qt
    win, _dialogs, _left, _right, tmp_path = world
    world = win
    d = tmp_path / "dir"
    d.mkdir()
    data = properties.gather(fs, [str(d)], posix=True)
    dlg = PropertiesDialog(world, data, set())
    assert dlg.permission_masks() == (0, 0) and dlg.perm_inside.isVisibleTo(dlg.perm_tab) is True
    dlg.perm_boxes[OTHERS_R].setCheckState(Qt.CheckState.Checked if dlg.perm_initial[OTHERS_R] != Qt.CheckState.Checked else Qt.CheckState.Unchecked)
    on, off = dlg.permission_masks()
    assert (on | off) == OTHERS_R
    dlg.perm_inside.setChecked(True)
    dlg._save_permissions()
    assert dlg.perm_request == (on, off, -1, True)


def test_the_window_plans_confirms_then_writes(world, monkeypatch):
    win, dialogs, _left, _right, tmp_path = world
    f = tmp_path / "f.sh"
    f.write_text("x")
    written = []
    monkeypatch.setattr(pm, "apply", lambda plan, cancel=None, progress=None, **k: written.append(len(plan)) or pm.Applied(done=len(plan)))
    dialogs.confirm_answer = False                                                       # refused: nothing is written
    win._change_permissions([str(f)], 0o777, 0, -1, False)
    pump(win, lambda: dialogs.confirms)
    pump(win, timeout=0.3)
    assert dialogs.confirms[-1][0] == "Change Permissions" and "will change" in dialogs.confirms[-1][1] and written == []
    dialogs.confirm_answer = True
    win._change_permissions([str(f)], 0o777, 0, -1, False)
    pump(win, lambda: written)
    assert written == [1]
