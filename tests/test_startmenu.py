"""The Windows Start menu as a tree of programs (core part)."""
import os

from dossier.core import startmenu as sm


def lnk(folder, name):
    os.makedirs(folder, exist_ok=True)
    (folder / name).write_bytes(b"L")


def test_roots_are_the_two_start_menu_folders_that_exist(tmp_path):
    common = tmp_path / "pd" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    common.mkdir(parents=True)
    env = {"ProgramData": str(tmp_path / "pd"), "APPDATA": str(tmp_path / "missing")}
    assert sm.roots(env) == [str(common)] and sm.roots({}) == []


def test_the_tree_has_groups_first_then_programs_sorted_and_merged_across_the_two_folders(tmp_path):
    a, b = tmp_path / "all", tmp_path / "me"
    lnk(a, "Notepad.lnk")
    lnk(a / "7-Zip", "7-Zip File Manager.lnk")
    lnk(a / "PowerToys", "PowerToys.lnk")
    lnk(b / "PowerToys", "File Locksmith.lnk")                # the same group in the user's own folder
    lnk(b, "Alpha.lnk")
    tree = sm.scan([str(a), str(b)])
    assert [n.name for n in tree] == ["7-Zip", "PowerToys", "Alpha", "Notepad"]
    pt = tree[1]
    assert pt.is_group and [c.name for c in pt.children] == ["File Locksmith", "PowerToys"]
    assert tree[3].path.endswith("Notepad.lnk") and not tree[3].is_group
    assert sm.count_programs(tree) == 5


def test_uninstallers_other_files_and_empty_groups_are_left_out(tmp_path):
    a = tmp_path / "all"
    lnk(a, "Uninstall Thing.lnk")
    lnk(a, "Remove Other.lnk")
    lnk(a / "Group", "Uninstall X.lnk")
    (a / "Notes.txt").parent.mkdir(exist_ok=True)
    (a / "Notes.txt").write_text("x")
    lnk(a, "Real.lnk")
    tree = sm.scan([str(a)])
    assert [n.name for n in tree] == ["Real"]


def test_a_missing_folder_gives_an_empty_tree_and_a_cancel_stops_the_scan(tmp_path):
    assert sm.scan([str(tmp_path / "nope")]) == []
    lnk(tmp_path / "all", "A.lnk")

    class Stop(Exception):
        pass

    def cancel():
        raise Stop()
    try:
        sm.scan([str(tmp_path / "all")], cancel)
    except Stop:
        stopped = True
    else:
        stopped = False
    assert stopped


def test_the_filter_keeps_matching_programs_and_the_groups_above_them(tmp_path):
    a = tmp_path / "all"
    lnk(a / "PowerToys", "File Locksmith.lnk")
    lnk(a / "PowerToys", "PowerRename.lnk")
    lnk(a, "Notepad.lnk")
    tree = sm.scan([str(a)])
    got = sm.filter_tree(tree, "lock")
    assert [n.name for n in got] == ["PowerToys"] and [c.name for c in got[0].children] == ["File Locksmith"]
    assert sm.filter_tree(tree, "") is tree and sm.filter_tree(tree, "zzz") == []
    assert [n.name for n in sm.filter_tree(tree, "NOTE")] == ["Notepad"]


def test_the_program_count_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "MAX_ITEMS", 3)
    for i in range(6):
        lnk(tmp_path / "all", f"P{i}.lnk")
    assert sm.count_programs(sm.scan([str(tmp_path / "all")])) == 3
