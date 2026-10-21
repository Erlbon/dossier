"""Things the design review found: the edge of an unchecked box, and a tall row left over from the last folder's note."""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QCheckBox  # noqa: E402

from dossier.core.home import HOME_URL  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_an_unchecked_box_has_a_visible_edge_in_both_schemes(world, scheme):
    win, _d, left, _r, _t = world
    win.theme.set_scheme(scheme)
    box = QCheckBox()
    box.resize(24, 24)
    box.show()
    image = box.grab().toImage()
    background = image.pixelColor(image.width() - 1, image.height() - 1)
    different = [(x, y) for x in range(0, 22) for y in range(2, 22) if image.pixelColor(x, y) != background]
    assert len(different) > 40, "the box cannot be told from the background"
    # an edge, and not only a white fill: some pixel is clearly darker (light) or lighter (dark) than the background
    contrast = max(abs(image.pixelColor(x, y).lightness() - background.lightness()) for x, y in different)
    assert contrast > 60


def test_the_row_that_held_a_note_is_a_normal_row_in_the_next_folder(world):
    win, _d, left, _r, _t = world
    (left / "README.md").write_text("# Heading\n\nSome text of the note.\n")
    for n in range(7):
        (left / f"f{n}.txt").write_text("x")
    win.left.refresh()
    pump(win, lambda: win.left.model.note_row >= 0)
    noted = win.left.model.note_row
    assert win.left.table.rowHeight(noted) > win.left.table.verticalHeader().defaultSectionSize()
    win.left.set_folder(HOME_URL)
    pump(win, lambda: win.left.is_home and win.left.model.entry_count() > 3)
    default = win.left.table.verticalHeader().defaultSectionSize()
    assert [win.left.table.rowHeight(r) for r in range(win.left.model.entry_count())] == [default] * win.left.model.entry_count()
    assert all(win.left.table.rowSpan(r, 0) == 1 for r in range(win.left.model.entry_count()))
