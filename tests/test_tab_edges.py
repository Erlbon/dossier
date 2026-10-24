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
