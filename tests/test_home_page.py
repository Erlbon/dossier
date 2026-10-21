"""The Home page in the panels: opening it, its entries, pins and network locations, and what it refuses."""
import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from tests.helpers import activate_window  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.home import ADD_NETWORK, HOME_URL  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs, key  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def world(app, tmp_path):
    drive = tmp_path / "drive"
    folder = drive / "folder"
    folder.mkdir(parents=True)
    (folder / "f.txt").write_text("x")
    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(folder), str(tmp_path)), dialogs=dialogs)
    # a made-up computer: one fixed drive (the temp folder acts as its root), one removable
    win.home_provider.volumes = lambda: [(str(drive), "Data", "fixed"), (str(tmp_path / "usb"), "Stick", "removable")]
    win.home_provider.home = lambda: str(folder)
    win.home_provider.exists = lambda p: os.path.isdir(p)
    win.show()
    win.activateWindow()
    activate_window(win)
    yield win, dialogs, drive, folder, tmp_path
    win.close()


def pump(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def rows(panel):
    m = panel.model
    return [(m.entry_at(r).kind, m.entry_at(r).name) for r in range(m.entry_count())]


def row_of_kind(panel, kind, name=None):
    m = panel.model
    for r in range(m.entry_count()):
        e = m.entry_at(r)
        if e.kind == kind and (name is None or e.name == name):
            return r
    raise AssertionError((kind, name, rows(panel)))


# getting there ---------------------------------------------------------------------------------------------------
def test_the_home_button_the_menu_the_shortcut_and_the_address_all_open_the_page(world):
    win, _d, drive, folder, tmp = world
    p = win.left
    p.home_button.click()
    assert p.is_home and p.path == HOME_URL and p.tabs.tabText(0) == "Home"
    p.set_folder(str(folder))
    QTest.keyClick(p.table, Qt.Key.Key_Home, Qt.KeyboardModifier.AltModifier)
    assert p.is_home
    p.set_folder(str(folder))
    p.address.setText("home")
    p.address.returnPressed.emit()
    assert p.is_home


def test_backspace_above_a_drive_root_goes_to_the_page_and_lands_on_that_drive(world, monkeypatch):
    win, _d, drive, folder, tmp = world
    p = win.left
    p.set_folder(str(drive))
    monkeypatch.setattr(type(win.fs.local), "parent", lambda self, path: None if path == str(drive) else os.path.dirname(path))
    p.set_folder(str(drive))
    assert not p.model.is_up_row(0)                              # a root has no .. row
    QTest.keyClick(p.table, Qt.Key.Key_Backspace)
    assert p.is_home
    assert p.model.entry_at(p.table.currentIndex().row()).path == str(drive)


def test_the_page_lists_sections_with_headers_and_its_own_columns(world):
    win, _d, drive, folder, tmp = world
    p = win.left
    p.set_folder(HOME_URL)
    kinds = [k for k, _n in rows(p)]
    assert kinds[0] == "header" and "fixed" in kinds and "removable" in kinds and "place" in kinds
    assert kinds[-1] == "action"
    assert [p.model.headerData(i, Qt.Orientation.Horizontal) for i in range(3)] == ["Name", "Type", "Details"]
    first = p.table.currentIndex().row()
    assert first == p.model.first_selectable_row() and p.model.entry_kind(first) != "header"
    fixed = row_of_kind(p, "fixed")
    assert p.model.data(p.model.index(fixed, 1)) == "Local disk" and "Data" in p.model.data(p.model.index(fixed, 0))
    assert p.model.data(p.model.index(row_of_kind(p, "removable"), 1)) == "Removable disk"
    p.set_folder(str(drive))
    assert [p.model.headerData(i, Qt.Orientation.Horizontal) for i in range(3)] == ["Name", "Size", "Date"]


def test_section_headers_cannot_be_selected_and_the_page_does_not_re_sort(world):
    win, *_ = world
    p = win.left
    p.set_folder(HOME_URL)
    header_row = row_of_kind(p, "header")
    assert p.model.flags(p.model.index(header_row, 0)) == Qt.ItemFlag.NoItemFlags
    before = rows(p)
    p.model.sort(1, Qt.SortOrder.DescendingOrder)
    assert rows(p) == before


def test_free_space_arrives_later_in_the_background(world):
    win, _d, drive, *_ = world
    p = win.left
    p.set_folder(HOME_URL)
    fixed = row_of_kind(p, "fixed")
    pump(lambda: "free of" in p.model.data(p.model.index(fixed, 2)))
    assert "free of" in p.model.data(p.model.index(fixed, 2))


def test_opening_entries_goes_to_their_folders(world):
    win, _d, drive, folder, tmp = world
    p = win.left
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "fixed"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Return)
    assert p.path == str(drive)
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "place", os.path.basename(str(folder)) + " (your folder)"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Return)
    assert p.path == str(folder)


