"""Dossier in Windows' Open With (card 69C): the keys written for pictures and text files (against a fake registry, never the real one),
taking them away, and the switches in Settings > Opening Files."""
import re

import pytest

from dossier.core import file_associations as F

BS = chr(92)
EXE = "C:" + BS + "Program Files" + BS + "Dossier" + BS + "dossier.exe"


class FakeRegistry:
    def __init__(self):
        self.values = {}                  # (path, name) -> value
        self.notified = 0

    def set_value(self, path, name, value):
        self.values[(path, name)] = value

    def get_value(self, path, name):
        return self.values.get((path, name))

    def delete_value(self, path, name):
        self.values.pop((path, name), None)

    def delete_tree(self, path):
        for key in [k for k in self.values if k[0] == path or k[0].startswith(path + BS)]:
            del self.values[key]

    def list_values(self, path):
        return [name for (p, name) in self.values if p == path]

    def notify_changed(self):
        self.notified += 1


def classes(*parts):
    return BS.join(("Software", "Classes") + parts)


def test_pictures_write_the_progid_the_extension_lists_and_the_application():
    reg = FakeRegistry()
    F.enable(reg, F.PICTURES, EXE)
    command = '"' + EXE + '" view "%1"'
    assert reg.values[(classes("Dossier.Picture"), "")] == "Dossier Picture Viewer"
    assert reg.values[(classes("Dossier.Picture", "shell", "open", "command"), "")] == command
    assert reg.values[(classes("Dossier.Picture", "DefaultIcon"), "")] == '"' + EXE + '",0'
    assert reg.values[(classes("Applications", "dossier.exe"), "FriendlyAppName")] == "Dossier"
    for ext in (".jpg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".svg"):
        assert (classes(ext, "OpenWithProgids"), "Dossier.Picture") in reg.values
        assert (classes("Applications", "dossier.exe", "SupportedTypes"), ext) in reg.values
    assert reg.notified == 1
    assert not any(path.startswith(classes("Dossier.Text")) for path, _n in reg.values)        # the other group is not touched


def test_text_writes_the_edit_command_for_its_extensions():
    reg = FakeRegistry()
    F.enable(reg, F.TEXTS, EXE)
    assert reg.values[(classes("Dossier.Text", "shell", "open", "command"), "")] == '"' + EXE + '" edit "%1"'
    for ext in (".txt", ".md", ".log", ".ini", ".cfg", ".json", ".xml", ".yaml", ".csv"):
        assert (classes(ext, "OpenWithProgids"), "Dossier.Text") in reg.values
    assert (classes(".jpg", "OpenWithProgids"), "Dossier.Picture") not in reg.values


def test_a_path_with_spaces_is_quoted():
    assert F.open_command(F.PICTURES, EXE) == '"C:' + BS + 'Program Files' + BS + 'Dossier' + BS + 'dossier.exe" view "%1"'


def test_taking_away_deletes_only_what_was_added():
    reg = FakeRegistry()
    other = [(classes(".jpg", "OpenWithProgids"), "Paint.Picture"), (classes(".jpg"), ""), (classes(".jpg", "UserChoice"), "ProgId"),
             (classes("Applications", "other.exe"), "FriendlyAppName"), (classes(".txt", "OpenWithProgids"), "txtfile")]
    for path, name in other:
        reg.set_value(path, name, "mine")
    before = dict(reg.values)
    F.enable(reg, F.PICTURES, EXE)
    F.enable(reg, F.TEXTS, EXE)
    F.disable(reg, F.PICTURES)
    assert not any("Picture" in p or p.endswith("SupportedTypes") and n in F.PICTURES.extensions for (p, n) in reg.values)
    assert F.is_enabled(reg, F.TEXTS, EXE) and not F.is_enabled(reg, F.PICTURES, EXE)
    assert (classes("Applications", "dossier.exe"), "FriendlyAppName") in reg.values        # text still uses the application's key
    F.disable(reg, F.TEXTS)
    assert reg.values == before                                                              # exactly as it was
    assert reg.notified == 4


def test_the_state_is_read_from_the_registry_and_a_moved_program_shows_as_off():
    reg = FakeRegistry()
    assert not F.is_enabled(reg, F.PICTURES, EXE)
    F.enable(reg, F.PICTURES, EXE)
    assert F.is_enabled(reg, F.PICTURES, EXE) and F.is_enabled(reg, F.PICTURES)
    assert not F.is_enabled(reg, F.PICTURES, "D:" + BS + "elsewhere" + BS + "dossier.exe")


def test_the_program_is_the_running_exe_only_when_built():
    assert F.exe_path(frozen=True, executable=EXE) == EXE
    assert F.exe_path(frozen=False, executable=EXE) is None


def test_the_installer_writes_the_same_keys_and_removes_them():
    """installer/dossier.iss [Registry] and the core module name the same ProgIDs, extensions, commands, and the installer's lines
    are flagged for removal at uninstall."""
    import os
    with open(os.path.join(os.path.dirname(__file__), "..", "installer", "dossier.iss"), encoding="utf-8") as f:
        iss = f.read()
    assert 'Name: "offerpictures"' in iss and 'Name: "offertext"' in iss
    lines = [x for x in iss.split("[Registry]", 1)[1].split(chr(10) + "[", 1)[0].splitlines() if x.startswith("Root:")]
    for group, task in ((F.PICTURES, "offerpictures"), (F.TEXTS, "offertext")):
        mine = [x for x in lines if f"Tasks: {task}" in x]
        exts = re.findall(r'Subkey: "Software' + re.escape(BS) + 'Classes' + re.escape(BS) + r'(' + r'\.[a-z0-9]+)' + re.escape(BS) +
                          'OpenWithProgids"', chr(10).join(mine))
        assert sorted(exts) == sorted(group.extensions)
        supported = re.findall(r'SupportedTypes"; ValueType: none; ValueName: "(\.[a-z0-9]+)"', chr(10).join(mine))
        assert sorted(supported) == sorted(group.extensions)
        progid_line = [x for x in mine if f'Classes{BS}{group.progid}"' in x][0]
        assert "uninsdeletekey" in progid_line
        command = open_command_for_inno(group)
        assert any(command in x for x in mine), command
        assert all("uninsdeletevalue" in x for x in mine if "OpenWithProgids" in x)
    assert all(x.startswith("Root: HKCU") for x in lines)                      # per user only, no administrator rights
    assert "uninsdeletekey" in [x for x in lines if f"Applications{BS}dossier.exe" + '"; ValueType: string; ValueName: "FriendlyAppName"' in x][0]


def open_command_for_inno(group):
    return 'ValueData: """{app}' + BS + 'dossier.exe"" ' + group.verb + ' ""%1"""'


# the switches in the window --------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from tests.test_gui_commander import pump, world, app  # noqa: E402,F401


def _menu(win, windows=True):
    from PyQt6.QtWidgets import QMenu
    menu = QMenu()
    win.build_associations_menu(menu, windows=windows)
    return menu


def test_the_switches_exist_only_on_windows(world):
    win, _d, _l, _r, _t = world
    off = _menu(win, windows=False)
    assert [a.text() for a in off.actions()] == [] and win.assoc_actions == {}
    on = _menu(win)
    texts = [a.text() for a in on.actions() if a.text()]
    assert texts == [F.PICTURES.label, F.TEXTS.label, "Open Default Apps..."]


def test_from_source_the_switches_are_off_with_a_tooltip(world):
    win, _d, _l, _r, _t = world
    win.assoc_frozen = False
    _menu(win)
    for act in win.assoc_actions.values():
        assert not act.isEnabled() and "from source" in act.toolTip()


def test_a_switch_writes_on_a_thread_and_shows_the_state(world):
    win, _d, _l, _r, _t = world
    win.assoc_registry, win.assoc_exe = FakeRegistry(), EXE
    _menu(win)
    pic = win.assoc_actions["picture"]
    assert pic.isEnabled() and not pic.isChecked()
    pic.setChecked(True)
    # wait for the registry AND the tick the thread's answer sets, or a late answer re-ticks it under a slow run
    pump(win, until=lambda: F.is_enabled(win.assoc_registry, F.PICTURES, EXE) and not win._size_jobs and pic.isChecked())
    assert F.is_enabled(win.assoc_registry, F.PICTURES, EXE) and not F.is_enabled(win.assoc_registry, F.TEXTS, EXE)
    pic.setChecked(False)
    pump(win, until=lambda: not F.is_enabled(win.assoc_registry, F.PICTURES, EXE) and not win._size_jobs and not pic.isChecked())
    assert not win.assoc_registry.values or not any("Picture" in p for p, _n in win.assoc_registry.values)
    assert not pic.isChecked()


def test_the_ticks_show_what_the_registry_says(world):
    """What the installer's ticks wrote shows as ticked switches when the menu opens."""
    win, _d, _l, _r, _t = world
    win.assoc_registry, win.assoc_exe = FakeRegistry(), EXE
    F.enable(win.assoc_registry, F.TEXTS, EXE)
    _menu(win)
    win.refresh_associations()
    pump(win, until=lambda: win.assoc_actions["text"].isChecked())
    assert win.assoc_actions["text"].isChecked() and not win.assoc_actions["picture"].isChecked()


def test_open_default_apps_uses_the_seam(world):
    win, _d, _l, _r, _t = world
    opened = []
    win.open_web_page = opened.append
    _menu(win)
    win.act_default_apps.trigger()
    assert opened == ["ms-settings:defaultapps"]


# question 75A: the general entry opens the file by its kind -----------------------------------------------------------------------
def test_the_general_entry_runs_dossier_open_in_the_module_and_the_installer():
    import os
    reg = FakeRegistry()
    F.enable(reg, F.PICTURES, EXE)
    assert reg.values[(classes("Applications", "dossier.exe", "shell", "open", "command"), "")] == '"' + EXE + '" open "%1"'
    with open(os.path.join(os.path.dirname(__file__), "..", "installer", "dossier.iss"), encoding="utf-8") as f:
        iss = f.read()
    line = [x for x in iss.splitlines() if f"Applications{BS}dossier.exe{BS}shell{BS}open{BS}command" in x][0]
    assert 'ValueData: """{app}' + BS + 'dossier.exe"" open ""%1"""' in line


def test_dossier_open_routes_a_picture_to_the_viewer_text_to_the_notepad_and_the_rest_to_the_window(tmp_path):
    from dossier.core.viewmodes import open_route
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(20))
    txt = tmp_path / "notes.txt"
    txt.write_text("hello", encoding="utf-8")
    md = tmp_path / "read.md"
    md.write_text("# hi", encoding="utf-8")
    exe = tmp_path / "tool.bin"
    exe.write_bytes(b"MZ" + bytes(200))
    assert open_route(str(png)) == "view"
    assert open_route(str(txt)) == "edit" and open_route(str(md)) == "edit"
    assert open_route(str(exe)) == "window" and open_route(str(tmp_path)) == "window"
    from dossier.gui.app import routed_open
    assert routed_open(["open", str(png)]) == ["view", str(png)]
    assert routed_open(["open", str(txt)]) == ["edit", str(txt)]
    assert routed_open(["open", str(exe)]) == [str(exe)]                                     # the window, cursor on the file
    assert routed_open(["view", str(png)]) == ["view", str(png)] and routed_open([]) == []


