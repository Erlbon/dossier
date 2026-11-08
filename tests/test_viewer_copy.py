"""Copy in the viewers: the picture (F3 and the glass viewer) goes to the clipboard as a picture and as its file; the text viewer selects
all with Ctrl+A and has a Copy button that works in every mode."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core import glass  # noqa: E402
from dossier.core.glass import Capabilities  # noqa: E402
from dossier.gui import file_clipboard  # noqa: E402
from dossier.gui.glass_viewer import GlassViewer  # noqa: E402
from dossier.gui.viewer import TextViewerWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def windows(app):
    made = []
    yield made
    for w in made:
        w.close()
    QApplication.processEvents()
    QGuiApplication.clipboard().clear()                                  # no picture left for the tests that follow
    file_clipboard._inner = None


def make_picture(folder, name="wide.png", w=40, h=30):
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor("#4f7a4a"))
    path = str(folder / name)
    assert image.save(path)
    return path


def wait_for(check, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if check():
            return
        time.sleep(0.005)
    raise AssertionError("waited in vain")


def clipboard_picture():
    data = QGuiApplication.clipboard().mimeData()
    assert data is not None and data.hasImage()
    return QImage(data.imageData())


def clipboard_files():
    return [os.path.normcase(p) for p in file_clipboard.get()[0]]


def open_f3(windows, path):
    win = TextViewerWindow([path])
    win.show()
    windows.append(win)
    wait_for(lambda: win.image_page.view.has_image())
    return win


def test_ctrl_c_in_the_f3_picture_viewer_copies_the_picture_and_its_file(windows, tmp_path):
    path = make_picture(tmp_path)
    QGuiApplication.clipboard().clear()
    win = open_f3(windows, path)
    QTest.keyClick(win.image_page.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    picture = clipboard_picture()
    assert (picture.width(), picture.height()) == (40, 30)
    assert clipboard_files() == [os.path.normcase(path)]               # a folder pastes the file itself
    assert "Copied" in win.status.text()


def test_a_turned_picture_is_copied_as_it_is_shown(windows, tmp_path):
    win = open_f3(windows, make_picture(tmp_path))
    QTest.keyClick(win.image_page.view, Qt.Key.Key_R)
    win.floating.buttons["copy"].click()
    picture = clipboard_picture()
    assert (picture.width(), picture.height()) == (30, 40)


def test_the_f3_bar_has_a_copy_button_for_every_kind_of_file(windows, tmp_path):
    win = open_f3(windows, make_picture(tmp_path))
    assert not win.floating.buttons["copy"].isHidden()
    for mode in ("text", "hex", "markdown", "image"):
        assert "copy" in win.PILL_KEYS[mode]


def test_ctrl_c_and_the_copy_button_in_the_glass_viewer(windows, tmp_path):
    path = make_picture(tmp_path)
    win = GlassViewer([path], 0, glass.SOLID, capabilities=Capabilities(False, False))
    win.show()
    windows.append(win)
    wait_for(lambda: win.view.has_image())
    QGuiApplication.clipboard().clear()
    QTest.keyClick(win.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert clipboard_picture().width() == 40 and clipboard_files() == [os.path.normcase(path)]
    assert "Copied" in win.caption.text()                              # the caption says it for a moment
    QGuiApplication.clipboard().clear()
    win.buttons["copy"].click()
    assert clipboard_picture().height() == 30


def menu_texts(menu):
    return [a.text().split(chr(9))[0] for a in menu.actions() if not a.isSeparator()]


def test_right_click_on_the_picture_has_copy_in_both_viewers(windows, tmp_path):
    path = make_picture(tmp_path)
    f3 = open_f3(windows, path)
    glassy = GlassViewer([path], 0, glass.SOLID, capabilities=Capabilities(False, False))
    glassy.show()
    windows.append(glassy)
    wait_for(lambda: glassy.view.has_image())
    for view, said in ((f3.image_page.view, lambda: f3.status.text()), (glassy.view, lambda: glassy.caption.text())):
        menu = view.context_menu()
        assert menu_texts(menu) == ["Copy Picture", "Fit to Window", "Actual Size", "Turn Left", "Turn Right"]
        assert menu.actions()[0].text().endswith(chr(9) + "Ctrl+C")         # the menu teaches the key
        QGuiApplication.clipboard().clear()
        menu.actions()[0].trigger()
        assert clipboard_picture().width() == 40 and clipboard_files() == [os.path.normcase(path)]
        assert "Copied" in said()


def test_a_right_click_on_the_picture_opens_the_menu(windows, tmp_path, monkeypatch):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    win = open_f3(windows, make_picture(tmp_path))
    shown = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: shown.append(menu_texts(self)))
    viewport = win.image_page.view.viewport()
    QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), viewport.mapToGlobal(QPoint(5, 5))))
    assert shown and shown[0][0] == "Copy Picture"


def test_right_click_turns_the_picture_as_the_keys_do(windows, tmp_path):
    win = open_f3(windows, make_picture(tmp_path))
    view = win.image_page.view
    [a for a in view.context_menu().actions() if a.text().startswith("Turn Right")][0].trigger()
    assert view.shown_image().width() == 30


def test_with_no_picture_the_menu_items_are_greyed(app):
    from dossier.gui.image_view import ImageView
    view = ImageView()
    assert not any(a.isEnabled() for a in view.context_menu().actions() if not a.isSeparator())


def open_text(windows, tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data.encode("utf-8"))
    win = TextViewerWindow([str(p)])
    win.show()
    windows.append(win)
    wait_for(lambda: not win.busy)
    return win


def test_ctrl_a_selects_the_whole_text_and_the_copy_button_copies_it(windows, tmp_path):
    win = open_text(windows, tmp_path, "a.txt", "first line\nsecond\nlast")
    QTest.keyClick(win.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert win.view.has_selection()
    win.floating.buttons["copy"].click()
    assert QGuiApplication.clipboard().text() == "first line\nsecond\nlast"
    assert "Copied" in win.status.text()


def test_the_copy_button_with_nothing_selected_says_how_to_select(windows, tmp_path):
    win = open_text(windows, tmp_path, "a.txt", "hello\n")
    QGuiApplication.clipboard().setText("before")
    win.floating.buttons["copy"].click()
    assert QGuiApplication.clipboard().text() == "before" and "Ctrl+A" in win.status.text()


def test_the_copy_button_in_hex_copies_the_selected_bytes(windows, tmp_path):
    p = tmp_path / "b.bin"
    p.write_bytes(b"MZ\x00\x01")
    win = TextViewerWindow([str(p)])
    win.show()
    windows.append(win)
    wait_for(lambda: not win.busy)
    assert win.mode == "hex"
    QTest.keyClick(win.hex, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    win.floating.buttons["copy"].click()
    assert QGuiApplication.clipboard().text() == "4D 5A 00 01"
