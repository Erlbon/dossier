"""OPDS and Subsonic servers in the window: the dialog, the login, browsing, and copying a book or a track out."""
import os

import pytest

pytest.importorskip("PyQt6")

from dossier.core import servers  # noqa: E402
from dossier.gui.servers import ConnectionDialog  # noqa: E402
from tests import catalog_server as cs  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import lab, save, wait  # noqa: E402,F401


@pytest.fixture
def catalog(lab):
    server, port = cs.start()
    win, d, left, right, tmp = lab
    win.catalog_port = port
    yield win, d, left, right, tmp
    server.shutdown()


def save_catalog(win, kind, **kw):
    kw.setdefault("name", "Books" if kind == "opds" else "Music")
    return save(win, protocol=kind, host="127.0.0.1", port=win.catalog_port, secure=False, user=cs.USER, **kw)


def test_the_dialog_for_a_catalogue_is_read_only_and_keeps_its_kind_when_an_address_is_pasted(lab):
    win, *_ = lab
    dlg = ConnectionDialog(win)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("opds"))
    assert "address of the catalogue" in dlg.start_dir.placeholderText() or "catalogue" in dlg.start_dir.placeholderText()
    assert not dlg._form.isRowVisible(dlg.read_only) and not dlg._form.isRowVisible(dlg._key_row) and dlg._form.isRowVisible(dlg.secure)
    assert dlg.port.value() == 443 and "Read-only" in dlg.type_note.text()
    dlg.host.setText("https://books.example.com:8443/opds")
    dlg.host.editingFinished.emit()
    c = dlg.connection()
    assert (c.protocol, c.host, c.port, c.start_dir, c.read_only) == ("opds", "books.example.com", 8443, "/opds", True)
    assert c.describe().startswith("OPDS  books.example.com:8443/opds") and c.url("/") == "opds://books.example.com:8443/"
    dlg.protocol.setCurrentIndex(dlg.protocol.findData("subsonic"))
    assert dlg.connection().read_only and "Subsonic" in dlg.connection().describe() and "music server" in dlg.type_note.text()


def test_a_catalogue_is_read_only_even_if_the_saved_file_says_otherwise():
    saved = servers.to_json([servers.Connection("b", "h", protocol="opds", read_only=False, start_dir="/opds")])
    assert servers.from_json(saved)[0].read_only is True


def test_an_opds_catalogue_asks_for_a_login_opens_and_a_book_can_be_copied_out(catalog):
    win, d, left, right, tmp = catalog
    c = save_catalog(win, "opds", start_dir="/opds")
    win.answers["password"] = ("wrong", False)
    d.confirm_answer = False
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: any("refused" in t.lower() or "wrong" in t.lower() for _title, t in d.infos))
    assert not win.fs.opds.connected(c.authority())
    d.infos.clear()
    d.confirm_answer = True                                       # the copy below is confirmed
    win.answers["password"] = (cs.PASSWORD, False)
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.right.path == c.url("/") and win.right.model.row_of("The Sea Wolf.epub") >= 0)
    assert win.fs.opds.connected(c.authority()) and not win.fs.dav.connected(c.authority())
    assert win.right.model.row_of("New books") >= 0 and win.right.model.row_of("Not for sale") < 0
    win._set_active(win.right)
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("The Sea Wolf.epub"), 0))
    win.copy()                                                    # to the other panel: the local folder
    wait(win, lambda: (left / "The Sea Wolf.epub").exists() and not win.busy, timeout=15)
    assert (left / "The Sea Wolf.epub").read_bytes() == cs.BOOKS["1"][1]
    win.delete()                                                  # a catalogue cannot be changed
    pump(win)
    assert win.right.model.row_of("The Sea Wolf.epub") >= 0


def test_a_subsonic_server_shows_artists_albums_and_tracks_and_a_track_copies_exactly(catalog):
    win, d, left, right, tmp = catalog
    c = save_catalog(win, "subsonic")
    win.answers["password"] = (cs.PASSWORD, False)
    win.open_server(c.url("/"), False, win.right)
    wait(win, lambda: win.right.path == c.url("/") and win.right.model.row_of("Artists") >= 0)
    album = c.url("/Artists/The Band/First Album (1999)")
    win.right.set_folder(album)
    wait(win, lambda: win.right.path == album and win.right.model.row_of("1-02 Second Song.mp3") >= 0)
    win._set_active(win.right)
    win.right.table.setCurrentIndex(win.right.model.index(win.right.model.row_of("1-02 Second Song.mp3"), 0))
    win.copy()
    wait(win, lambda: (left / "1-02 Second Song.mp3").exists() and not win.busy, timeout=15)
    assert (left / "1-02 Second Song.mp3").read_bytes() == cs.SONGS["s2"][4]


def test_enter_on_a_track_downloads_it_and_hands_it_to_the_system_player(catalog, monkeypatch):
    from dossier.gui import unpack
    opened = []
    monkeypatch.setattr(unpack.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile()) or True))
    win, d, left, right, tmp = catalog
    c = save_catalog(win, "subsonic")
    win.answers["password"] = (cs.PASSWORD, False)
    album = c.url("/Artists/The Band/First Album (1999)")
    win.open_server(c.url("/"), False, win.left)
    wait(win, lambda: win.left.path == c.url("/"))
    win.left.set_folder(album)
    wait(win, lambda: win.left.path == album and win.left.model.row_of("1-01 Opening.mp3") >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("1-01 Opening.mp3"), 0))
    win.left.open_current()
    wait(win, lambda: len(opened) == 1, timeout=15)
    assert os.path.basename(opened[0]) == "1-01 Opening.mp3" and open(opened[0], "rb").read() == cs.SONGS["s1"][4]
