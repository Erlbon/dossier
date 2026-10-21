"""The Tailnet section in the window: read on a thread, shown on the Home page, added as a server, switched off."""
import pytest

pytest.importorskip("PyQt6")

from dossier.core import tailnet  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import wait  # noqa: E402,F401
from tests.test_tailnet import STATUS  # noqa: E402


@pytest.fixture
def devices(monkeypatch):
    monkeypatch.setattr(tailnet, "read_devices", lambda *a, **k: tailnet.parse_status(STATUS))


def home_names(win):
    win.left.go_home()
    pump(win, lambda: win.left.is_home)
    return [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]


def test_the_devices_appear_on_the_home_page_after_the_background_reading(world, devices):
    win, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())
    names = home_names(win)
    assert names[names.index("Tailnet") + 1:] == ["laptop", "homeserver3", "alpha-nas", "zeta-phone"]
    assert win.tailnet_item("home://#tailnet/homeserver3").host == "100.118.213.22"


def test_without_tailscale_there_is_no_section_and_no_error(world):
    win, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: not win._tailnet_reading)
    assert "Tailnet" not in home_names(win)


def test_a_device_opens_the_add_server_dialog_with_its_name_and_address(world, devices, monkeypatch):
    win, d, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())
    seen = []
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (seen.append(dlg), False)[1])
    win._home_action("home://#tailnet/homeserver3")
    dlg = seen[0]
    assert dlg.windowTitle() == "Add a Server" and dlg.name.text() == "homeserver3" and dlg.host.text() == "100.118.213.22"
    assert dlg.protocol.currentData() == "sftp" and dlg.port.value() == 22
    win.add_tailnet_server("home://#tailnet/homeserver3", "subsonic")
    assert seen[1].protocol.currentData() == "subsonic" and seen[1].connection().read_only


def test_enter_on_a_device_row_does_the_same_and_the_context_menu_offers_every_kind(world, devices, monkeypatch):
    win, d, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())
    home_names(win)
    row = win.left.model.row_of("homeserver3")
    seen = []
    monkeypatch.setattr(type(win), "_ask_server", lambda self, dlg: (seen.append(dlg), False)[1])
    win.left.table.setCurrentIndex(win.left.model.index(row, 0))
    win.left.open_current()
    assert seen and seen[0].host.text() == "100.118.213.22"
    menu = win._home_menu(win.left, win.left.model.entry_at(row), row)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Add as SFTP Server...", "Add as WebDAV Server...", "Add as OPDS Book Catalogue...", "Add as Subsonic Music Server...",
                     "Copy the Address", "Read the Tailnet Again"]


def test_the_address_can_be_copied(world, devices):
    from PyQt6.QtGui import QGuiApplication
    win, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())
    win.copy_tailnet_address("home://#tailnet/homeserver3")
    assert QGuiApplication.clipboard().text() == "100.118.213.22"


def test_the_section_can_be_switched_off_and_the_choice_is_kept(world, devices):
    win, *_ = world
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())
    assert "Tailnet" in home_names(win)
    win.act_tailnet.setChecked(False)
    assert win.settings.value("tailnet/show") == "false" and not win.tailnet_items()
    pump(win)
    assert "Tailnet" not in [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    win.act_tailnet.setChecked(True)
    wait(win, lambda: win.tailnet_items())


def test_showing_the_home_page_again_does_not_read_the_tailnet_more_than_every_half_minute(world, monkeypatch):
    win, *_ = world
    calls = []
    monkeypatch.setattr(tailnet, "read_devices", lambda *a, **k: calls.append(1))
    win.refresh_tailnet(force=True)
    wait(win, lambda: not win._tailnet_reading)
    for _ in range(3):
        win.refresh_tailnet()
    pump(win)
    assert calls == [1]