def test_the_cursor_cannot_stand_on_a_section_header(world):
    win, *_ = world
    p = win.left
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "header"), 0))
    assert p.model.entry_kind(p.table.currentIndex().row()) != "header"
    QTest.keyClick(p.table, Qt.Key.Key_Up)                               # arrow keys step over headers too
    assert p.model.entry_kind(p.table.currentIndex().row()) != "header"


# pins -----------------------------------------------------------------------------------------------------------------
def test_pin_a_folder_see_it_on_the_page_and_keep_it_across_sessions(world):
    win, dialogs, drive, folder, tmp = world
    QTest.keyClick(win.left.table, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    win.left.set_folder(HOME_URL)
    assert ("pin", "folder") in rows(win.left)
    win.left.set_folder(str(folder))
    win.pin_folder()                                            # pinning the same folder again changes nothing
    assert "already" in win.status.text()
    win.left.set_folder(HOME_URL)
    assert [k for k, _n in rows(win.left)].count("pin") == 1
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), start=(HOME_URL, HOME_URL), dialogs=FakeDialogs())
    try:
        assert again.left.is_home and ("pin", "folder") in rows(again.left)
    finally:
        again.close()


def test_pinning_is_refused_on_the_page_itself(world):
    win, dialogs, *_ = world
    win.left.set_folder(HOME_URL)
    win.pin_folder()
    assert dialogs.infos and "Open the folder" in dialogs.infos[-1][1]


def test_remove_a_pin_with_delete_and_the_folder_stays(world):
    win, dialogs, drive, folder, tmp = world
    win.pin_folder()
    p = win.left
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "pin"), 0))
    dialogs.confirm_answer = False
    QTest.keyClick(p.table, Qt.Key.Key_F8)
    assert any(k == "pin" for k, _n in rows(p))                 # declined: still there
    dialogs.confirm_answer = True
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "pin"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_F8)
    assert not any(k == "pin" for k, _n in rows(p)) and folder.is_dir() and (folder / "f.txt").exists()
    assert "Removed" in win.status.text()


def test_a_drive_or_a_place_cannot_be_removed_from_the_page(world):
    win, dialogs, drive, folder, tmp = world
    p = win.left
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "fixed"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Delete)
    assert "Only pinned folders" in dialogs.infos[-1][1] and any(k == "fixed" for k, _n in rows(p))
    assert drive.is_dir()


# network locations ------------------------------------------------------------------------------------------------------
def _says(win, monkeypatch, address):
    """Make the Add a Network Share dialog answer with ``address`` (an SMB share, saved, not mounted)."""
    from PyQt6.QtWidgets import QDialog

    def fake(self, dlg):
        dlg.address.setText(address)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(type(win), "_ask_mount", fake)


