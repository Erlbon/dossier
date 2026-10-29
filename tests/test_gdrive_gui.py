"""Google Drive in the window: adding it, signing in through the browser, opening it again without the browser, disconnecting."""
import pytest

pytest.importorskip("PyQt6")
from dossier.core import servers  # noqa: E402
from tests.fake_drive import FakeDrive  # noqa: E402
from tests.test_gdrive import browser  # noqa: E402
from tests.test_gui_commander import app, world  # noqa: E402,F401
from tests.test_servers_gui import wait  # noqa: E402


@pytest.fixture
def lab(world, monkeypatch):
    win, d, left, right, tmp = world
    store = {}
    monkeypatch.setattr(servers, "get_secret", lambda account: store.get(account, ""))
    monkeypatch.setattr(servers, "set_secret", lambda account, value: store.__setitem__(account, value) or True)
    monkeypatch.setattr(servers, "forget_secret", lambda account: store.pop(account, None))
    drive = FakeDrive()
    drive.client_secret = "the-secret"
    drive.add("notes.txt", "root", b"hello drive")
    win.cloud_transport = drive
    win.open_browser = browser(drive)
    win.store, win.drive = store, drive
    return win, d, left, right, tmp


def add_drive(win, monkeypatch, remember=True):
    def answer(self, dlg):
        dlg.name.setText("My Google")
        dlg.protocol.setCurrentIndex(dlg.protocol.findData("gdrive"))
        dlg.client_id.setText("client-id")
        dlg.client_secret.setText("the-secret")
        dlg.remember.setChecked(remember)
        return True
    monkeypatch.setattr(type(win), "_ask_server", answer)
    win.add_server()
    return win.connections()[0]


def test_adding_a_drive_keeps_the_client_id_in_the_settings_and_the_secret_in_the_password_store(lab, monkeypatch):
    win, *_ = lab
    conn = add_drive(win, monkeypatch)
    assert conn.protocol == "gdrive" and conn.client_id == "client-id" and conn.save_password and conn.host.startswith("gd-")
    assert win.store[servers.client_secret_account("client-id")] == "the-secret"
    assert "the-secret" not in win.settings.value("servers/list", "")
    assert win.server_items()[0].detail == "Google Drive  (read-only)"                  # read-only until the owner switches it off


def test_the_dialog_for_a_drive_shows_the_client_rows_and_hides_host_port_and_user(lab):
    from dossier.gui.servers import ConnectionDialog
    win, *_ = lab
    dlg = ConnectionDialog(win)
    form = dlg._form
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("gdrive"))
    assert form.isRowVisible(dlg.client_id) and form.isRowVisible(dlg.client_secret) and dlg.remember.isChecked()
    assert not any(form.isRowVisible(w) for w in (dlg.host, dlg.port, dlg.user, dlg.start_dir, dlg.secure))
    assert "Google" in dlg.type_note.text()
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("sftp"))
    assert all(form.isRowVisible(w) for w in (dlg.host, dlg.port, dlg.user)) and not form.isRowVisible(dlg.client_id)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("gdrive"))
    dlg.name.setText("G")
    dlg._accept()
    assert "client ID" in dlg.problem.text()                                            # the app must be named before it can be saved


def test_the_first_open_signs_in_through_the_browser_and_keeps_only_the_token(lab, monkeypatch):
    win, d, left, right, tmp = lab
    conn = add_drive(win, monkeypatch)
    win.open_server(conn.url("/"), panel=win.left)
    wait(win, lambda: win.left.path.startswith("gdrive://"))
    wait(win, lambda: any(e.name == "notes.txt" for e in (win.left.model.entry_at(r) for r in range(win.left.model.entry_count())) if e))
    assert win.store[f"gdrive:{conn.authority()}"] == "refresh-1"
    assert win.server_connected(conn)


def test_the_next_time_the_kept_token_opens_the_drive_without_the_browser(lab, monkeypatch):
    win, d, left, right, tmp = lab
    conn = add_drive(win, monkeypatch)
    win.store[f"gdrive:{conn.authority()}"] = "refresh-1"
    win.open_browser = lambda url: pytest.fail("the browser must not open: a token was kept")
    win.open_server(conn.url("/"), panel=win.left)
    wait(win, lambda: win.left.path.startswith("gdrive://") and win.left.model.entry_count() > 1)
    assert win.server_connected(conn)


def test_a_revoked_token_falls_back_to_the_browser(lab, monkeypatch):
    win, d, left, right, tmp = lab
    conn = add_drive(win, monkeypatch)
    win.store[f"gdrive:{conn.authority()}"] = "revoked"
    opened = []
    real = win.open_browser
    win.open_browser = lambda url: (opened.append(url), real(url))
    win.open_server(conn.url("/"), panel=win.left)
    wait(win, lambda: win.left.path.startswith("gdrive://"))
    assert opened and win.store[f"gdrive:{conn.authority()}"] == "refresh-1"


def test_without_staying_signed_in_nothing_is_kept_and_disconnecting_returns_home(lab, monkeypatch):
    win, d, left, right, tmp = lab
    conn = add_drive(win, monkeypatch, remember=False)
    win.open_server(conn.url("/"), panel=win.left)
    wait(win, lambda: win.left.path.startswith("gdrive://"))
    assert f"gdrive:{conn.authority()}" not in win.store
    win.disconnect_server(conn)
    wait(win, lambda: win.left.is_home)
    assert not win.server_connected(conn)


def test_removing_the_drive_forgets_its_token(lab, monkeypatch):
    win, d, left, right, tmp = lab
    conn = add_drive(win, monkeypatch)
    win.store[f"gdrive:{conn.authority()}"] = "refresh-1"
    monkeypatch.setattr(type(win.dialogs), "confirm", lambda self, *a, **k: True, raising=False)
    win.remove_server(conn)
    assert f"gdrive:{conn.authority()}" not in win.store and win.connections() == []
