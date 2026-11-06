"""SVG in F3 and the thumbnails (decided 2026-11-06): F3 shows an SVG as a picture, drawn from the vector so it stays sharp at any zoom,
with its text a "View as" away; it is one of the pictures the wheel steps through; and a small SVG (an icon) fills its thumbnail."""
import os

import pytest

from dossier.core import viewmodes

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="16" viewBox="0 0 24 16"><rect width="24" height="16" fill="#c22"/></svg>'


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_an_svg_opens_as_a_picture_and_its_text_is_one_choice_away(tmp_path):
    svg = write(tmp_path, "icon.svg", '<?xml version="1.0"?>' + chr(10) + "<!-- made by hand -->" + chr(10) + ICON)
    assert viewmodes.mode_for(svg) == "image" and viewmodes.modes_for(svg) == ["image", "text", "hex"]
    assert viewmodes.mode_for(write(tmp_path, "notes.svg", "not a drawing at all")) == "text"        # the content decides
    assert viewmodes.mode_for(write(tmp_path, "drawing.xml", ICON)) == "text"                        # and so does the name
    assert viewmodes.image_siblings(["b.png", "a.svg", "c.svgz", "d.txt"]) == ["a.svg", "b.png", "c.svgz"]


def test_the_svg_is_drawn_from_the_vector_and_fit_may_enlarge_it(app, tmp_path):
    from PyQt6.QtSvgWidgets import QGraphicsSvgItem
    from dossier.gui.image_view import ImageView, read_image
    path = write(tmp_path, "icon.svg", ICON)
    view = ImageView()
    view.resize(480, 320)
    view.show()
    view.set_image(read_image(path), path)
    assert isinstance(view._item, QGraphicsSvgItem) and view.image_size() == (24, 16)
    view.fit()
    assert view.zoom > 5                                                     # a 24 px icon fills the window, sharp
    view.turn(1)
    rect = view._scene.sceneRect()
    assert round(rect.width()) == 16 and round(rect.height()) == 24          # turned a quarter
    view.close()


def test_a_photo_is_still_never_enlarged_by_fit(app, tmp_path):
    from PyQt6.QtGui import QColor, QImage
    from dossier.gui.image_view import ImageView
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("#2c2"))
    path = str(tmp_path / "small.png")
    image.save(path)
    view = ImageView()
    view.resize(480, 320)
    view.show()
    view.set_image(image, path)
    view.fit()
    assert view.zoom == pytest.approx(1.0)
    view.close()


def test_a_small_svg_fills_its_thumbnail(app, tmp_path):
    from dossier.core import covers
    from dossier.gui import thumbnails
    path = write(tmp_path, "icon.svg", ICON)
    image = thumbnails.make(covers.kind_of("icon.svg", False), path, 128)
    assert image is not None and (image.width(), image.height()) == (128, 85)
    assert covers.kind_of("icon.svgz", False) == "image"
