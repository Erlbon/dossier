"""The program icon: the master SVG, the generated .ico and PNG, and its use by the windows."""
import os
import struct

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import appicon  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def colours(image, step=1):
    seen = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            seen.add(image.pixelColor(x, y).name())
    return seen


def test_the_svg_renders_sharp_at_every_size_and_is_gold_on_a_dark_tile(app):
    for size in appicon.SIZES:
        img = appicon.render(size)
        assert img.width() == size and img.height() == size
        assert img.pixelColor(int(size * 0.21), int(size * 0.55)).name() == QColor("#d4a94f").name()   # the folder
    big = appicon.render(256)
    assert "#d4a94f" in colours(big, 4) and "#14171f" in colours(big, 4)       # the gold folder, the dark tile
    assert big.pixelColor(0, 0).alpha() == 0                                    # the corners are transparent


def test_the_d_is_cut_out_of_the_folder_in_the_tile_colour(app):
    img = appicon.render(256)
    d_stem = img.pixelColor(int(256 * 0.375), int(256 * 0.60))                  # on the vertical bar of the D
    assert d_stem.name() == "#14171f"


def test_the_ico_holds_seven_png_images_of_the_right_sizes(app):
    data = open(appicon.ICO, "rb").read()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(appicon.SIZES))
    for i, size in enumerate(appicon.SIZES):
        w, h, _c, _r, planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        assert (w or 256, h or 256) == (size, size) and planes == 1 and bits == 32
        png = data[offset:offset + length]
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        img = QImage.fromData(png)
        assert img.width() == size and img.height() == size


def test_the_generated_files_match_the_master(app, tmp_path):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import make_icons
    make_icons.write_ico(str(tmp_path / "fresh.ico"), appicon.SIZES)
    # Compared as pictures, not bytes: another system may compress the same picture differently. If this fails,
    # the SVG changed: run tools/make_icons.py and commit the new files.
    committed = open(appicon.ICO, "rb").read()
    offset = struct.unpack("<II", committed[6 + 16 * (len(appicon.SIZES) - 1) + 8:6 + 16 * len(appicon.SIZES)])[1]
    shipped = QImage.fromData(committed[offset:])
    fresh = appicon.render(256)
    assert shipped.size() == fresh.size()
    total = sum(abs(shipped.pixelColor(x, y).red() - fresh.pixelColor(x, y).red())
                + abs(shipped.pixelColor(x, y).alpha() - fresh.pixelColor(x, y).alpha())
                for x in range(0, 256, 4) for y in range(0, 256, 4))
    assert total / (64 * 64) < 3
    assert QImage(appicon.PNG).width() == 256


def test_the_icon_object_has_every_size(app):
    icon = appicon.app_icon()
    assert not icon.isNull() and {s.width() for s in icon.availableSizes()} >= {16, 32, 256}


def test_every_window_carries_the_icon(app, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)),
                     dialogs=FakeDialogs())
    try:
        assert not win.windowIcon().isNull() and not QApplication.windowIcon().isNull()
    finally:
        win.close()


def test_the_taskbar_id_call_is_harmless_everywhere():
    from dossier.core.platform import set_app_id
    set_app_id("Erlbon.Dossier.Test")
