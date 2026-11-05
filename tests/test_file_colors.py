"""Colours of file names by type (comparison review 2026-11-05, card 9, option C): four groups, light and dark, hidden files dimmed,
marked files gold over everything, and the owner's own choice kept."""
import os

import pytest

from dossier.core import filecolors as fc

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_four_groups_with_a_light_and_a_dark_colour():
    colors = fc.FileColors()
    assert [g.key for g in colors.groups] == ["media", "archives", "documents", "programs"]
    assert colors.color_of("IMG_1.JPG", dark=False) == "#0f6e56" and colors.color_of("IMG_1.jpg", dark=True) == "#5dcaa5"
    assert colors.color_of("a.zip", False) == "#993c1d" and colors.color_of("main.py", False) == "#185fa5"
    assert colors.color_of("setup.exe", False) == "#a32d2d" and colors.color_of("README", False) == ""
    assert fc.FileColors(enabled=False).color_of("a.jpg", False) == ""


def test_the_icons_and_the_colours_use_the_same_extensions():
    from dossier.core.filetypes import BY_EXTENSION
    colors = fc.FileColors()
    for ext, icon in BY_EXTENSION.items():
        group = {"photo": "media", "movie": "media", "music": "media", "file-zip": "archives",
                 "file-settings": "programs"}.get(icon, "documents")
        expected = next(g.light for g in colors.groups if g.key == group)
        assert colors.color_of("x." + ext, False) == expected, ext


def test_a_saved_choice_comes_back_and_a_damaged_one_is_the_default():
    mine = fc.FileColors()
    mine.enabled = False
    mine.groups[1].extensions = "zip rar"
    mine.groups[1].light = "#123456"
    back = fc.loads(fc.dumps(mine))
    assert not back.enabled and back.groups[1].extensions == "zip rar" and back.groups[1].light == "#123456"
    assert fc.loads("not json").enabled and fc.loads('{"groups": [{"key": "media", "light": "red"}]}').groups[0].light == "#0f6e56"


def test_the_list_colours_names_dims_hidden_and_keeps_marks_gold(world):
    from dossier.gui.models import marked_color
    win, _d, left, *_ = world
    for name in ("a.jpg", "b.txt", "c.zip"):
        (left / name).write_text("x")
    hidden = left / (".h.txt" if os.name != "nt" else "h.txt")
    hidden.write_text("x")
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 5)
    model = win.left.model

    def colour(name):
        brush = model.data(model.index(model.row_of(name), 0), Qt.ItemDataRole.ForegroundRole)
        return brush.color().name() if brush is not None else ""
    assert colour("a.jpg") in ("#0f6e56", "#5dcaa5") and colour("c.zip") in ("#993c1d", "#f0997b")
    from dossier.gui import theme
    assert colour(hidden.name) == theme.current()["dim"].lower()
    win.selection.add([str(left / "a.jpg")])
    assert colour("a.jpg") == marked_color().name()                 # a mark wins over the type


def test_the_settings_page_changes_and_keeps_the_choice(world):
    from dossier.gui.file_colors import FileColorsDialog
    win, *_ = world

    def answer(dlg):
        dlg.enabled.setChecked(False)
        return True
    win._ask_file_colors = answer
    win.open_file_colors()
    assert not win.left.model.file_colors.enabled and not win.file_colors().enabled
    dlg = FileColorsDialog(win, win.file_colors())
    dlg.reset()
    assert dlg.value().enabled and dlg.value().groups[0].light == "#0f6e56"
    dlg.close()