def test_f7_on_the_page_adds_a_network_location_and_the_entry_does_the_same(world, monkeypatch):
    win, dialogs, drive, folder, tmp = world
    p = win.left
    p.set_folder(HOME_URL)
    _says(win, monkeypatch, "\\\\nas\\media")
    QTest.keyClick(p.table, Qt.Key.Key_F7)
    assert ("netloc", "\\\\nas\\media") in rows(p)
    win._home_action(ADD_NETWORK)                               # the same address again: not added twice
    assert [k for k, _n in rows(p)].count("netloc") == 1 and "already" in win.status.text()
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "action"), 0))
    _says(win, monkeypatch, "\\\\other\\share")
    QTest.keyClick(p.table, Qt.Key.Key_Return)                  # opening the action entry asks for an address
    assert ("netloc", "\\\\other\\share") in rows(p)


def test_a_server_address_is_explained_not_saved(world):
    win, dialogs, *_ = world
    win.left.set_folder(HOME_URL)
    win.save_network_location("sftp://host/path")
    assert "SFTP" in dialogs.infos[-1][1] and not any(k == "netloc" for k, _n in rows(win.left))


def test_remove_a_saved_network_location(world):
    win, dialogs, *_ = world
    p = win.left
    p.set_folder(HOME_URL)
    win.save_network_location("\\\\nas\\media")
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "netloc"), 0))
    win.remove_from_home()
    assert not any(k == "netloc" for k, _n in rows(p))


# what the page refuses ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key_", [Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4, Qt.Key.Key_F5, Qt.Key.Key_F6])
def test_file_commands_on_the_page_explain_that_these_are_shortcuts(world, key_):
    win, dialogs, *_ = world
    win.left.set_folder(HOME_URL)
    QTest.keyClick(win.left.table, key_)
    assert dialogs.infos and "shortcuts" in dialogs.infos[-1][1]


def test_nothing_can_be_marked_on_the_page(world):
    win, *_ = world
    p = win.left
    p.set_folder(HOME_URL)
    p.table.setCurrentIndex(p.model.index(row_of_kind(p, "place"), 0))
    QTest.keyClick(p.table, Qt.Key.Key_Space)
    QTest.keyClick(p.table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(p.table, Qt.Key.Key_Insert)
    QApplication.processEvents()
    assert len(win.selection) == 0 and p.targets() == []


def test_the_command_line_and_the_terminal_need_a_real_folder(world):
    win, dialogs, *_ = world
    win.left.set_folder(HOME_URL)
    win.cmdline.setText("echo hi")
    win.run_command_line()
    assert "shortcuts" in dialogs.infos[-1][1]
    count = len(dialogs.infos)
    win.open_terminal()
    assert len(dialogs.infos) == count + 1 and "this computer" in dialogs.infos[-1][1]


def test_marks_made_elsewhere_are_not_shown_or_counted_on_the_page(world):
    win, dialogs, drive, folder, tmp = world
    win.selection.add([str(folder / "f.txt")])
    p = win.left
    p.set_folder(HOME_URL)
    assert not any(p.model.is_marked(p.model.entry_at(r)) for r in range(p.model.entry_count()))
    assert len(win.selection) == 1                                # the selection itself is untouched


# the page is a tab like any other -------------------------------------------------------------------------------------------------------------
def test_a_tab_can_show_the_page_and_it_is_restored_with_the_session(world):
    win, dialogs, drive, folder, tmp = world
    p = win.left
    p.new_tab(HOME_URL)
    assert p.is_home and [p.tabs.tabText(i) for i in range(p.tabs.count())] == ["folder", "Home"]
    p.tabs.setCurrentIndex(0)
    assert not p.is_home and p.path == str(folder)
    p.tabs.setCurrentIndex(1)
    assert p.is_home
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs())
    try:
        assert [again.left.tabs.tabText(i) for i in range(again.left.tabs.count())] == ["folder", "Home"]
        assert again.left.is_home
    finally:
        again.close()


def test_the_menus_offer_pin_add_and_the_home_page(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Pin Folder to Home Page" in [a.text() for a in menus["Go"].actions()]
    assert "Add Network Share..." in [a.text() for a in menus["Network"].actions()]
    assert "Home Page" in [a.text() for a in menus["Go"].actions()]
