"""Mac packages and Linux launchers in the window (card 50A): names, Enter, Show Package Contents."""
from __future__ import annotations

import stat

import pytest

pytest.importorskip("PyQt6")

from dossier.core import bundles  # noqa: E402
from tests.test_gui_commander import pump, world, app  # noqa: E402,F401

DESKTOP = "[Desktop Entry]" + chr(10) + "Type=Application" + chr(10) + "Name=Fancy Tool" + chr(10) + "Exec=fancy --go" + chr(10)


def _show(win, panel, name):
    panel.refresh()
    pump(win, lambda: panel.model.row_of(name) >= 0)
    row = panel.model.row_of(name)
    panel.table.setCurrentIndex(panel.model.index(row, 0))
    return row


def _launcher(win, left, monkeypatch):
    monkeypatch.setattr(bundles, "LINUX", True)
    (left / "fancy.desktop").write_text(DESKTOP, encoding="utf-8")
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    return started


def test_a_launcher_shows_its_own_name_and_type(world, monkeypatch):
    win, _d, left, *_ = world
    _launcher(win, left, monkeypatch)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 1)
    model = win.left.model
    row = next(r for r in range(model.rowCount()) if model.entry_at(r) is not None and model.entry_at(r).name == "fancy.desktop")
    assert model.data(model.index(row, 0)) == "Fancy Tool"
    assert model.data(model.index(row, 3)) == "Launcher"


def test_enter_on_an_untrusted_launcher_asks_once(world, monkeypatch):
    win, dialogs, left, *_ = world
    started = _launcher(win, left, monkeypatch)
    _show(win, win.left, "fancy.desktop")
    dialogs.choice_answer = "start"
    win.left.open_current()
    pump(win, lambda: started)
    assert len(dialogs.choices_asked) == 1 and "fancy --go" in dialogs.choices_asked[0][1]
    assert started[0][0].endswith("fancy.desktop")
    win.left.open_current()
    pump(win, lambda: len(started) == 2)
    assert len(dialogs.choices_asked) == 1                       # trusted now: not asked again
    assert win.trusted_launchers() == [str(left / "fancy.desktop")]


def test_a_launcher_that_is_not_started_is_not_trusted(world, monkeypatch):
    win, dialogs, left, *_ = world
    started = _launcher(win, left, monkeypatch)
    _show(win, win.left, "fancy.desktop")
    dialogs.choice_answer = None
    win.left.open_current()
    pump(win, lambda: getattr(dialogs, "choices_asked", None))
    assert not started and win.trusted_launchers() == []


def test_enter_on_a_runnable_file_asks_run_or_view(world, monkeypatch):
    win, dialogs, left, *_ = world
    monkeypatch.setattr(bundles, "WINDOWS", False)
    monkeypatch.setattr(win, "_run_mode", lambda path: stat.S_IFREG | 0o755, raising=False)
    (left / "install").write_text("data")
    started, viewed = [], []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    monkeypatch.setattr(win, "view_file", lambda paths: viewed.append(paths))
    _show(win, win.left, "install")
    dialogs.choice_answer = "run"
    win.left.open_current()
    pump(win, lambda: started)
    assert started == [(str(left / "install"), [])] and dialogs.choices_asked[0][2] == ["run", "terminal", "view"]
    dialogs.choice_answer = "view"
    win.left.open_current()
    pump(win, lambda: viewed)
    assert viewed == [[str(left / "install")]]


def test_ctrl_enter_on_a_runnable_file_does_not_ask(world, monkeypatch):
    win, dialogs, left, *_ = world
    monkeypatch.setattr(bundles, "WINDOWS", False)
    monkeypatch.setattr(win, "_run_mode", lambda path: stat.S_IFREG | 0o755, raising=False)
    (left / "install").write_text("data")
    monkeypatch.setattr(win, "_open_file_plain", lambda path, alternate=False: True)
    _show(win, win.left, "install")
    win.left.open_current(new_tab=True)
    assert not getattr(dialogs, "choices_asked", [])


def test_enter_on_a_mac_package_goes_to_the_system_and_ctrl_enter_opens_the_folder(world, monkeypatch):
    win, _d, left, *_ = world
    monkeypatch.setattr(bundles, "MAC", True)
    (left / "Mail.app").mkdir()
    (left / "Mail.app" / "Contents").mkdir()
    opened = []
    monkeypatch.setattr(win, "_open_with_system", lambda path: opened.append(path))
    _show(win, win.left, "Mail.app")
    model = win.left.model
    assert model.data(model.index(model.row_of("Mail.app"), 3)) == "App"
    tabs = win.left.tabs.count()
    win.left.open_current()
    assert opened == [str(left / "Mail.app")] and win.left.path == str(left)
    win.left.open_current(new_tab=True)
    assert len(opened) == 1 and win.left.tabs.count() == tabs + 1


def test_show_package_contents_is_in_the_menu_for_a_package_only(world, monkeypatch):
    win, _d, left, *_ = world
    monkeypatch.setattr(bundles, "MAC", True)
    (left / "Mail.app").mkdir()
    (left / "Plain").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("Plain") >= 0 and win.left.model.row_of("Mail.app") >= 0)
    texts = lambda name: [a.text() for a in win.build_context_menu(win.left, win.left.model.row_of(name)).actions()]  # noqa: E731
    assert "Show Package Contents" in texts("Mail.app")
    assert "Show Package Contents" not in texts("Plain")
    next(a for a in win.build_context_menu(win.left, win.left.model.row_of("Mail.app")).actions()
         if a.text() == "Show Package Contents").trigger()
    pump(win, lambda: win.left.path == str(left / "Mail.app"))
