"""Card 45A: Quick Look on the Mac (qlmanage) and the GNOME previewer on Linux (core/quicklook.py)."""
from __future__ import annotations

import pytest

from dossier.core import quicklook as Q


def test_the_mac_previews_with_qlmanage():
    assert Q.command_for("/Users/a/x.txt", "mac") == ["qlmanage", "-p", "/Users/a/x.txt"]


def test_linux_calls_sushi_over_dbus_with_a_file_uri():
    command = Q.command_for("/home/a/my file.txt", "linux", sushi=True)
    assert command[:7] == ["gdbus", "call", "--session", "--dest", "org.gnome.NautilusPreviewer", "--object-path",
                           "/org/gnome/NautilusPreviewer"]
    assert command[7:] == ["--method", "org.gnome.NautilusPreviewer2.ShowFile", "'file:///home/a/my%20file.txt'", "''", "false",
                           "''"]


def test_there_is_no_command_without_a_previewer_or_on_windows():
    assert Q.command_for("/home/a/x", "linux", sushi=False) is None
    assert Q.command_for("C:/x.txt", "", sushi=True) is None
    assert Q.command_for("sftp://h/x", "linux", sushi=True) is None
    assert Q.command_for("", "mac") is None


def test_sushi_is_found_by_its_service_file_or_its_program():
    service = "/usr/share/dbus-1/services/org.gnome.NautilusPreviewer.service"
    gdbus = lambda name: "/usr/bin/gdbus" if name == "gdbus" else None          # noqa: E731
    assert Q.sushi_installed(["/usr/share"], exists=lambda p: p.replace(chr(92), "/") == service, which=gdbus)
    assert not Q.sushi_installed(["/usr/share"], exists=lambda p: False, which=gdbus)
    both = lambda name: "/usr/bin/" + name                                       # noqa: E731
    assert Q.sushi_installed(["/usr/share"], exists=lambda p: False, which=both)
    assert not Q.sushi_installed(["/usr/share"], exists=lambda p: True, which=lambda name: None)      # no gdbus to call it with


def test_availability_per_system():
    assert Q.QuickLook(system="mac").available
    assert not Q.QuickLook(system="").available
    linux = Q.QuickLook(system="linux", detector=lambda: True)
    assert not linux.available and linux.command("/a") is None            # not known until the thread has looked
    linux.detect_now()
    assert linux.available and linux.command("/a")[0] == "gdbus"
    none = Q.QuickLook(system="linux", detector=lambda: False)
    none.detect_now()
    assert not none.available


# the window ------------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from tests.test_gui_commander import pump, world, app  # noqa: E402,F401


def _file_menu(win):
    """File > Preview, the submenu that holds View, View as Glass and Quick Look (owner, 2026-11-19)."""
    file = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "File")
    return next(a.menu() for a in file.actions() if a.text() == "Preview")


def _texts(menu):
    menu.aboutToShow.emit()
    return [a.text().split("\t")[0] for a in menu.actions() if a.isVisible() and not a.isSeparator()]


def _on_a_file(win, left):
    (left / "a.txt").write_text("a")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.txt") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.txt"), 0))
    win._set_active(win.left)


def test_the_mac_runs_qlmanage_through_the_seam(world):
    win, _d, left, *_ = world
    _on_a_file(win, left)
    win.quick_look_info = Q.QuickLook(system="mac")
    started = []
    win._start_detached = started.append
    win.quick_look()
    assert started == [["qlmanage", "-p", str(left / "a.txt")]]
    assert "Quick Look" in _texts(_file_menu(win))
    menu = win.build_context_menu(win.left, win.left.model.row_of("a.txt"))
    assert "Quick Look" in [a.text().split("\t")[0] for a in menu.actions()]


def test_linux_with_sushi_runs_the_dbus_call_and_without_it_nothing(world):
    win, _d, left, *_ = world
    _on_a_file(win, left)
    started = []
    win._start_detached = started.append
    win.quick_look_info = Q.QuickLook(system="linux", detector=lambda: False)
    win.quick_look_info.detect_now()
    win.quick_look()
    assert started == [] and "Quick Look" not in _texts(_file_menu(win))
    win.quick_look_info = Q.QuickLook(system="linux", detector=lambda: True)
    win.quick_look_info.detect_now()
    from types import SimpleNamespace
    here = SimpleNamespace(name="a.txt", path="/home/a/a.txt", kind="file")        # this test runs on Windows: a Linux path by hand
    win.active.current_entry = lambda: here
    win.quick_look()
    assert len(started) == 1 and started[0][0] == "gdbus" and started[0][8] == "org.gnome.NautilusPreviewer2.ShowFile"
    assert started[0][9] == "'file:///home/a/a.txt'"


def test_windows_has_no_entry_and_the_key_does_nothing(world):
    win, _d, left, *_ = world
    _on_a_file(win, left)
    win.quick_look_info = Q.QuickLook(system="")
    started = []
    win._start_detached = started.append
    win.quick_look()
    assert started == []
    assert "Quick Look" not in _texts(_file_menu(win))
    menu = win.build_context_menu(win.left, win.left.model.row_of("a.txt"))
    assert "Quick Look" not in [a.text().split("\t")[0] for a in menu.actions()]
    if not Q.IS_MACOS and not Q.IS_LINUX:                 # this very window is on Windows: no key was given to the action
        assert win.act_quick_look.shortcuts() == []
