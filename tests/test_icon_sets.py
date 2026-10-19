"""Swappable icon sets: manifest, mapping, fallback, user sets, the View menu."""
import json
import os
import shutil

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import icon_set  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402,F401
from tests.test_icons import dominant_color  # noqa: E402,F401
from dossier.gui.main_window import MainWindow  # noqa: E402

SQUARE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">'
          '<rect x="2" y="2" width="20" height="20"/></svg>')


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def user_sets(tmp_path):
    icon_set.set_user_dir(str(tmp_path))
    icon_set.use("tabler")
    yield tmp_path
    icon_set.set_user_dir(None)
    icon_set.use("tabler")


def make_set(root, folder, manifest, files):
    d = root / folder
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def test_tabler_is_built_in_and_the_default(app, user_sets):
    ids = [s.id for s in icon_set.available_sets()]
    assert ids[0] == "tabler" and icon_set.active() == "tabler"
    assert icon_set.resolve("folder").endswith(os.path.join("tabler", "folder.svg"))


def test_a_user_set_is_found_selected_and_used_with_its_mapping(app, user_sets):
    make_set(user_sets, "square", {"title": "Squares", "map": {"music": "note.svg"}},
             {"folder.svg": SQUARE, "note.svg": SQUARE})
    assert "square" in [s.id for s in icon_set.available_sets()]
    assert icon_set.use("square")
    assert icon_set.resolve("folder").endswith(os.path.join("square", "folder.svg"))
    assert icon_set.resolve("music").endswith(os.path.join("square", "note.svg"))      # mapped name
    icon_set.clear_cache()
    c = dominant_color(icon_set.icon("folder", "#445566"))
    assert (c.red(), c.green(), c.blue()) == (0x44, 0x55, 0x66)


def test_an_icon_the_set_lacks_falls_back_to_tabler(app, user_sets):
    make_set(user_sets, "tiny", {"title": "Tiny"}, {"folder.svg": SQUARE})
    icon_set.use("tiny")
    assert icon_set.resolve("trash").endswith(os.path.join("tabler", "trash.svg"))
    assert not icon_set.icon("trash", "#000000").isNull()
    assert icon_set.resolve("no-such-icon") == ""


def test_broken_or_hostile_sets_are_ignored_or_contained(app, user_sets):
    (user_sets / "nomanifest").mkdir()
    (user_sets / "nomanifest" / "folder.svg").write_text(SQUARE)
    bad = user_sets / "badjson"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json")
    make_set(user_sets, "escape", {"title": "X", "map": {"folder": "../../tabler/trash.svg", "file": "a/b.svg",
                                                         "music": "note.png"}}, {})
    ids = [s.id for s in icon_set.available_sets()]
    assert "nomanifest" not in ids and "badjson" not in ids and "escape" in ids
    assert icon_set.available_sets()[ids.index("escape")].mapping == {}      # path-like values dropped


def test_a_user_set_cannot_replace_a_built_in_one(app, user_sets):
    make_set(user_sets, "tabler", {"title": "Fake Tabler"}, {"folder.svg": SQUARE})
    sets = [s for s in icon_set.available_sets() if s.id == "tabler"]
    assert len(sets) == 1 and sets[0].builtin and sets[0].title == "Tabler"


def test_unknown_set_changes_nothing(app, user_sets):
    assert icon_set.use("nope") is False and icon_set.active() == "tabler"


def test_the_view_menu_lists_sets_switches_repaints_and_remembers(app, tmp_path):
    (tmp_path / "icon-sets").mkdir()
    make_set(tmp_path / "icon-sets", "square", {"title": "Squares"}, {"pencil.svg": SQUARE})
    start = tmp_path / "start"
    start.mkdir()
    ini = str(tmp_path / "s.ini")
    win = MainWindow(settings_path=ini, start=(str(start), str(start)), dialogs=FakeDialogs())
    win.show()
    try:
        assert set(win.icon_set_actions) == {"tabler", "square"} and win.icon_set_actions["tabler"].isChecked()
        win.icon_set_actions["square"].trigger()
        assert icon_set.active() == "square" and win.icon_set_actions["square"].isChecked()
        c = dominant_color(win._fkey_buttons[0].icon())                  # F2 Rename icon is "pencil"
        assert QColor(c.rgb()) == QColor(win._fkey_buttons[0].icon().pixmap(24, 24).toImage().pixelColor(12, 12))
    finally:
        win.close()
    again = MainWindow(settings_path=ini, start=(str(start), str(start)), dialogs=FakeDialogs())
    try:
        assert icon_set.active() == "square" and again.icon_set_actions["square"].isChecked()
    finally:
        again.close()
        icon_set.set_user_dir(None)
        icon_set.use("tabler")
