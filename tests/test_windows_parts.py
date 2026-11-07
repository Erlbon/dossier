"""The "Windows" group of Add a Program (the owner, 2026-11-07: "No one is going to remember the exe names"): parts of Windows that are
not in the Start menu, such as System, Network, Windows Security, Device Manager and Services, one click away on the tools bar, each
with its own icon."""
import os

import pytest

from dossier.core import startmenu as SM
from dossier.core import tools as T
from dossier.core import windows_parts as W


def test_the_group_names_the_parts_people_look_for_and_each_has_a_program_and_an_icon():
    group = W.windows_group(exists=lambda path: True, system_root="C:" + os.sep + "Windows")
    assert group.is_group and group.name == "Windows"
    names = [n.name for n in group.children]
    for wanted in ("System", "Network and Internet", "Network Connections", "Windows Security", "Firewall", "Device Manager",
                   "Services", "Event Viewer", "Disk Management", "Environment Variables", "Advanced System Settings"):
        assert wanted in names, wanted
    assert names == sorted(names, key=str.casefold) and len(set(names)) == len(names)
    for node in group.children:
        assert node.path and node.icon and not node.is_group, node.name


def test_a_console_is_started_by_its_full_path_and_a_settings_page_by_its_address():
    root = "C:" + os.sep + "Windows"
    by_name = {n.name: n for n in W.windows_group(exists=lambda path: True, system_root=root).children}
    assert by_name["Device Manager"].path == os.path.join(root, "System32", "devmgmt.msc")
    assert by_name["Device Manager"].icon == os.path.join(root, "System32", "devmgr.dll") + ",5"
    assert by_name["System"].path == "ms-settings:about"
    assert by_name["Environment Variables"].path == os.path.join(root, "System32", "rundll32.exe")
    assert by_name["Environment Variables"].args == "sysdm.cpl,EditEnvironmentVariables"


def test_a_part_whose_program_is_not_on_this_computer_is_left_out():
    root = "C:" + os.sep + "Windows"
    group = W.windows_group(exists=lambda path: not path.endswith("devmgmt.msc"), system_root=root)
    names = [n.name for n in group.children]
    assert "Device Manager" not in names and "Services" in names and "System" in names     # an address needs no file


def test_an_icon_is_a_file_or_a_file_and_an_index():
    assert W.icon_spec("C:" + os.sep + "x.dll,5") == ("C:" + os.sep + "x.dll", 5)
    assert W.icon_spec("C:" + os.sep + "x.dll,-201") == ("C:" + os.sep + "x.dll", -201)
    assert W.icon_spec("C:" + os.sep + "Program Files" + os.sep + "a,b.exe") == ("C:" + os.sep + "Program Files" + os.sep + "a,b.exe", None)
    assert W.icon_spec("") == ("", None)


def test_a_tool_keeps_its_icon_in_the_settings_and_old_settings_still_load():
    tool = T.Tool("Device Manager", "devmgmt.msc", "", "", icon="devmgr.dll,5")
    assert T.loads(T.dumps([tool])) == [tool]
    old = '[{"type":"tool","name":"Notepad","command":"notepad.exe","args":"","start_in":""}]'
    assert T.loads(old) == [T.Tool("Notepad", "notepad.exe")]
    assert "icon" not in T.dumps([T.Tool("Notepad", "notepad.exe")])           # nothing stored when there is none


# in the window -----------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_picking_a_part_of_windows_adds_a_tool_with_its_program_arguments_and_icon(world, monkeypatch):
    win, *_ = world
    root = "C:" + os.sep + "Windows"
    tree = [W.windows_group(exists=lambda path: True, system_root=root)]
    env = next(n for n in tree[0].children if n.name == "Environment Variables")

    def pick(self, dlg):
        dlg.picked = env
        return True
    monkeypatch.setattr(type(win), "_ask_start_menu", pick)
    monkeypatch.setattr(type(win), "_ask_tool", lambda self, dlg: True)
    win.set_tools([])
    win._programs_found((tree, []))
    assert win.tools == [T.Tool("Environment Variables", env.path, "sysdm.cpl,EditEnvironmentVariables", "", icon=env.icon)]


def test_editing_a_tool_keeps_its_icon(world, monkeypatch):
    from dossier.gui.tools_bar import ToolDialog
    win, *_ = world
    tool = T.Tool("Services", "services.msc", "", "", icon="filemgmt.dll,0")
    dlg = ToolDialog(win, tool, None, None, "Edit the Program")
    dlg.name.setText("My services")
    assert dlg.tool() == T.Tool("My services", "services.msc", "", "", icon="filemgmt.dll,0")
    dlg.command.setText("other.exe")                                         # another program: its own icon from now on
    assert dlg.tool().icon == ""


@pytest.mark.skipif(os.name != "nt", reason="Windows' own icons")
def test_the_real_icons_of_windows_are_read_and_are_not_the_blank_page_of_a_console(world):
    """Qt's own lookup gives a .msc console and a .cpl panel a blank page; the icons are read from the files that hold them."""
    from dossier.gui.tools_bar import program_icon
    group = W.windows_group()
    by_name = {n.name: n for n in group.children}
    blank = program_icon(by_name["Device Manager"].path).pixmap(32, 32).toImage()
    for name, node in by_name.items():                                    # every part, not only the consoles
        icon = program_icon(node.path, node.icon)
        assert not icon.isNull(), name
        assert icon.pixmap(32, 32).toImage() != blank, name


def test_add_a_program_offers_the_windows_group_first(world, tmp_path, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(SM, "roots", lambda environ=None: [])
    monkeypatch.setattr(W, "windows_group", lambda **kw: SM.Node("Windows", "", [SM.Node("Services", "services.msc")]))
    got = []
    monkeypatch.setattr(type(win), "_ask_start_menu", lambda self, dlg: (got.append(dlg.tree.topLevelItem(0).text(0)), False)[1])
    win.add_program()
    pump(win, lambda: got)
    assert got == ["Windows"]
