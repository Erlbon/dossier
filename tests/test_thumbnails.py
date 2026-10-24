"""The thumbnail view: pictures made on the side, one list shown two ways, and the choices that go with it."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QIcon, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import thumbnails as th  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def save_png(path, w=300, h=200, color="#3366cc"):
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))
    return path


def wait_until(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


# the maker --------------------------------------------------------------------------------------------------------------
def test_an_image_file_is_scaled_to_fit_without_changing_its_shape(tmp_path):
    big = save_png(tmp_path / "big.png", 800, 400)
    image = th.make("image", str(big), 128)
    assert image.width() == 128 and image.height() == 64
    small = save_png(tmp_path / "small.png", 40, 30)
    assert th.make("image", str(small), 128).width() == 40                 # never enlarged
    assert th.make("image", str(tmp_path / "missing.png"), 128) is None


def test_a_damaged_picture_or_a_text_file_gives_no_thumbnail(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert th.make("image", str(bad), 128) is None
    assert th.make("", str(bad), 128) is None


def test_the_sizes_step_up_and_down_and_stop_at_the_ends():
    assert th.step_by(128, 1) == 192 and th.step_by(128, -1) == 96
    assert th.step_by(256, 1) == 256 and th.step_by(64, -1) == 64
    assert th.nearest_step(100) == 96 and th.nearest_step(999) == 256


# the loader -------------------------------------------------------------------------------------------------------------
def test_a_thumbnail_is_asked_for_made_on_the_side_and_then_known(app, tmp_path):
    png = save_png(tmp_path / "a.png")
    loader = th.Thumbnails()
    seen = []
    loader.ready.connect(seen.append)
    key = loader.key(str(png), 1.0, 10, 128)
    assert loader.get(key) == (False, None)
    loader.request(key, "image", str(png), 128)
    loader.request(key, "image", str(png), 128)                            # asking again while it is being made does nothing
    wait_until(lambda: seen)
    known, pixmap = loader.get(key)
    assert known and pixmap is not None and pixmap.width() == 128 and seen == [str(png)]
    loader.shutdown()


def test_an_item_without_a_picture_is_remembered_as_having_none(app, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"x")
    loader = th.Thumbnails()
    key = loader.key(str(bad), 1.0, 1, 128)
    loader.request(key, "image", str(bad), 128)
    wait_until(lambda: loader.get(key)[0])
    assert loader.get(key) == (True, None)
    loader.shutdown()


def test_network_drives_and_video_are_off_until_allowed(app):
    loader = th.Thumbnails()
    assert loader.wanted("image", False) and not loader.wanted("image", True) and not loader.wanted("", False)
    loader.on_network = True
    assert loader.wanted("image", True)
    assert not loader.wanted("video", False)
    loader.video = True
    assert not loader.wanted("video", False)                               # on, but no ffmpeg to do it with
    loader.ffmpeg = "ffmpeg"
    assert loader.wanted("video", False)


def test_the_memory_keeps_only_so_many_pictures(app, monkeypatch):
    loader = th.Thumbnails()
    monkeypatch.setattr(th, "CACHE_ITEMS", 5)
    for i in range(12):
        loader._pending[f"k{i}"] = f"p{i}"
        loader._finished(f"k{i}", None)
    assert len(loader._cache) == 5 and loader.get("k11") == (True, None) and loader.get("k0") == (False, None)


def test_the_memory_is_also_limited_in_bytes_not_only_in_pictures(app, monkeypatch):
    from PyQt6.QtGui import QImage
    loader = th.Thumbnails()
    loader.ratio = 1.0
    monkeypatch.setattr(th, "CACHE_BYTES", 3 * 100 * 100 * 4 + 10)                     # room for three 100 x 100 pictures
    for i in range(8):
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(0)
        loader._pending[f"k{i}"] = f"p{i}"
        loader._finished(f"k{i}", image)
    assert len(loader._cache) == 3 and loader._bytes == 3 * 100 * 100 * 4
    assert loader.get("k7")[0] and not loader.get("k0")[0]                              # the newest stay, the oldest went
    loader._finished("k7", None)                                                        # a replaced picture no longer counts
    assert loader._bytes == 2 * 100 * 100 * 4
    loader.clear()
    assert loader._bytes == 0 and len(loader._cache) == 0
    big = QImage(4000, 4000, QImage.Format.Format_ARGB32)                               # one picture over the limit is still kept (the newest)
    big.fill(0)
    loader._pending["big"] = "p"
    loader._finished("big", big)
    assert len(loader._cache) == 1


# the panel, the model and the window ---------------------------------------------------------------------------------------
def images_in(left, names=("a.png", "b.png", "c.txt")):
    for n in names:
        if n.endswith(".png"):
            save_png(left / n)
        else:
            (left / n).write_text(n)


def test_a_panel_starts_in_details_and_shows_thumbnails_when_asked(world):
    win, d, left, *_ = world
    assert win.left.view_mode == "details" and win.left.view is win.left.table and win.left.model.icon_px == 0
    win.left.set_view_mode("icons", 128)
    assert win.left.view is win.left.icons and win.left.model.icon_px == 128
    win.left.set_view_mode("details")
    assert win.left.view is win.left.table and win.left.model.icon_px == 0


def test_the_thumbnails_of_a_folder_fill_in_as_they_are_made(world):
    win, d, left, *_ = world
    images_in(left)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.left.set_view_mode("icons", 96)
    m = win.left.model
    row = m.row_of("a.png")
    wait_until(lambda: win.thumbs.get(win.thumbs.key(str(left / "a.png"), m.entry_at(row).mtime, m.entry_at(row).size, 96))[0])
    icon = m.index(row, 0).data(Qt.ItemDataRole.DecorationRole)
    pm = icon.pixmap(QSize(96, 96))
    assert isinstance(icon, QIcon) and not pm.isNull()
    txt = m.index(m.row_of("c.txt"), 0).data(Qt.ItemDataRole.DecorationRole)
    assert isinstance(txt, QIcon)                                          # a text file keeps its type icon


def test_one_cursor_and_one_set_of_marks_for_both_views(world):
    win, d, left, *_ = world
    images_in(left)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("b.png"), 0))
    win.left.set_view_mode("icons", 96)
    assert win.left.icons.currentIndex().row() == win.left.model.row_of("b.png")
    win.selection.add([str(left / "a.png")])
    assert [os.path.basename(p) for p in win.left.marked_here()] == ["a.png"]
    assert win.left.current_name() == "b.png"


def test_keys_and_clicks_work_in_the_thumbnail_view_like_in_the_table(world):
    win, d, left, *_ = world
    images_in(left, ("a.png", "b.png"))
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.left.set_view_mode("icons", 96)
    icons = win.left.icons
    icons.setCurrentIndex(win.left.model.index(win.left.model.row_of("box"), 0))
    icons.setFocus()
    QTest.keyClick(icons, Qt.Key.Key_Return)
    pump(win, lambda: win.left.path.endswith("box"))
    QTest.keyClick(icons, Qt.Key.Key_Backspace)
    pump(win, lambda: win.left.path == str(left))
    icons.setCurrentIndex(win.left.model.index(win.left.model.row_of("a.png"), 0))
    QTest.keyClick(icons, Qt.Key.Key_Space)
    assert [os.path.basename(p) for p in win.left.marked_here()] == ["a.png"]


def test_the_home_page_always_shows_details_and_the_choice_comes_back(world):
    win, d, left, *_ = world
    win.left.set_view_mode("icons", 128)
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    assert win.left.view is win.left.table and win.left.model.icon_px == 0
    win.left.set_folder(str(left))
    pump(win, lambda: not win.left.is_home)
    assert win.left.view is win.left.icons and win.left.model.icon_px == 128


def test_the_folder_note_is_left_out_of_the_thumbnail_view(world):
    win, d, left, *_ = world
    (left / "README.md").write_text("# Hello\n\nA note.")
    win.left.refresh()
    pump(win, lambda: win.left.model.note_row >= 0)
    win.left.set_view_mode("icons", 96)
    assert win.left.model.note_row < 0 and win.left.note.isHidden()
    win.left.set_view_mode("details")
    pump(win, lambda: win.left.model.note_row >= 0)


def test_ctrl_wheel_in_the_thumbnail_view_changes_the_size_and_stops_at_the_ends(world):
    win, *_ = world
    win.left.set_view_mode("icons", 128)
    win.left.icons.zoom.emit(1)
    assert win.left.icon_px == 192
    for _ in range(5):
        win.left.icons.zoom.emit(1)
    assert win.left.icon_px == 256
    for _ in range(9):
        win.left.icons.zoom.emit(-1)
    assert win.left.icon_px == 64


def test_the_choice_is_per_panel_and_remembered(world):
    win, d, left, right, tmp = world
    win.left.set_view_mode("icons", 192)
    assert str(win.settings.value("view/mode_left")) == "icons" and int(win.settings.value("view/size_left")) == 192
    assert win.right.view_mode == "details" and str(win.settings.value("view/mode_right")) == "details"
    from dossier.gui.main_window import MainWindow
    again = MainWindow(settings_path=str(tmp / "s.ini"), start=(str(left), str(right)), dialogs=d)
    try:
        assert again.left.view_mode == "icons" and again.left.icon_px == 192 and again.right.view_mode == "details"
    finally:
        again.close()


def test_the_view_menu_changes_the_mode_of_the_active_panel_and_shows_the_current_one(world):
    win, *_ = world
    win.view_mode_actions["icons"].trigger()
    assert win.left.view_mode == "icons" and win.view_mode_actions["icons"].isChecked()
    win.size_actions[192].trigger()
    assert win.left.icon_px == 192 and win.size_actions[192].isChecked()
    win._set_active(win.right)
    win.sync_mode_actions()
    assert win.view_mode_actions["details"].isChecked() and not win.view_mode_actions["icons"].isChecked()
    win.view_mode_actions["details"].trigger()
    assert win.right.view_mode == "details"


def test_arrange_by_sorts_the_list_in_either_view(world):
    win, d, left, *_ = world
    for n, size in (("a.txt", 30), ("b.txt", 10), ("c.txt", 20)):
        (left / n).write_text("x" * size)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    win.left.set_view_mode("icons", 96)
    win.arrange_by("size")
    order = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count()) if win.left.model.entry_at(r).name != ".."]
    assert order == ["b.txt", "c.txt", "a.txt"]
    win.arrange_by(None, True)
    order = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count()) if win.left.model.entry_at(r).name != ".."]
    assert order == ["a.txt", "c.txt", "b.txt"]


def test_the_thumbnail_settings_are_kept_and_the_old_pictures_forgotten(world, monkeypatch):
    win, *_ = world
    win.thumbs._cache["x"] = None

    def fake(self, dlg):
        dlg.network.setChecked(True)
        dlg.video.setChecked(False)
        return True
    monkeypatch.setattr(type(win), "_run_thumb_dialog", fake)
    win.open_thumbnail_settings()
    assert win.thumbs.on_network and str(win.settings.value("thumbs/network")) == "true" and not win.thumbs._cache


def test_a_drop_works_on_the_thumbnail_view_too(world):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QDropEvent
    from dossier.gui import dragdrop
    win, d, left, right, tmp = world
    save_png(left / "a.png")
    (right / "box").mkdir()
    win.right.refresh()
    pump(win, lambda: win.right.model.row_of("box") >= 0)
    win.right.set_view_mode("icons", 96)
    box_center = win.right.icons.visualRect(win.right.model.index(win.right.model.row_of("box"), 0)).center()
    mime = dragdrop.make_mime([str(left / "a.png")], str(id(win.left)))          # the event does not own it: keep it alive
    event = QDropEvent(QPointF(box_center), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.right.icons.dropEvent(event)
    pump(win, lambda: (right / "box" / "a.png").exists() and not win.busy)
