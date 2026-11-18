"""Open With on the Mac and Linux (card 49A): the system's programs for the type, the default first, then the tools bar's, then
Other Program..."""
from __future__ import annotations

import pytest

from dossier.core import desktop_entries as D
from dossier.core import open_with as O


def _desktop(tmp_path):
    apps = {
        "org.gnome.gedit.desktop": D.DesktopApp("org.gnome.gedit.desktop", "/usr/share/applications/org.gnome.gedit.desktop",
                                                "Text Editor", exec="gedit %U", mime_types=("text/plain",)),
        "vim.desktop": D.DesktopApp("vim.desktop", "/usr/share/applications/vim.desktop", "Vim", exec="vim %F",
                                    mime_types=("text/plain",), terminal=True, no_display=True),
        "gimp.desktop": D.DesktopApp("gimp.desktop", "/usr/share/applications/gimp.desktop", "GIMP", exec="gimp %U",
                                     mime_types=("image/png",)),
    }
    assoc = D.parse_mimeapps(["[Default Applications]\ntext/plain=vim.desktop\n"])
    mime = D.MimeDatabase([(50, "text/plain", "*.txt", False), (50, "image/png", "*.png", False)], {})
    return D.Desktop(apps, assoc, mime)


def test_linux_lists_the_programs_for_the_type_with_the_default_first(tmp_path):
    progs = O.linux_programs(_desktop(tmp_path), "notes.txt")
    assert [p.name for p in progs] == ["Vim", "Text Editor"]
    assert progs[0].default and not progs[1].default
    assert progs[0].path.endswith("vim.desktop")
    assert [p.name for p in O.linux_programs(_desktop(tmp_path), "photo.png")] == ["GIMP"]


def test_linux_with_no_default_marks_none(tmp_path):
    desk = _desktop(tmp_path)
    desk.associations = D.Associations()
    progs = O.linux_programs(desk, "notes.txt")
    assert [p.name for p in progs] == ["Text Editor", "Vim"] and not any(p.default for p in progs)


def test_mac_puts_the_default_first_once_and_sorts_the_rest():
    lookup = lambda path: ("/Applications/TextEdit.app", ["/Applications/Xcode.app", "/Applications/TextEdit.app",  # noqa: E731
                                                          "/Applications/BBEdit.app"])
    progs = O.mac_programs("/Users/a/x.txt", lookup)
    assert [p.name for p in progs] == ["TextEdit", "BBEdit", "Xcode"]
    assert progs[0].default and progs[0].path == "/Applications/TextEdit.app"
    assert O.mac_programs("/x", lambda p: ("", [])) == []


def test_system_programs_are_empty_until_the_desktop_is_read(tmp_path):
    progs = O.SystemPrograms(loader=lambda: _desktop(tmp_path), system="linux")
    assert progs.for_file("/home/a/notes.txt") == [] and not progs.ready
    progs.load_now()
    assert progs.ready and [p.name for p in progs.for_file("/home/a/notes.txt")] == ["Vim", "Text Editor"]
    assert O.SystemPrograms(system="").for_file("/x.txt") == []


# the menu ---------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from tests.test_gui_commander import pump, world, app  # noqa: E402,F401


def test_open_with_menu_shows_the_systems_programs_then_the_tools_then_other_program(world, tmp_path):
    from dossier.core import tools
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    win.system_programs = O.SystemPrograms(loader=lambda: _desktop(tmp_path), system="linux")
    win.system_programs.load_now()
    win.set_tools([tools.Tool("Notepad++", r"C:\npp.exe", "{files}")])
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    menu = win.build_context_menu(win.left, win.left.model.row_of("a.txt"))
    open_with = next(a.menu() for a in menu.actions() if a.text() == "Open With")
    texts = [a.text() for a in open_with.actions() if not a.isSeparator()]
    assert texts[:3] == ["Vim (default)", "Text Editor", "Notepad++"]
    next(a for a in open_with.actions() if a.text() == "Text Editor").trigger()
    assert started == [("/usr/share/applications/org.gnome.gedit.desktop", [str(left / "a.txt")])]
    if "Choose Another Program..." not in texts:
        assert texts[-1] == "Other Program..."
