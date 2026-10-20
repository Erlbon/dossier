"""The Search dialog gathers criteria; the command runs the search and opens a result tab."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.search import BadCriteria  # noqa: E402
from dossier.gui.search_dialog import SearchDialog  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_answers_become_criteria_with_units_and_whole_days(app, tmp_path):
    d = SearchDialog(None, str(tmp_path))
    d.name.setText("*.jpg;*.png")
    d.case.setChecked(True)
    d.kinds.setCurrentIndex(d.kinds.findData("both"))
    d.subfolders.setChecked(False)
    d.min_size.number.setText("1,5")
    d.min_size.unit.setCurrentIndex(d.min_size.unit.findText("MB"))
    d.after.on.setChecked(True)
    d.before.on.setChecked(True)
    d.text.setText("hello")
    d.regex.setChecked(True)
    c = d.criteria()
    assert c.root == str(tmp_path) and c.name == "*.jpg;*.png" and c.case_sensitive and c.kinds == "both"
    assert not c.subfolders and c.min_size == int(1.5 * 1024 * 1024) and c.max_size is None
    assert c.older_than - c.newer_than > 86_000                           # a whole day lies between start and end of today
    assert c.text == "hello" and c.text_regex


def test_bad_input_is_refused_with_a_reason_and_the_dialog_stays_open(app, tmp_path):
    d = SearchDialog(None, str(tmp_path))
    d.min_size.number.setText("abc")
    with pytest.raises(BadCriteria):
        d.criteria()
    d._accept()
    assert "is not a size" in d.problem.text() and d.result() == 0
    d.min_size.number.setText("5")
    d.max_size.number.setText("1")
    d._accept()
    assert "smallest size is larger" in d.problem.text()
    d.min_size.number.clear()
    d.max_size.number.clear()
    d.text.setText("(")
    d.regex.setChecked(True)
    d._accept()
    assert d.problem.text().startswith("Cannot search")


def test_the_command_searches_and_opens_the_result_in_a_new_tab(world, monkeypatch):
    win, dialogs, left, *_ = world
    (left / "a.txt").write_text("needle here")
    (left / "b.txt").write_text("nothing")
    (left / "sub").mkdir()
    (left / "sub" / "c.txt").write_text("another needle")
    win.left.refresh()
    tabs_before = win.left.tabs.count()

    def fake(dlg):
        dlg.text.setText("needle")
        dlg.name.setText("*.txt")
        return True

    monkeypatch.setattr(type(win), "_ask_search", lambda self, dlg: fake(dlg))
    win.search_files()
    pump(win, lambda: win.left.tabs.count() > tabs_before)
    pump(win, lambda: win.left.path.startswith("found:") and win.left.model.entry_count() >= 2)
    names = sorted(os.path.basename(win.left.model.entry_at(r).path) for r in range(win.left.model.entry_count())
                   if win.left.model.entry_at(r).name != "..")
    assert names == ["a.txt", "c.txt"]
    assert win._last_search.text == "needle"                                # the next dialog starts from it


def test_cancelling_starts_nothing(world, monkeypatch):
    win, *_ = world
    monkeypatch.setattr(type(win), "_ask_search", lambda self, dlg: False)
    before = win.left.tabs.count()
    win.search_files()
    assert win.left.tabs.count() == before and not win._size_jobs


def test_the_menu_has_search(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert "Search..." in [a.text() for a in menus["Commands"].actions()]
