"""Right-click > Earlier Versions... and Tools > Compare > Earlier Versions... in the window (card 67B)."""
import os

import pytest

pytest.importorskip("PyQt6")

from dossier.gui.earlier_versions import EarlierVersionsDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def make(left):
    left.joinpath("a.txt").write_text("now")
    for stamp, text in (("2026.11.16-01.00.00", "old"), ("2026.11.18-01.00.00", "newer")):
        snap = left / "#snapshot" / f"GMT+01-{stamp}"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "a.txt").write_text(text)


def at_file(win, left, name="a.txt"):
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    row = next(r for r in range(win.left.model.rowCount()) if not win.left.model.is_up_row(r) and win.left.model.entry_at(r).name == name)
    win.left.table.setCurrentIndex(win.left.model.index(row, 0))
    win._set_active(win.left)


def test_the_menus_offer_earlier_versions(world):
    win, d, left, right, tmp = world
    make(left)
    at_file(win, left)
    bar = win.bar_command("earlier_versions")
    assert bar.text() == "Earlier Versions..."
    menu = win._item_menu(win.left, win.left.current_entry())
    assert "Earlier Versions..." in [a.text().split(chr(9))[0] for a in menu.actions()]


def test_choosing_a_moment_opens_it_in_the_other_panel_read_only(world, monkeypatch):
    win, d, left, right, tmp = world
    make(left)
    at_file(win, left)
    seen = []

    def pick(self, dlg):
        seen.append(dlg)
        assert isinstance(dlg, EarlierVersionsDialog) and dlg.tree.topLevelItemCount() == 2
        return dlg.moments[0]
    monkeypatch.setattr(type(win), "_ask_earlier_version", pick)
    win.earlier_versions()
    pump(win, lambda: seen)
    pump(win, lambda: "newer" in win.right.path or "#snapshot" in win.right.path)
    assert win.right.path == str(left / "#snapshot" / "GMT+01-2026.11.18-01.00.00")
    pump(win, lambda: win.right.current_name() == "a.txt")
    assert not win.fs.is_writable(win.right.path)                                      # nothing can be changed inside it
    assert (left / "a.txt").read_text() == "now"


def test_a_picker_cancel_changes_nothing(world, monkeypatch):
    win, d, left, right, tmp = world
    make(left)
    at_file(win, left)
    before = win.right.path
    asked = []
    monkeypatch.setattr(type(win), "_ask_earlier_version", lambda self, dlg: asked.append(dlg) or None)
    win.earlier_versions()
    pump(win, lambda: asked)
    assert win.right.path == before


def test_no_snapshots_says_where_it_looked(world):
    win, d, left, right, tmp = world
    left.joinpath("a.txt").write_text("now")
    at_file(win, left)
    win.earlier_versions()
    pump(win, lambda: d.infos)
    title, text = d.infos[-1]
    assert title == "Earlier Versions" and "#snapshot" in text and ".zfs" in text and str(tmp) not in text


def test_a_move_out_of_a_snapshot_is_refused_by_the_plan(world):
    win, d, left, right, tmp = world
    make(left)
    from dossier.core import ops
    snap = left / "#snapshot" / "GMT+01-2026.11.18-01.00.00" / "a.txt"
    plan = ops.plan_move(win.fs, [str(snap)], str(right))
    assert plan.blocking                                                               # a snapshot's files are only copied, never moved
    assert os.path.exists(snap)