# question 76A: a moved one-file exe takes its switches over --------------------------------------------------------------------
def test_switches_on_for_a_copy_whose_place_is_gone_are_taken_over_without_asking():
    reg = FakeRegistry()
    old = "D:" + BS + "gone" + BS + "dossier.exe"
    F.enable(reg, F.PICTURES, old)
    assert F.registered_exe(reg, F.PICTURES) == old and F.registered_exe(reg, F.TEXTS) is None
    assert F.take_over_on_start(reg, EXE, exists=lambda p: False) == [F.PICTURES]
    assert F.is_enabled(reg, F.PICTURES, EXE) and not F.is_enabled(reg, F.TEXTS, EXE)            # an off switch stays off


def test_a_copy_that_still_exists_elsewhere_keeps_its_switches():
    reg = FakeRegistry()
    other = "D:" + BS + "other" + BS + "dossier.exe"
    F.enable(reg, F.TEXTS, other)
    assert F.take_over_on_start(reg, EXE, exists=lambda p: True) == []
    assert F.is_enabled(reg, F.TEXTS, other)


def test_an_older_general_entry_of_this_copy_is_brought_up_to_date():
    reg = FakeRegistry()
    F.enable(reg, F.TEXTS, EXE)
    reg.set_value(classes("Applications", "dossier.exe", "shell", "open", "command"), "", '"' + EXE + '" "%1"')
    assert F.take_over_on_start(reg, EXE, exists=lambda p: True) == [F.TEXTS]
    assert reg.values[(classes("Applications", "dossier.exe", "shell", "open", "command"), "")] == '"' + EXE + '" open "%1"'
    assert F.take_over_on_start(reg, EXE, exists=lambda p: True) == []


def test_the_window_takes_the_switches_over_on_a_thread(world):
    win, _d, _l, _r, tmp = world
    win.assoc_registry, win.assoc_exe = FakeRegistry(), EXE
    F.enable(win.assoc_registry, F.PICTURES, str(tmp / "gone" / "dossier.exe"))
    _menu(win)
    win.take_over_associations()
    pump(win, until=lambda: win.assoc_actions["picture"].isChecked())
    assert F.is_enabled(win.assoc_registry, F.PICTURES, EXE) and win.assoc_actions["picture"].isChecked()
