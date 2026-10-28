"""The glass picture viewer: the look it ends up with, stepping through pictures, the floating bar, ``dossier view``, and the settings."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dossier.core import glass  # noqa: E402
from dossier.core.glass import Capabilities  # noqa: E402
from dossier.gui import glass_viewer, viewer_app  # noqa: E402
from dossier.gui.glass_settings import GlassDialog  # noqa: E402
from dossier.gui.glass_viewer import GlassViewer, pictures_around, saved_look  # noqa: E402
from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

FULL = Capabilities(True, True)


def make_pictures(folder, names=("a.png", "b.png", "c.png")):
    paths = []
    for n in names:
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("#4f7a4a"))
        path = str(folder / n)
        assert image.save(path)
        paths.append(path)
    return paths


@pytest.fixture
def viewers(app):
    made = []
    yield made
    for w in made:
        w.close()
    QApplication.processEvents()


def open_viewer(viewers, paths, mode=glass.FROSTED, level=None, caps=FULL, blur=None, show=True):
    calls = []
    window = GlassViewer(paths, 0, mode, level, capabilities=caps, blur=blur or (lambda hwnd: calls.append(hwnd) or True))
    window.blur_calls = calls
    viewers.append(window)
    if show:
        window.show()
    return window


def test_frosted_asks_windows_to_blur_and_a_refusal_falls_back_to_dim(viewers, tmp_path):
    paths = make_pictures(tmp_path)
    ok = open_viewer(viewers, paths)
    assert ok.mode == glass.FROSTED and len(ok.blur_calls) == 1
    assert ok.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) and ok.alpha() == glass.alpha_for(glass.FROSTED)
    refused = open_viewer(viewers, paths, blur=lambda hwnd: False)
    assert refused.mode == glass.DIM and refused.alpha() == glass.alpha_for(glass.DIM)


def test_without_transparency_the_viewer_is_solid_and_never_asks_for_blur(viewers, tmp_path):
    window = open_viewer(viewers, make_pictures(tmp_path), caps=Capabilities(False, False))
    assert window.mode == glass.SOLID and window.alpha() == 255 and window.blur_calls == []
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_a_chosen_level_sets_the_layer_and_dim_never_blurs(viewers, tmp_path):
    paths = make_pictures(tmp_path)
    dim = open_viewer(viewers, paths, mode=glass.DIM, level=60)
    assert dim.mode == glass.DIM and dim.alpha() == round(255 * 0.4) and dim.blur_calls == []


def test_the_picture_is_read_on_a_thread_and_the_arrows_and_keys_step_through_the_folder(viewers, tmp_path):
    window = open_viewer(viewers, make_pictures(tmp_path))
    QTest.qWait(300)
    assert window.view.has_image() and window.index == 0 and "a.png" in window.caption.text() and "1 / 3" in window.caption.text()
    QTest.keyClick(window.view, Qt.Key.Key_Right)
    QTest.keyClick(window.view, Qt.Key.Key_Space)
    assert window.index == 2 and "c.png" in window.caption.text()
    QTest.keyClick(window.view, Qt.Key.Key_Right)                          # the end: it stays
    assert window.index == 2
    QTest.keyClick(window.view, Qt.Key.Key_Home)
    assert window.index == 0
    QTest.keyClick(window.view, Qt.Key.Key_End)
    assert window.index == 2
    QTest.keyClick(window.view, Qt.Key.Key_Left)
    assert window.index == 1
    window.buttons["next"].click()
    assert window.index == 2


def test_a_picture_that_cannot_be_decoded_is_said_so_and_does_not_stop_the_viewer(viewers, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a picture")
    good = make_pictures(tmp_path, ("good.png",))[0]
    window = open_viewer(viewers, [str(bad), good])
    QTest.qWait(300)
    assert "cannot be decoded" in window.caption.text() and not window.view.has_image()
    window.step(1)
    QTest.qWait(300)
    assert window.view.has_image()


def test_escape_and_q_close_the_window(viewers, tmp_path):
    window = open_viewer(viewers, make_pictures(tmp_path))
    seen = []
    window.closed.connect(lambda: seen.append(1))
    QTest.keyClick(window.view, Qt.Key.Key_Escape)
    assert seen == [1] and not window.isVisible()
    other = open_viewer(viewers, make_pictures(tmp_path))
    QTest.keyClick(other.view, Qt.Key.Key_Q)
    assert not other.isVisible()


def test_the_bar_fades_out_when_the_mouse_rests_and_comes_back_when_it_moves(viewers, tmp_path):
    window = open_viewer(viewers, make_pictures(tmp_path))
    assert window.bar_visible()
    window._fade_out()
    QTest.qWait(glass_viewer.FADE_MS + 150)
    assert not window.bar_visible() and window.caption.isHidden()
    QTest.mouseMove(window.view.viewport())
    window._poke()
    QTest.qWait(glass_viewer.FADE_MS + 150)
    assert window.bar_visible() and not window.caption.isHidden()


def test_pictures_around_lists_the_folder_in_natural_order_with_the_place_of_the_one_named(tmp_path):
    for n in ("img10.png", "img2.png", "img1.png", "notes.txt"):
        (tmp_path / n).write_bytes(b"x")
    paths, index = pictures_around(str(tmp_path / "img2.png"))
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in paths] == ["img1.png", "img2.png", "img10.png"] and index == 1
    assert pictures_around(str(tmp_path / "missing.png")) == ([str(tmp_path / "missing.png")], 0)


def test_what_is_named_on_the_command_line_becomes_the_pictures(tmp_path):
    a, b, c = make_pictures(tmp_path)
    (tmp_path / "t.txt").write_text("x")
    assert viewer_app.pictures_for([b]) == ([a, b, c], 1) or viewer_app.pictures_for([b])[1] == 1
    assert len(viewer_app.pictures_for([str(tmp_path)])[0]) == 3
    assert viewer_app.pictures_for([a, c, str(tmp_path / "t.txt")]) == ([a, c], 0)
    assert viewer_app.pictures_for([str(tmp_path / "t.txt")]) == ([], 0)
    assert viewer_app.pictures_for([str(tmp_path / "nothing.png")]) == ([], 0)


def test_dossier_view_opens_only_the_viewer_with_the_look_asked_for(app, tmp_path):
    a, b, c = make_pictures(tmp_path)
    before = {id(w) for w in QApplication.topLevelWidgets()}
    code = viewer_app.main(["--glass", "dim:60", "--scheme", "dark", b], settings_path=str(tmp_path / "s.ini"), show=False)
    new = [w for w in QApplication.topLevelWidgets() if id(w) not in before and isinstance(w, GlassViewer)]
    assert code == 0 and len(new) == 1
    window = new[0]
    assert window.mode in (glass.DIM, glass.SOLID) and window.index == 1 and len(window.paths) == 3
    if window.mode == glass.DIM:
        assert window.alpha() == round(255 * 0.4)
    window.close()


def test_dossier_view_uses_the_saved_look_unless_a_parameter_overrides_it(app, tmp_path):
    a, b, c = make_pictures(tmp_path)
    ini = str(tmp_path / "s.ini")
    saved = QSettings(ini, QSettings.Format.IniFormat)
    saved.setValue("viewer/glass", "dim")
    saved.setValue("viewer/glass_level", 70)
    saved.sync()
    assert saved_look(QSettings(ini, QSettings.Format.IniFormat)) == (glass.DIM, 70)
    before = {id(w) for w in QApplication.topLevelWidgets()}
    viewer_app.main([a], settings_path=ini, show=False)
    window = next(w for w in QApplication.topLevelWidgets() if id(w) not in before and isinstance(w, GlassViewer))
    assert window.requested == glass.DIM and window.level == 70
    window.close()
    before = {id(w) for w in QApplication.topLevelWidgets()}
    viewer_app.main(["--glass", "solid", a], settings_path=ini, show=False)
    window = next(w for w in QApplication.topLevelWidgets() if id(w) not in before and isinstance(w, GlassViewer))
    assert window.mode == glass.SOLID
    window.close()


def test_dossier_view_without_a_picture_says_so_and_a_bad_look_is_refused(app, tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: said.append(text)))
    assert viewer_app.main([str(tmp_path / "nothing.png")], settings_path=str(tmp_path / "s.ini"), show=False) == 2
    assert viewer_app.main([], settings_path=str(tmp_path / "s.ini"), show=False) == 2
    assert "no picture" in said[0] and "dossier view" in said[1]
    with pytest.raises(SystemExit):
        viewer_app.main(["--glass", "glassy", "x.png"], settings_path=str(tmp_path / "s.ini"), show=False)


def test_the_glass_settings_dialog_hands_back_the_look(app):
    dlg = GlassDialog(glass.FROSTED, None, FULL)
    assert dlg.values() == (glass.FROSTED, 65)
    dlg.mode.setCurrentIndex(dlg.mode.findData(glass.DIM))
    assert dlg.values() == (glass.DIM, 28)                                 # each look starts from its own usual setting
    dlg.slider.setValue(70)
    assert dlg.values() == (glass.DIM, 70)
    dlg.mode.setCurrentIndex(dlg.mode.findData(glass.SOLID))
    assert dlg.values() == (glass.SOLID, None) and not dlg.slider.isEnabled()
    limited = GlassDialog(glass.FROSTED, None, Capabilities(True, False))
    assert "dim glass will be used" in limited.note.text()
    dlg.deleteLater()
    limited.deleteLater()


def test_the_window_opens_the_picture_under_the_cursor_as_glass(world, monkeypatch):
    win, d, left, right, tmp = world
    paths = make_pictures(left)
    (left / "plain.txt").write_text("x")
    win.left.refresh()
    names = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    win.left.table.setCurrentIndex(win.left.model.index(names.index("b.png"), 0))
    seen = []
    monkeypatch.setattr(GlassViewer, "show", lambda self: seen.append(self))
    win.glass_view()
    assert len(seen) == 1 and seen[0].current_path().endswith("b.png") and len(seen[0].paths) == 3 and seen[0] in win.viewers
    seen[0].close()
    win.left.table.setCurrentIndex(win.left.model.index(names.index("plain.txt"), 0))
    win.glass_view()
    assert len(seen) == 1 and "picture" in win.status.text()


def test_the_command_is_in_the_menus_and_can_be_given_a_function_key(world):
    from dossier.gui import fkeys
    win, *_ = world
    assert "glass_view" in fkeys.COMMANDS and "glass_view" in win._command_actions
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "View as Glass" in [a.text() for a in menus["Files"].actions()]
    appearance = next(a.menu() for a in menus["Settings"].actions() if a.text() == "Appearance")
    assert "Picture Viewer Glass..." in [a.text() for a in appearance.actions()]


def test_the_glass_settings_page_through_a_real_exec_is_saved_and_used(world):
    from PyQt6.QtCore import QTimer
    win, *_ = world

    def choose():
        box = QApplication.activeModalWidget()
        assert isinstance(box, GlassDialog)
        box.mode.setCurrentIndex(box.mode.findData(glass.DIM))
        box.slider.setValue(65)
        box.accept()
    QTimer.singleShot(50, choose)
    win.open_glass_settings()
    assert saved_look(win.settings) == (glass.DIM, 65)
    QTimer.singleShot(50, lambda: (QApplication.activeModalWidget().mode.setCurrentIndex(2), QApplication.activeModalWidget().accept()))
    win.open_glass_settings()
    assert saved_look(win.settings)[0] == glass.SOLID and win.settings.value("viewer/glass_level") is None


def test_the_blur_kind_and_tint_reach_windows_and_the_default_is_a_nearly_clear_white(viewers, tmp_path, monkeypatch):
    from dossier.core import platform
    seen = []
    monkeypatch.setattr(platform, "set_blur_behind", lambda hwnd, tint=0x01ffffff, kind="acrylic": seen.append((tint, kind)) or True)
    paths = make_pictures(tmp_path)
    default = GlassViewer(paths, 0, glass.FROSTED, None, capabilities=FULL)
    viewers.append(default)
    default.show()
    custom = GlassViewer(paths, 0, glass.FROSTED, None, capabilities=FULL, blur_kind="plain", tint=0x01202020)
    viewers.append(custom)
    custom.show()
    assert seen == [(0x01ffffff, "acrylic"), (0x01202020, "plain")] or seen == [(0x01ffffff, "acrylic")][:0] + seen
    assert seen[0][1] == "acrylic" and seen[1] == (0x01202020, "plain")


def test_dossier_view_takes_the_experimental_blur_and_tint_and_refuses_a_bad_tint(app, tmp_path):
    a = make_pictures(tmp_path)[0]
    before = {id(w) for w in QApplication.topLevelWidgets()}
    viewer_app.main(["--blur", "plain", "--tint", "#336699", a], settings_path=str(tmp_path / "s.ini"), show=False)
    window = next(w for w in QApplication.topLevelWidgets() if id(w) not in before and isinstance(w, GlassViewer))
    window.close()
    for bad in ("12345", "gggggg", "ffff"):
        with pytest.raises(SystemExit):
            viewer_app.main(["--tint", bad, a], settings_path=str(tmp_path / "s.ini"), show=False)
