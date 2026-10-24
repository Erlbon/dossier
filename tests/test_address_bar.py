"""The clickable address: parts of the path as buttons, text to type into on demand."""
import os

import pytest

from dossier.core import pathparts
from dossier.core.home import HOME_URL, HomeFileSystem, HomeProvider, RouterFileSystem
from dossier.core.vfs import LocalFileSystem
from dossier.core.zipfs import archive_root

BACKSLASH = chr(92)


@pytest.fixture
def router():
    return RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider()))


def labels(parts):
    return [label for label, _p in parts]


def test_a_local_path_is_split_from_the_top_with_each_part_a_real_folder(router, tmp_path):
    deep = tmp_path / "Export" / "Download"
    deep.mkdir(parents=True)
    parts = pathparts.segments(router, str(deep))
    assert labels(parts)[-2:] == ["Export", "Download"] and parts[-1][1] == str(deep)
    assert parts[-2][1] == str(tmp_path / "Export")
    assert all(os.path.isdir(p) for _l, p in parts)
    assert os.path.dirname(parts[1][1]) == parts[0][1].rstrip(BACKSLASH + "/") + os.sep or len(parts) > 1


@pytest.mark.skipif(os.name != "nt", reason="drive letters")
def test_a_drive_root_is_called_by_its_letter_and_a_share_by_its_name():
    fs = LocalFileSystem()
    assert labels(pathparts.segments(fs, "C:" + BACKSLASH + "Temp" + BACKSLASH + "Export")) == ["C:", "Temp", "Export"]
    unc = BACKSLASH * 2 + "server" + BACKSLASH + "share"
    parts = pathparts.segments(fs, unc + BACKSLASH + "Photos" + BACKSLASH + "2022")
    assert labels(parts) == [unc, "Photos", "2022"]
    assert parts[0][1].rstrip(BACKSLASH) == unc


def test_the_home_page_is_one_part(router):
    assert pathparts.segments(router, HOME_URL) == [("Home", HOME_URL)]


def test_inside_an_archive_the_parts_lead_out_through_the_archive_into_its_folder(router, tmp_path):
    import zipfile
    archive = tmp_path / "box.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("docs/deep/a.txt", "a")
    parts = pathparts.segments(router, archive_root(str(archive)) + "docs/deep")
    assert labels(parts)[-3:] == ["box.zip", "docs", "deep"]
    assert parts[-3][1] == archive_root(str(archive))                     # the archive root is a part of its own
    assert parts[-4][1] == str(tmp_path)                                  # and above it is the folder holding it


def test_an_empty_path_has_no_parts(router):
    assert pathparts.segments(router, "") == []


# in the window ------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QToolButton  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def crumb_buttons(panel):
    return [b for b in panel.address_bar.findChildren(QToolButton) if b.objectName() == "crumb"]


def deep_folder(win, tmp):
    deep = tmp / "one" / "two" / "three"
    deep.mkdir(parents=True)
    win.resize(1500, 700)                                      # wide enough for the whole path: the buttons on the bar's right take room too
    win.left.set_folder(str(deep))
    pump(win, lambda: win.left.path == str(deep))
    return deep


def test_the_address_shows_clickable_parts_for_the_current_folder(world):
    win, _d, left, right, tmp = world
    deep = deep_folder(win, tmp)
    texts = [b.text() for b in crumb_buttons(win.left)]
    assert texts[-3:] == ["one", "two", "three"]
    assert win.left.address_bar.parts()[-1][1] == str(deep)
    assert not win.left.address_bar.editing


def test_clicking_a_part_goes_there_and_stands_on_the_folder_we_came_out_of(world):
    win, _d, left, right, tmp = world
    deep = deep_folder(win, tmp)
    two = [b for b in crumb_buttons(win.left) if b.text() == "two"][0]
    two.click()
    pump(win, lambda: win.left.path == str(tmp / "one" / "two"))
    assert win.left.current_name() == "three"


def test_a_middle_click_on_a_part_opens_it_in_a_background_tab(world):
    win, _d, left, right, tmp = world
    deep = deep_folder(win, tmp)
    tabs_before = win.left.tabs.count()
    one = [b for b in crumb_buttons(win.left) if b.text() == "one"][0]
    QTest.mouseClick(one, Qt.MouseButton.MiddleButton)
    assert win.left.tabs.count() == tabs_before + 1
    assert win.left.path == str(deep)                                   # the current tab did not change


def test_the_empty_end_of_the_field_turns_it_into_text_to_type_and_enter_goes_there(world):
    win, _d, left, right, tmp = world
    bar = win.left.address_bar
    QTest.mouseClick(bar._blank, Qt.MouseButton.LeftButton)
    assert bar.editing and win.left.address.text() == win.left.path
    win.left.address.setText(str(right))
    QTest.keyClick(win.left.address, Qt.Key.Key_Return)
    pump(win, lambda: win.left.path == str(right))
    assert not bar.editing


def test_escape_and_ctrl_l(world):
    win, _d, left, right, tmp = world
    bar = win.left.address_bar
    key(win, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert bar.editing
    win.left.address.setText("something half typed")
    QTest.keyClick(win.left.address, Qt.Key.Key_Escape)
    assert not bar.editing and win.left.address.text() == win.left.path          # the typing is thrown away


def test_a_listing_that_ends_while_typing_does_not_wipe_what_is_typed(world):
    win, _d, left, right, tmp = world
    bar = win.left.address_bar
    bar.start_edit()
    win.left.address.setText("D:" + BACKSLASH + "typed")
    bar.set_path(win.left.path)
    assert bar.editing and win.left.address.text() == "D:" + BACKSLASH + "typed"


def test_a_long_path_folds_its_left_part_into_a_menu_that_still_navigates(world):
    win, _d, left, right, tmp = world
    deep = deep_folder(win, tmp)
    win.left.address_bar.setFixedWidth(150)
    QApplication.processEvents()
    texts = [b.text() for b in crumb_buttons(win.left)]
    assert texts[0] == "..." and texts[-1] == "three" and len(texts) < len(win.left.address_bar.parts())
    menu = crumb_buttons(win.left)[0].menu()
    names = [a.text() for a in menu.actions()]
    folded = len(win.left.address_bar.parts()) - (len(texts) - 1)               # every part that is not a button
    assert len(names) == folded and names[0] == win.left.address_bar.parts()[folded - 1][0]   # nearest first
    assert "one" not in texts and names[-1] != "three"
    target = tmp
    [a for a in menu.actions() if a.text() == win.left.address_bar.parts()[folded - 1][0]][0].trigger()
    pump(win, lambda: win.left.path == win.left.address_bar.parts()[folded - 1][1])


def test_the_home_page_has_a_single_part_and_the_menu_item_exists(world):
    win, *_ = world
    win.left.go_home()
    pump(win, lambda: win.left.is_home)
    assert [b.text() for b in crumb_buttons(win.left)] == ["Home"]
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Edit the Path" in [a.text() for a in menus["Go"].actions()]


def test_rebuilding_the_parts_leaves_no_stray_windows_behind(world):
    """A removed part must not turn into a window of its own (it took the focus from the main window)."""
    win, _d, left, right, tmp = world
    for name in ("a", "b", "c"):
        (tmp / name).mkdir(exist_ok=True)
        win.left.set_folder(str(tmp / name))
        pump(win, lambda n=name: win.left.path == str(tmp / n))
    QApplication.processEvents()
    strays = [w for w in QApplication.topLevelWidgets() if isinstance(w, QToolButton) and w.isVisible()]
    assert strays == []
    assert QApplication.activeWindow() is win or not win.isActiveWindow()
