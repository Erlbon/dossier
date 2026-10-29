"""The frosted file manager: the frame shows a blurred picture of the screen, the file lists stay solid, the setting is remembered."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QRect, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import frost  # noqa: E402
from dossier.gui.frost_window import FrostDialog  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs, app, pump, world  # noqa: E402,F401


def fake_screens(win):
    """A picture of the screen: bright red, the size of the screen the window is on."""
    screen = win.screen()
    shot = QPixmap(screen.geometry().size())
    shot.fill(QColor("#ff0000"))
    return {screen.name(): (screen.geometry(), shot)}


@pytest.fixture(autouse=True)
def not_frosted_afterwards():
    yield
    frost.set_active(False)


def frame_pixel(win):
    """The colour of the window in the frame (just left of the status line) and in the middle of the left file list."""
    image = win.grab().toImage()
    edge = win.status.mapTo(win, win.status.rect().bottomLeft())
    centre = win.left.table.mapTo(win, win.left.table.rect().center())
    return image.pixelColor(max(1, edge.x() - 4), edge.y() - 2), image.pixelColor(centre.x(), centre.y())


def test_turning_it_on_frosts_the_frame_and_leaves_the_lists_solid(world):
    win, *_ = world
    assert not frost.active()
    assert win.set_frost(True, 40, grabber=lambda: fake_screens(win), wait_ms=0)
    QApplication.processEvents()
    frame, lists = frame_pixel(win)
    assert frame.red() - frame.blue() > 30                          # the red picture shows through the frame, tinted
    assert abs(lists.red() - lists.blue()) < 30                     # the list is its own solid colour, not the picture
    assert "transparent" in win.tools_bar.styleSheet()
    win.set_frost(False)
    assert not frost.active() and "transparent" not in win.tools_bar.styleSheet().split("#toolsbar QToolButton")[0]


def test_the_setting_and_the_strength_are_remembered_and_come_back_at_start(world, tmp_path, monkeypatch):
    win, *_ = world
    win.set_frost(True, 55, grabber=lambda: fake_screens(win), wait_ms=0)
    assert str(win.settings.value("frost/on")) == "true" and str(win.settings.value("frost/level")) == "55"
    monkeypatch.setattr(frost, "grab_screens", lambda: fake_screens(win))
    again = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path / "left"), str(tmp_path / "right")), dialogs=FakeDialogs())
    assert frost.active() and again._frost_level == 55
    again.close()
    win.set_frost(False)
    other = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path / "left"), str(tmp_path / "right")), dialogs=FakeDialogs())
    assert not frost.active()
    other.close()


def test_no_picture_of_the_screen_means_no_frost(world):
    win, *_ = world
    assert win.set_frost(True, 40, grabber=lambda: {}, wait_ms=0) is False
    assert not frost.active()


def test_a_remote_session_gets_no_frost(world, monkeypatch):
    from dossier.core import platform
    win, *_ = world
    monkeypatch.setattr(platform, "is_remote_session", lambda: True)
    assert win.set_frost(True, 40, grabber=lambda: fake_screens(win), wait_ms=0) is False
    assert "remote" in win.status.text()


def test_the_blur_strength_is_the_share_of_the_screen_that_shows_through():
    assert frost.tint_alpha(40) == round(255 * 0.6) and frost.tint_alpha(1) > frost.tint_alpha(80)
    assert frost.tint_alpha(500) == frost.tint_alpha(frost.MAX_LEVEL)             # never fully clear


def test_the_settings_page_through_a_real_exec_turns_it_on(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(frost, "grab_screens", lambda: fake_screens(win))

    def choose():
        box = QApplication.activeModalWidget()
        assert isinstance(box, FrostDialog)
        box.on.setChecked(True)
        box.slider.setValue(30)
        box.accept()
    QTimer.singleShot(50, choose)
    win.open_frost_settings()
    assert frost.active() and win._frost_level == 30
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    appearance = next(a.menu() for a in menus["Settings"].actions() if a.text() == "Appearance")
    assert "Frosted Background..." in [a.text() for a in appearance.actions()]


def test_apply_shows_the_effect_with_the_dialog_open_and_cancel_puts_it_back(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(frost, "grab_screens", lambda: fake_screens(win))
    seen = []

    def apply_then_cancel():
        box = QApplication.activeModalWidget()
        box.on.setChecked(True)
        box.slider.setValue(35)
        box.applied.emit(*box.values())
        seen.append((frost.active(), win._frost_level, box.isVisible()))         # the effect is on while the dialog is still there
        box.reject()
    QTimer.singleShot(50, apply_then_cancel)
    win.open_frost_settings()
    assert seen == [(True, 35, True)]
    assert not frost.active() and str(win.settings.value("frost/on")) == "false"      # cancelled: as before


def test_the_title_bar_gets_windows_frosted_look_while_the_frame_is_frosted(world, monkeypatch):
    from dossier.core import platform
    win, *_ = world
    calls = []
    monkeypatch.setattr(platform, "set_title_backdrop", lambda hwnd, on, dark=False: calls.append(on) or True)
    win.set_frost(True, 40, grabber=lambda: fake_screens(win), wait_ms=0)
    win.set_frost(False)
    assert calls[-2:] == [True, False]


def test_the_title_backdrop_call_is_a_harmless_no_on_other_systems(monkeypatch):
    from dossier.core import platform
    monkeypatch.setattr(platform, "IS_WINDOWS", False)
    assert platform.set_title_backdrop(1, True) is False


# the notepad and the viewer ------------------------------------------------------------------------------------------------------
def test_the_notepad_has_one_floating_bar_with_everything_in_it(tmp_path):
    pytest.importorskip("PyQt6.Qsci")
    from dossier.core.textedit import load_document
    from dossier.gui.notepad import NotepadWindow
    p = tmp_path / "a.py"
    p.write_text("x = 1" + chr(10), encoding="utf-8")
    win = NotepadWindow(load_document(str(p)), FakeDialogs())
    win.show()
    QApplication.processEvents()
    assert {"file", "edit", "view", "save", "find", "goto", "settings", "close"} <= set(win.floating.buttons)
    assert not win.menuBar().isVisible() and win.statusBar().isHidden()          # no menu bar, no status line
    assert win.position.text()                                                   # the cursor position is in the bar
    win.floating.buttons["find"].click()
    assert win.bar.isVisible()
    win.floating.buttons["view"].click()
    assert win.view_menu.isVisible()
    win.view_menu.close()
    win.close()


def test_the_notepad_and_the_viewer_give_their_title_bars_the_frost(world, tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.Qsci")
    from dossier.core import platform
    from dossier.core.textedit import load_document
    from dossier.gui.notepad import NotepadWindow
    from dossier.gui.viewer import TextViewerWindow
    win, *_ = world
    p = tmp_path / "a.txt"
    p.write_text("hello" + chr(10), encoding="utf-8")
    pad = NotepadWindow(load_document(str(p)), FakeDialogs())
    viewer = TextViewerWindow([str(p)])
    for w in (pad, viewer):
        w.show()
    calls = []
    monkeypatch.setattr(platform, "set_title_backdrop", lambda hwnd, on, dark=False: calls.append(on) or True)
    win.set_frost(True, 40, grabber=lambda: fake_screens(win), wait_ms=0)
    QApplication.processEvents()
    assert calls.count(True) >= 3                                        # the file manager and both windows
    win.set_frost(False)
    assert calls.count(False) >= 3
    pad.close()
    viewer.close()


def test_a_bright_picture_does_not_make_a_bright_patch_in_the_dark_scheme(world, monkeypatch):
    from dossier.gui import frost_window, theme
    win, *_ = world
    monkeypatch.setattr(theme, "_current", dict(theme.DARK))
    white = {win.screen().name(): (win.screen().geometry(), QPixmap(win.screen().geometry().size()))}
    white[win.screen().name()][1].fill(QColor("#ffffff"))
    win.set_frost(True, 90, grabber=lambda: white, wait_ms=0)
    QApplication.processEvents()
    frame, _ = frame_pixel(win)
    ceiling = QColor(theme.current()["card"]).lighter(frost_window.CEILING)
    assert frame.lightness() <= ceiling.lightness() + 2
    win.set_frost(False)
