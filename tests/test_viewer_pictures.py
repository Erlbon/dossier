"""The picture viewers after the comparison with Picasa and its kind (the owner's answers of 2026-11-20): Delete to the Recycle Bin (88A),
a turn kept in a JPEG (89A), the facts card (90A), reading ahead (92A), zoom that glides (93A), moving GIF and WebP (94A), Open With
and E (95B). The EXIF writing is tested without Qt first, then checked against Qt's own reading of every orientation."""
import os
import struct
import time

import pytest

from dossier.core import exif as ex
from tests.test_viewmodes import tiff

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QImageReader, QPainter, QTransform  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu  # noqa: E402

from dossier.core import glass  # noqa: E402
from dossier.core.trash import TITLE as TRASH_TITLE  # noqa: E402
from dossier.gui import picture_tools  # noqa: E402
from dossier.gui.glass_viewer import GlassViewer  # noqa: E402
from dossier.gui.picture_tools import Picture, ReadAhead  # noqa: E402
from dossier.gui.viewer import TextViewerWindow  # noqa: E402
from tests.helpers import wait_for  # noqa: E402
from tests.test_glass_viewer import FULL, make_pictures  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_viewer_modes import photo_with_exif  # noqa: E402


# the EXIF Orientation, written (89A) --------------------------------------------------------------------------------------------------
def jpeg_bytes(w=64, h=32) -> bytes:
    """A JPEG as Qt writes it (with a JFIF header and no EXIF): red top left, blue bottom right, so every turn looks different."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.fillRect(0, 0, 16, 16, QColor("red"))
    p.fillRect(w - 16, h - 16, 16, 16, QColor("blue"))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "JPG", 95)
    return bytes(buf.data())


def qt_reads(data: bytes) -> QImage:
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    return reader.read()


def corners(img: QImage) -> tuple:
    w, h = img.width(), img.height()
    return (w, h) + tuple(QColor(img.pixel(x, y)).name()[1] + QColor(img.pixel(x, y)).name()[5]
                          for x, y in ((3, 3), (w - 4, 3), (3, h - 4), (w - 4, h - 4)))


def test_the_turns_compose_as_quarter_turns_and_a_mirrored_photo_stays_mirrored():
    assert [ex.turned(1, 1), ex.turned(6, 1), ex.turned(3, 1), ex.turned(8, 1)] == [6, 3, 8, 1]
    assert ex.turned(1, -1) == 8 and ex.turned(6, 2) == 8 and ex.turned(5, 4) == 5
    assert all(ex.turned(o, q) in (2, 4, 5, 7) for o in (2, 4, 5, 7) for q in (1, 2, 3))


@pytest.mark.parametrize("start", range(1, 9))
def test_qt_shows_the_written_orientation_as_the_turn_asked_for(app, start):
    """For every orientation a photo can have, a turn written to its EXIF is what Qt (the viewer) then shows: the picture as it was,
    turned a quarter, a half or back a quarter."""
    data = ex.with_orientation(jpeg_bytes(), start)
    shown = qt_reads(data)
    for quarters in (1, 2, 3, -1):
        written = ex.with_orientation(data, ex.turned(start, quarters))
        assert corners(qt_reads(written)) == corners(shown.transformed(QTransform().rotate(90 * quarters)))


def test_an_orientation_already_there_is_changed_in_place_and_nothing_else_is(app):
    block = tiff([(0x010F, 2, ["Canon"]), (0x0110, 2, ["EOS R6"]), (0x0112, 3, [1])], [(0x829A, 5, [(1, 250)])])
    plain = jpeg_bytes()
    payload = b"Exif\x00\x00" + block
    data = plain[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + plain[2:]
    new = ex.with_orientation(data, 6)
    assert len(new) == len(data) and sum(a != b for a, b in zip(data, new)) == 1         # one byte of the value
    e = ex.parse(ex.find_block(new))
    assert e.orientation == 6 and e.get("Camera") == "Canon EOS R6" and e.get("Exposure time") == "1/250 s"


def test_exif_without_an_orientation_gets_one_and_keeps_every_other_field(app):
    block = tiff([(0x010F, 2, ["Canon"]), (0x0110, 2, ["EOS R6"])], [(0x829A, 5, [(1, 250)]), (0x8827, 3, [400])])
    plain = jpeg_bytes()
    payload = b"Exif\x00\x00" + block
    data = plain[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + plain[2:]
    assert ex.parse(ex.find_block(data)).get("Orientation") == ""
    new = ex.with_orientation(data, 8)
    e = ex.parse(ex.find_block(new))
    assert e.orientation == 8 and e.get("Camera") == "Canon EOS R6" and e.get("ISO") == "400" and e.get("Exposure time") == "1/250 s"
    assert new.endswith(plain[2:])                                                           # the picture data itself untouched
    assert qt_reads(new).width() == 32                                                       # and Qt turns it


def test_a_jpeg_without_exif_gets_a_small_block_after_its_jfif_header(app):
    plain = jpeg_bytes()
    assert plain[2:4] == b"\xff\xe0" and ex.find_block(plain) == b""
    new = ex.with_orientation(plain, 6)
    jfif_end = 4 + struct.unpack(">H", plain[4:6])[0]
    assert new[:jfif_end] == plain[:jfif_end] and new[jfif_end:jfif_end + 2] == b"\xff\xe1"   # JFIF stays first
    assert ex.parse(ex.find_block(new)).orientation == 6 and new.endswith(plain[jfif_end:])
    assert corners(qt_reads(new)) == corners(qt_reads(plain).transformed(QTransform().rotate(90)))


def test_writing_keeps_the_files_date_and_only_a_jpeg_is_written(app, tmp_path):
    path = tmp_path / "p.jpg"
    path.write_bytes(jpeg_bytes())
    os.utime(path, (1_600_000_000, 1_600_000_000))
    ex.write_orientation(str(path), 6)                                                       # grows: a block is added
    assert os.path.getmtime(path) == 1_600_000_000 and ex.read_exif(str(path)).orientation == 6
    ex.write_orientation(str(path), 3)                                                       # the same size: patched in place
    assert os.path.getmtime(path) == 1_600_000_000 and ex.read_exif(str(path)).orientation == 3
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    png = tmp_path / "p.png"
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(png))
    with pytest.raises(ex.NotWritable):
        ex.write_orientation(str(png), 6)


# the facts card's lines (90A) -------------------------------------------------------------------------------------------------------
def test_the_facts_are_the_few_lines_people_look_for_and_never_a_rating():
    e = ex.parse(tiff([(0x010F, 2, ["Canon"]), (0x0110, 2, ["Canon EOS R6"])],
                      [(0x829A, 5, [(1, 250)]), (0x829D, 5, [(8, 1)]), (0x8827, 3, [200]), (0x9003, 2, ["2026:06:12 14:02:33"]),
                       (0xA434, 2, ["RF24-105mm F4 L IS USM"])]))
    lines = ex.photo_facts("IMG_4412.jpg", 4032, 3024, "3.1 MB", e)
    assert lines == ["IMG_4412.jpg", "4032 x 3024 · 3.1 MB", "12 Jun 2026 14:02", "Canon EOS R6 · RF24-105mm F4 L IS USM",
                     "1/250 s · f/8 · ISO 200"]
    assert ex.photo_facts("a.png", 40, 30, "1 KB", ex.Exif(error="no EXIF block")) == ["a.png", "40 x 30 · 1 KB"]
    assert ex.camera_name("NIKON CORPORATION", "NIKON D750") == "NIKON D750" and ex.camera_name("Apple", "iPhone 13") == "Apple iPhone 13"
    assert not any("rating" in x.lower() or "★" in x for x in lines)


# the viewers -----------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def viewers(app):
    made = []
    yield made
    for w in made:
        try:
            w.close()
        except RuntimeError:                     # closed by the test already, and deleted
            pass
    QApplication.processEvents()


def glass_viewer(viewers, paths, **kw):
    window = GlassViewer([str(p) for p in paths], 0, glass.SOLID, capabilities=FULL, blur=lambda hwnd: True, **kw)
    viewers.append(window)
    window.show()
    wait_for(lambda: window.view.has_image())
    return window


def f3_viewer(viewers, paths, **services):
    window = TextViewerWindow([str(p) for p in paths], 0)
    if services:
        window.set_picture_services(**services)
    viewers.append(window)
    window.show()
    wait_for(lambda: window.image_page.view.has_image())
    return window


def test_delete_sends_the_picture_to_the_bin_with_no_question_and_shows_the_next(viewers, tmp_path):
    """88A: no question, the caption says where it went, the next picture takes its place; the last one closes the viewer."""
    paths = make_pictures(tmp_path)
    binned, asked = [], []
    window = glass_viewer(viewers, paths, trasher=lambda p: (os.remove(p), binned.append(p)),
                          ask=lambda *a: asked.append(a) or True)
    QTest.keyClick(window.view, Qt.Key.Key_Delete)
    wait_for(lambda: len(window.paths) == 2)
    assert binned == [paths[0]] and not asked and not os.path.exists(paths[0])
    assert window.caption.text() == f"a.png is in the {TRASH_TITLE}"
    wait_for(lambda: window.view._path == paths[1])
    window.step(1)
    QTest.keyClick(window.view, Qt.Key.Key_Delete)                     # the last picture: the one before it is shown
    wait_for(lambda: len(window.paths) == 1)
    assert window.current_path() == paths[1]
    QTest.keyClick(window.view, Qt.Key.Key_Delete)
    wait_for(lambda: not window.isVisible())
    assert binned == paths[:1] + paths[2:] + paths[1:2] and not asked


def test_on_a_drive_with_no_bin_delete_asks_first_and_says_it_is_for_good(viewers, tmp_path, monkeypatch):
    monkeypatch.setattr(picture_tools, "no_recycle_bin", lambda path: True)
    paths = make_pictures(tmp_path)
    answers, binned = [False, True], []
    asked = []
    window = glass_viewer(viewers, paths, trasher=binned.append, ask=lambda title, text, ok: asked.append(text) or answers.pop(0))
    QTest.keyClick(window.view, Qt.Key.Key_Delete)
    QApplication.processEvents()
    assert os.path.exists(paths[0]) and len(window.paths) == 3 and "for good" in asked[0]          # said no: nothing happens
    QTest.keyClick(window.view, Qt.Key.Key_Delete)
    wait_for(lambda: len(window.paths) == 2)
    assert not os.path.exists(paths[0]) and not binned and window.caption.text() == "a.png is deleted for good"


def test_f3_deletes_a_picture_too_and_the_window_behind_reads_the_folder_again(world):
    win, _d, left, _r, tmp = world
    paths = make_pictures(left)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    win.view_file([paths[1]])
    pump(win, lambda: any(isinstance(v, TextViewerWindow) for v in win.viewers))
    viewer = next(v for v in win.viewers if isinstance(v, TextViewerWindow))
    wait_for(lambda: viewer.image_page.view.has_image())
    QTest.keyClick(viewer.image_page.view, Qt.Key.Key_Delete)
    wait_for(lambda: len(viewer.paths) == 2)
    assert not os.path.exists(paths[1]) and any(n.endswith("b.png") for n in os.listdir(tmp / "bin"))
    assert viewer.status.text() == f"b.png is in the {TRASH_TITLE}" and viewer.paths[viewer.index] == paths[2]
    pump(win, lambda: "b.png" not in [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())])
    viewer.close()


def test_turning_a_jpeg_keeps_the_turn_in_the_file_and_its_date(viewers, tmp_path):
    """89A: R in the viewer writes the turn to the EXIF at once; the file keeps its modified date."""
    path = photo_with_exif(tmp_path / "photo.jpg", orientation=1)
    os.utime(path, (1_600_000_000, 1_600_000_000))
    changed = []
    window = glass_viewer(viewers, [path], changed=changed.append)
    QTest.keyClick(window.view, Qt.Key.Key_R)
    wait_for(lambda: ex.read_exif(path).orientation == 6)
    QTest.keyClick(window.view, Qt.Key.Key_R)
    wait_for(lambda: len(changed) == 2)
    assert ex.read_exif(path).orientation == 3 and os.path.getmtime(path) == 1_600_000_000 and changed == [path, path]
    assert "kept" in window.caption.text()
    window.close()
    again = glass_viewer(viewers, [path])
    assert again.view.image_size() == (40, 20) and again.view._turn == 0                   # shown upside down by its EXIF now


def test_turning_another_kind_is_for_looking_only_and_says_so_the_first_time(viewers, tmp_path):
    paths = make_pictures(tmp_path)
    before = open(paths[0], "rb").read()
    window = glass_viewer(viewers, paths)
    QTest.keyClick(window.view, Qt.Key.Key_R)
    wait_for(lambda: "looking only" in window.caption.text())
    assert open(paths[0], "rb").read() == before and window.view.image_size() == (40, 30) and window.view._turn == 1
    window._unsay()
    QTest.keyClick(window.view, Qt.Key.Key_L)
    QTest.qWait(150)
    assert "looking only" not in window.caption.text()                                      # only the first time


def test_i_shows_the_facts_card_which_stays_while_stepping_and_is_remembered(viewers, tmp_path):
    """90A: I and the bar's ⓘ show a glass card at the top right; it follows the steps until I again, and the next viewer opens with
    it. No rating."""
    photo = photo_with_exif(tmp_path / "photo.jpg")
    other = make_pictures(tmp_path, ("z.png",))[0]
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    window = glass_viewer(viewers, [photo, other], settings=settings)
    assert window.facts.isHidden()
    QTest.keyClick(window.view, Qt.Key.Key_I)
    assert not window.facts.isHidden() and window.info_button.isChecked()
    assert window.facts.lines[0] == "photo.jpg" and window.facts.lines[1].startswith("20 x 40 · ")
    assert "Canon EOS R6" in window.facts.lines and "1/250 s · ISO 400" in window.facts.lines
    assert not any("rating" in x.lower() or "★" in x for x in window.facts.lines)
    card = window.facts.geometry()
    assert card.right() > window.width() * 0.8 and card.top() < window.height() * 0.2      # top right
    window.step(1)
    wait_for(lambda: window.facts.lines[:1] == ["z.png"])
    assert not window.facts.isHidden()
    window.close()
    again = glass_viewer(viewers, [photo], settings=settings)
    assert not again.facts.isHidden()
    again.info_button.click()
    assert again.facts.isHidden() and str(settings.value("viewer/facts")) == "false"


def test_the_next_and_previous_pictures_are_read_ahead_so_a_step_shows_one_at_once(viewers, tmp_path):
    """92A: once a picture is shown its neighbours are read; stepping then shows the next without waiting for a thread."""
    paths = make_pictures(tmp_path, ("a.png", "b.png", "c.png", "d.png"))
    reads = []

    def reader(path):
        reads.append(path)
        return picture_tools.read_picture(path)

    window = glass_viewer(viewers, paths, reader=reader)
    wait_for(lambda: paths[1] in window.cache.kept())
    window.step(1)
    assert window.view._path == paths[1]                                                 # no event handled: it was there already
    wait_for(lambda: paths[2] in window.cache.kept())
    window.step(-1)
    assert window.view._path == paths[0] and reads.count(paths[0]) == 1 and reads.count(paths[1]) == 1
    window.floating.slider.dragging = True                                              # not while the slider is dragged
    window.index = 3
    window._read_ahead()
    assert window.cache.idle() and paths[3] not in window.cache.kept()


def test_the_pictures_kept_stay_under_the_budget_the_oldest_going_first(app):
    def pic():
        img = QImage(100, 100, QImage.Format.Format_ARGB32)
        img.fill(0)
        return Picture(img)

    cache = ReadAhead(lambda fn: fn(), budget=90_000)
    for name in "abc":
        cache.put(name, pic())
    assert cache.kept() == ["b", "c"] and cache.used() == 80_000
    cache.get("b")
    cache.put("d", pic())
    assert cache.kept() == ["b", "d"]
    cache.close()


@pytest.mark.glides
def test_zoom_and_fit_glide_and_a_new_picture_does_not(viewers, tmp_path):
    """93A: about a sixth of a second from where it is to where it goes; stepping to another picture is at once."""
    paths = make_pictures(tmp_path)
    window = glass_viewer(viewers, paths)
    view = window.view
    assert view.glide_ms == 160 and view.zoom == 1.0
    start = time.monotonic()
    view.zoom_by(2.0)
    assert view.gliding() and view.zoom < 1.5                                          # not there at once
    seen = []
    wait_for(lambda: seen.append(view.zoom) or not view.gliding(), timeout=3)
    assert time.monotonic() - start >= 0.12 and abs(view.zoom - 2.0) < 1e-6
    assert any(1.05 < z < 1.95 for z in seen)                                           # it went through the zooms in between
    QTest.keyClick(view, Qt.Key.Key_0)
    assert view.gliding()
    wait_for(lambda: not view.gliding(), timeout=3)
    assert abs(view.zoom - 1.0) < 1e-6
    view.zoom_by(2.0)
    window.step(1)
    wait_for(lambda: view._path == paths[1])
    assert not view.gliding() and view.zoom == 1.0


@pytest.mark.glides
def test_the_glide_keeps_the_point_under_the_mouse_where_it_is(viewers, tmp_path):
    """93A: the zoom goes toward the point under the mouse, all the way through the glide, as Qt's own anchor did."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QCursor
    path = tmp_path / "big.png"
    QImage(1800, 1200, QImage.Format.Format_RGB32).save(str(path))
    window = glass_viewer(viewers, [path])
    view = window.view
    spot = QPoint(view.viewport().width() * 2 // 3, view.viewport().height() // 3)
    QCursor.setPos(view.viewport().mapToGlobal(spot))
    if view.viewport().mapFromGlobal(QCursor.pos()) != spot or not view.underMouse():
        pytest.skip("this platform cannot place the mouse")
    view.zoom_by(3.0)                       # first the picture fills the view both ways (a smaller one is held in the middle)
    wait_for(lambda: not view.gliding(), timeout=3)
    under = view.mapToScene(spot)
    view.zoom_by(1.6)
    drift = []
    wait_for(lambda: drift.append((view.mapToScene(spot) - under).manhattanLength()) or not view.gliding(), timeout=3)
    assert len(drift) > 2 and max(drift) < 3                                           # it stayed under the mouse


def test_a_zoomed_picture_on_the_glass_has_no_scroll_bars_but_still_moves(viewers, tmp_path):
    """97A (2026-11-20): the bars broke the glass look. The arrows and the wheel still move a zoomed picture; F3 keeps its bars."""
    path = tmp_path / "big.png"
    QImage(1800, 1200, QImage.Format.Format_RGB32).save(str(path))
    window = glass_viewer(viewers, [path, path])
    view = window.view
    view.zoom_by(4.0)
    QApplication.processEvents()
    bar = view.horizontalScrollBar()
    assert not bar.isVisible() and not view.verticalScrollBar().isVisible() and bar.maximum() > 0
    before = bar.value()
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert bar.value() > before and window.index == 0                                  # it scrolled, it did not step
    f3 = f3_viewer(viewers, [path])
    f3.image_page.view.zoom_by(4.0)
    QApplication.processEvents()
    assert f3.image_page.view.horizontalScrollBar().isVisible()


def animated_gif(path, frames=((255, 0, 0), (0, 0, 255)), size=4, delay=3, loop=True):
    """A small animated GIF, written by hand (Qt writes no GIF): one colour per frame. The LZW codes stay three bits wide by
    clearing the table every two pixels."""
    def lzw(index: int) -> bytes:
        codes = []
        for _ in range(0, size * size, 2):
            codes += [4, index, index]
        codes.append(5)
        bits = n = 0
        out = bytearray()
        for c in codes:
            bits |= c << n
            n += 3
            while n >= 8:
                out.append(bits & 0xFF)
                bits >>= 8
                n -= 8
        if n:
            out.append(bits & 0xFF)
        return bytes([len(out)]) + bytes(out) + b"\x00"

    palette = list(frames) + [(0, 0, 0)] * (4 - len(frames))
    data = b"GIF89a" + struct.pack("<HHBBB", size, size, 0x81, 0, 0) + b"".join(bytes(c) for c in palette)
    if loop:
        data += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for i in range(len(frames)):
        data += b"\x21\xf9\x04\x00" + struct.pack("<H", delay) + b"\x00\x00"
        data += b"\x2c" + struct.pack("<HHHH", 0, 0, size, size) + b"\x00" + b"\x02" + lzw(i)
    path.write_bytes(data + b"\x3b")
    return str(path)


def test_an_animated_gif_plays_round_and_round_and_space_pauses_it(viewers, tmp_path):
    """94A: it moves (also a GIF that says to play once), Space pauses and plays it; past a still picture Space steps on."""
    gif = animated_gif(tmp_path / "a.gif", loop=False)
    still = make_pictures(tmp_path, ("b.png",))[0]
    window = glass_viewer(viewers, [gif, still])
    view = window.view
    assert view.is_animated()
    colours = set()
    wait_for(lambda: colours.add(QColor(view.shown_image().pixel(1, 1)).name()) or len(colours) == 2, timeout=3)
    frames = []
    wait_for(lambda: frames.append(view.frame_number()) or frames[-1] < max(frames), timeout=3)   # it went round again
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert view.is_paused() and window.index == 0
    paused_at = view.frame_number()
    QTest.qWait(120)
    assert view.frame_number() == paused_at
    view.zoom_by(2.0)
    assert view.zoom == 2.0                                                              # zoom works on it
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert not view.is_paused() and window.index == 0
    window.step(1)
    wait_for(lambda: view._path == still)
    assert not view.is_animated()
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert window.index == 1                                                             # the end: Space steps (and stays)


def test_an_animated_webp_plays_in_f3_too(viewers, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "m.webp"
    first, second = Image.new("RGB", (8, 8), (255, 0, 0)), Image.new("RGB", (8, 8), (0, 0, 255))
    first.save(path, save_all=True, append_images=[second], duration=40, loop=0)
    window = f3_viewer(viewers, [path])
    view = window.image_page.view
    assert view.is_animated()
    colours = set()
    wait_for(lambda: colours.add(QColor(view.shown_image().pixel(1, 1)).red() > 128) or len(colours) == 2, timeout=3)
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert view.is_paused()


def test_the_gear_has_open_with_and_e_opens_the_picture_in_the_program_set(viewers, tmp_path):
    """95B: Open With lists what the window behind gives for this file and starts it on the picture; the viewer stays. E uses the
    program set once in Settings, and says where to set it when none is."""
    paths = make_pictures(tmp_path)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    opened, started = [], []

    def open_with(menu, path):
        menu.addAction("Paint").triggered.connect(lambda: opened.append(path))

    window = glass_viewer(viewers, paths, settings=settings, open_with=open_with, launcher=lambda prog, path: started.append((prog, path)))
    QTest.keyClick(window.view, Qt.Key.Key_E)
    assert not started and "Edit Pictures With" in window.caption.text()
    menu = QMenu()
    window.add_picture_menu(menu)
    sub = next(a.menu() for a in menu.actions() if a.text() == "Open With")
    next(a for a in sub.actions() if a.text() == "Paint").trigger()
    assert opened == [paths[0]] and window.isVisible()
    settings.setValue(picture_tools.EDITOR_KEY, r"C:\Programs\Paint.exe")
    QTest.keyClick(window.view, Qt.Key.Key_E)
    assert started == [(r"C:\Programs\Paint.exe", paths[0])] and window.isVisible()
    menu = QMenu()
    window.add_picture_menu(menu)
    assert any(a.text().startswith("Edit in Paint") for a in menu.actions())
    assert window.buttons["settings"].isVisibleTo(window.bar) and window.buttons["info"].isVisibleTo(window.bar)


def test_from_the_window_open_with_has_the_panels_programs_and_e_its_setting(world, monkeypatch):
    from dossier.core import tools
    win, d, left, _r, tmp = world
    paths = make_pictures(left)
    win.set_tools([tools.Tool("Paint", r"C:\paint.exe", "{files}")])
    started = []
    win.tool_starter = lambda command, argv, cwd: started.append((command, argv))
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    names = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    win.left.table.setCurrentIndex(win.left.model.index(names.index("b.png"), 0))
    seen = []
    monkeypatch.setattr(GlassViewer, "show", lambda self: seen.append(self))
    win.glass_view()
    viewer = seen[0]
    menu = QMenu()
    viewer.add_picture_menu(menu)
    sub = next(a.menu() for a in menu.actions() if a.text() == "Open With")
    next(a for a in sub.actions() if a.text() == "Paint").trigger()
    assert started == [(r"C:\paint.exe", [paths[1]])]
    d.program_answer = r"C:\Tools\GIMP.exe"
    assert win.act_picture_editor.text() == "Edit Pictures With..."
    win.act_picture_editor.trigger()
    assert win.act_picture_editor.text() == "Edit Pictures With GIMP (Change...)"
    viewer.edit_picture()
    assert started[-1] == (r"C:\Tools\GIMP.exe", [paths[1]])
    viewer.close()
