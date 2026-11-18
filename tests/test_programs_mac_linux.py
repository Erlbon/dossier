"""Add a Program on the Mac and Linux (review 2026-11-18, section 5): the Mac's apps and the desktop's launchers are offered, and a
Mac app starts through ``open -a``, a launcher by its own command."""
from __future__ import annotations

from dossier.core import desktop_entries, startmenu, tools


def test_a_mac_app_starts_through_open(tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("x", encoding="utf-8")
    assert tools.program_commands("/Applications/TextEdit.app", [str(doc)]) == [["open", "-a", "/Applications/TextEdit.app", str(doc)]]
    assert tools.program_commands("/Applications/Code.app", ["--new-window"]) == [["open", "-a", "/Applications/Code.app", "--args", "--new-window"]]
    assert tools.program_commands("/Applications/Calculator.app/", []) == [["open", "-a", "/Applications/Calculator.app/"]]
    assert tools.program_commands("/usr/bin/gimp", ["x"]) == [["/usr/bin/gimp", "x"]]


def test_a_launcher_starts_by_its_own_command(tmp_path):
    launcher = tmp_path / "viewer.desktop"
    launcher.write_text("[Desktop Entry]\nName=Viewer\nExec=viewer --one %f\n", encoding="utf-8")
    assert tools.program_commands(str(launcher), ["/p/a.jpg", "/p/b.jpg"]) == [["viewer", "--one", "/p/a.jpg"], ["viewer", "--one", "/p/b.jpg"]]


def test_the_macs_apps_are_a_tree_with_folders_as_groups(tmp_path):
    apps = tmp_path / "Applications"
    (apps / "Mail.app" / "Contents").mkdir(parents=True)
    (apps / "Utilities" / "Terminal.app").mkdir(parents=True)
    (apps / "Empty folder").mkdir()
    tree = startmenu.scan_mac_apps([str(apps)])
    assert [n.name for n in tree] == ["Utilities", "Mail"]
    assert tree[0].children[0].name == "Terminal" and tree[0].children[0].path.endswith("Terminal.app")
    assert tree[1].path.endswith("Mail.app")


def test_the_desktops_launchers_are_grouped_as_its_menu_groups_them():
    apps = [desktop_entries.DesktopApp("gimp.desktop", "/u/gimp.desktop", "GIMP", exec="gimp", categories=("Graphics",), icon="gimp"),
            desktop_entries.DesktopApp("calc.desktop", "/u/calc.desktop", "Calculator", exec="calc", categories=("Utility",)),
            desktop_entries.DesktopApp("odd.desktop", "/u/odd.desktop", "Odd", exec="odd")]
    tree = startmenu.scan_launchers(apps)
    assert [(g.name, [n.name for n in g.children]) for g in tree] == [("Accessories", ["Calculator"]), ("Graphics", ["GIMP"]),
                                                                     ("Other", ["Odd"])]
    assert tree[1].children[0].icon == "gimp"
