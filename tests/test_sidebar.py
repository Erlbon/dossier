"""The sidebar (card 60B): hidden until View > Bars > Sidebar, remembered, fed by the Home page's entries on a thread."""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.home import ServerItem  # noqa: E402
from dossier.core.trash import TITLE as TRASH_TITLE  # noqa: E402
from dossier.gui import sidebar as sidebar_module  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.helpers import activate_window  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402,F401
from tests.test_home_page import app, pump  # noqa: E402,F401


@pytest.fixture
def world(app, tmp_path):
    drive = tmp_path / "drive"
    folder = drive / "folder"
    folder.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(folder), str(tmp_path)), dialogs=FakeDialogs())
    win.home_provider.volumes = lambda: [(str(drive), "Data", "fixed"), (str(tmp_path / "usb"), "Stick", "removable")]
    win.home_provider.home = lambda: str(folder)
    win.home_provider.exists = lambda p: os.path.isdir(p)
    win._save_list("home/pins", [str(other)])
    win.show()
    win.activateWindow()
    activate_window(win)
    yield win, drive, folder, other, tmp_path
    win.close()


def shown(win):
    return [(e.kind, e.name) for e in win.sidebar.entries()]


def ready(win, kind):
    pump(lambda: any(e.kind == kind for e in win.sidebar.entries()))


def test_hidden_by_default_and_view_menu_shows_it_and_remembers(world):
    win, *_rest, tmp = world
    assert not win.sidebar.isVisibleTo(win) and not win.act_sidebar.isChecked()
    assert not win.sidebar.entries()                       # nothing is read while it is hidden
    win.act_sidebar.setChecked(True)
    assert win.sidebar.isVisibleTo(win)
    ready(win, "trash")
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), start=(str(tmp), str(tmp)), dialogs=FakeDialogs())
    try:
        assert again.act_sidebar.isChecked() and not again.sidebar.isHidden()
    finally:
        again.close()


def test_lists_pins_drives_and_the_trash_from_the_home_data(world):
    win, drive, folder, other, tmp = world
    win.home_provider.servers = lambda: [ServerItem("Box", "sftp://u@h/", "u@h")]
    win.act_sidebar.setChecked(True)
    ready(win, "server")
    kinds = [k for k, _n in shown(win)]
    assert kinds == ["pin", "fixed", "removable", "server", "trash"]
    names = [n for _k, n in shown(win)]
    assert names[0] == "other" and names[-1] == TRASH_TITLE
    headings = [h for h, _es in win.sidebar.groups]
    assert headings == ["Pinned", "Drives", "Servers", ""]


def test_a_click_opens_in_the_active_panel_and_follows_the_active_panel(world):
    win, drive, folder, other, tmp = world
    win.act_sidebar.setChecked(True)
    ready(win, "pin")
    pin = next(e for e in win.sidebar.entries() if e.kind == "pin")
    win._set_active(win.left)
    win.sidebar.place_clicked.emit(pin)
    pump(lambda: os.path.normcase(win.left.path) == os.path.normcase(str(other)))
    assert os.path.normcase(win.right.path) == os.path.normcase(str(tmp))
    fixed = next(e for e in win.sidebar.entries() if e.kind == "fixed")
    win._set_active(win.right)
    win.sidebar.place_clicked.emit(fixed)
    pump(lambda: os.path.normcase(win.right.path) == os.path.normcase(str(drive)))
    assert os.path.normcase(win.left.path) == os.path.normcase(str(other))


def test_the_trash_entry_opens_the_trash(world, monkeypatch):
    win, *_rest = world
    win.act_sidebar.setChecked(True)
    ready(win, "trash")
    opened = []
    monkeypatch.setattr(type(win), "open_trash", lambda self, panel=None, new_tab=False: opened.append(panel))
    win.sidebar.place_clicked.emit(next(e for e in win.sidebar.entries() if e.kind == "trash"))
    assert opened == [win.active]


def test_a_server_entry_connects_as_from_the_home_page(world, monkeypatch):
    win, *_rest = world
    win.home_provider.servers = lambda: [ServerItem("Box", "sftp://u@h/", "u@h")]
    win.act_sidebar.setChecked(True)
    ready(win, "server")
    opened = []
    monkeypatch.setattr(type(win), "open_server", lambda self, path, new_tab=False, panel=None: opened.append((path, new_tab, panel)))
    win.sidebar.place_clicked.emit(next(e for e in win.sidebar.entries() if e.kind == "server"))
    assert opened == [("sftp://u@h/", False, win.active)]


def test_the_eject_mark_runs_eject_and_only_ejectable_drives_have_one(world, monkeypatch):
    win, *_rest = world
    win.act_sidebar.setChecked(True)
    ready(win, "removable")
    marks = [win.sidebar.itemWidget(win.sidebar.item(i)) for i in range(win.sidebar.count())]
    marks = [m for m in marks if m is not None]
    assert len(marks) == 1                                 # the stick, not the fixed drive, the pin or the Trash
    calls = []
    monkeypatch.setattr(type(win), "eject_drive", lambda self, root, kind, title="": calls.append((root, kind, title)))
    marks[0].findChild(sidebar_module.QToolButton).click()
    stick = next(e for e in win.sidebar.entries() if e.kind == "removable")
    assert calls == [(stick.path, "removable", sidebar_module.short_title(stick))]
    menu = win.sidebar_menu(stick)
    assert [a.text() for a in menu.actions() if a.text()] == ["Open", "Open in the Other Panel", "Eject"]
    assert [a.text() for a in win.sidebar_menu(next(e for e in win.sidebar.entries() if e.kind == "pin")).actions() if a.text()] \
        == ["Open", "Open in the Other Panel"]


def test_the_places_are_read_on_a_thread(world, monkeypatch):
    win, *_rest = world
    where = []
    real = sidebar_module.build_entries

    def watch(provider):
        where.append(threading.current_thread() is threading.main_thread())
        return real(provider)
    monkeypatch.setattr(sidebar_module, "build_entries", watch)
    win.act_sidebar.setChecked(True)
    ready(win, "trash")
    win.home_provider.volumes = lambda: [(str(world[1]), "Data", "fixed")]
    win.refresh_sidebar()
    pump(lambda: not any(e.kind == "removable" for e in win.sidebar.entries()))
    assert where and not any(where)
    assert QApplication.instance() is not None
