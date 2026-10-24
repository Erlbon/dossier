"""The first tab's left edge lines up with the box below it, in the active panel (gold frame) and in the other (no frame)."""
import pytest

pytest.importorskip("PyQt6")

from dossier.gui.panel import FRAME  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def edge_of_tab(panel) -> float:
    """Where the first tab's outline begins, in the panel's own coordinates."""
    left = panel.tabs.mapTo(panel, panel.tabs.rect().topLeft()).x()
    return left + panel.tabs.tab_outline(0).left()


def edge_of_box(panel) -> int:
    """Where the address bar (the box under the tabs) begins, in the panel's own coordinates."""
    return panel.bar.mapTo(panel, panel.bar.rect().topLeft()).x()


def test_the_first_tab_lines_up_with_the_box_below_in_both_states(world):
    win, d, left, right, tmp = world
    for panel, other in ((win.left, win.right), (win.right, win.left)):
        panel.set_active(True)
        other.set_active(False)
        for p in (panel, other):
            assert p.tabs.first_inset == (0 if p._active else FRAME)
            assert edge_of_box(p) == FRAME                          # the address bar always starts inside the frame's margin
            visible_edge = 0 if p._active else edge_of_box(p)       # the active panel's gold frame fills that margin; the other has none
            assert edge_of_tab(p) == visible_edge, (p is win.left, p._active)


def test_the_inset_follows_the_active_panel(world):
    win, d, left, right, tmp = world
    win.right.set_active(True)
    win.left.set_active(False)
    assert win.right.tabs.first_inset == 0 and win.left.tabs.first_inset == FRAME
    win.left.set_active(True)
    win.right.set_active(False)
    assert win.left.tabs.first_inset == 0 and win.right.tabs.first_inset == FRAME
    assert win.left.tabs.tab_outline(0).left() - win.right.tabs.tab_outline(0).left() == -FRAME


def test_only_the_first_tab_is_moved(world):
    win, d, left, right, tmp = world
    win.right.new_tab(str(tmp), activate=False)
    win.right.set_active(False)
    gap_before = win.right.tabs.tab_outline(1).left() - win.right.tabs.tabRect(1).left()
    win.right.set_active(True)
    assert win.right.tabs.tab_outline(1).left() - win.right.tabs.tabRect(1).left() == gap_before


# the one line around the current tab and the box below it ----------------------------------------------------------------------------------
def test_the_outline_runs_around_tab_and_box_and_starts_where_the_box_starts(world):
    from PyQt6.QtCore import QPointF
    win, d, left, right, tmp = world
    for panel, other in ((win.left, win.right), (win.right, win.left)):
        panel.set_active(True)
        other.set_active(False)
        for p in (panel, other):
            path = p.outline.path()
            assert path is not None
            inset = 0 if p._active else FRAME
            box = path.boundingRect()
            assert box.left() == inset + 0.5 and box.right() == p.width() - inset - 0.5 and box.bottom() == p.height() - inset - 0.5
            assert box.top() == p.tabs.mapTo(p, p.tabs.rect().topLeft()).y() + p.tabs.tab_outline(0).top() + 0.5
            assert not path.contains(QPointF(box.center().x(), box.bottom() + 5))


def test_the_outline_follows_the_current_tab_and_leaves_the_others_resting_on_the_top_edge(world):
    win, d, left, right, tmp = world
    p = win.left
    p.new_tab(str(tmp))
    p.tabs.setCurrentIndex(0)
    first = p.outline.path()
    p.tabs.setCurrentIndex(1)
    second = p.outline.path()
    assert first != second and first.boundingRect().left() == second.boundingRect().left()      # the box does not move, the tab does
    tab_left = p.tabs.mapTo(p, p.tabs.rect().topLeft()).x() + p.tabs.tab_outline(1).left() + 0.5
    xs = {round(second.elementAt(i).x, 1) for i in range(second.elementCount())}
    assert round(tab_left, 1) in xs                                                           # it goes up at the second tab's own left edge


def test_the_outline_is_darker_in_the_active_panel_and_clicks_pass_through(world):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from dossier.gui import theme
    win, d, left, right, tmp = world
    c = theme.tab_colors()
    assert c["frame_line"] != c["inactive_frame_line"] and QColor(c["frame_line"]).lightness() < QColor(c["active_fill"]).lightness()
    assert win.left.outline.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert win.left.outline.geometry() == win.left.rect()


def test_the_outline_is_drawn_on_the_panel_edge_in_the_right_colour(world):
    from PyQt6.QtGui import QColor
    from dossier.gui import theme
    win, d, left, right, tmp = world
    c = theme.tab_colors()
    win.left.set_active(True)
    win.right.set_active(False)
    img = win.left.grab().toImage()
    y = win.left.body.y() + 60
    assert img.pixelColor(0, y).name() == QColor(c["frame_line"]).name()                       # the active panel: on its very edge
    img = win.right.grab().toImage()
    assert img.pixelColor(FRAME, win.right.body.y() + 60).name() == QColor(c["inactive_frame_line"]).name()   # the other: where its box starts
