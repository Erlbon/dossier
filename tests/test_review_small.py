"""The small cards of the functionality review of 2026-11-05 (docs/functionality-review-2026-11-05.md): 1, 8, 10, 12, 17-21."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401

from dossier.core import platform  # noqa: E402
from dossier.gui.dialogs import stem_length  # noqa: E402


def listed(win, panel, count):
    panel.refresh()
    pump(win, lambda: panel.model.entry_count() >= count)


def cursor_on(panel, name):
    panel.table.setCurrentIndex(panel.model.index(panel.model.row_of(name), 0))


# 1 -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path, words", [("zip://C:/a.zip!/x.txt", "inside an archive"),
                                         ("sftp://host/etc/x.conf", "on a server")])
def test_f4_says_why_a_file_cannot_be_edited(world, path, words):
    win, dialogs, *_ = world
    win.edit_file(path=path)
    pump(win, lambda: dialogs.infos)
    assert words in dialogs.infos[-1][1]


# 8 -----------------------------------------------------------------------------------------------------------------------------
def test_new_file_opens_in_the_editor(world):
    pytest.importorskip("PyQt6.Qsci")
    win, dialogs, left, *_ = world
    dialogs.texts = ["notes.txt"]
    win.new_file()
    pump(win, lambda: win.editors)
    try:
        assert os.path.normcase(win.editors[0].doc.path) == os.path.normcase(str(left / "notes.txt"))
    finally:
        for w in list(win.editors):
            w.close()


# 10 ----------------------------------------------------------------------------------------------------------------------------
def test_the_rename_box_selects_the_name_without_its_extension():
    assert stem_length("report.pdf") == len("report")
    assert stem_length("archive.tar.gz") == len("archive.tar")
    assert stem_length(".gitignore") == len(".gitignore")
    assert stem_length("my.folder", is_dir=True) == len("my.folder")


def test_f2_asks_with_the_rename_box(world):
    win, dialogs, left, *_ = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "a.txt")
    dialogs.texts = ["b.txt"]
    win.rename()
    pump(win, lambda: (left / "b.txt").exists())
    assert dialogs.names_asked == [("a.txt", False)]


# 12 ----------------------------------------------------------------------------------------------------------------------------
def test_the_panel_says_what_it_holds(world):
    win, _d, left, *_ = world
    (left / "sub").mkdir()
    (left / "a.txt").write_bytes(b"x" * 2048)
    (left / "b.log").write_bytes(b"y" * 1024)
    listed(win, win.left, 4)
    assert win.left.counts.text().startswith("1 folder, 2 files, 3")
    win.left.model.set_filter("*.txt")
    assert win.left.counts.text().endswith("(1 of 3 shown)")


# 17 ----------------------------------------------------------------------------------------------------------------------------
def test_ctrl_j_puts_the_name_and_ctrl_shift_j_the_path_into_the_command_line(world):
    win, _d, left, *_ = world
    (left / "my file.txt").write_text("a")
    listed(win, win.left, 2)
    cursor_on(win.left, "my file.txt")
    win.active.table.setFocus()
    key(win, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
    assert win.cmdline.text() == '"my file.txt" '
    win.cmdline.clear()
    win.active.table.setFocus()
    key(win, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert win.cmdline.text() == f'"{left / "my file.txt"}" '


# 18 ----------------------------------------------------------------------------------------------------------------------------
def test_show_in_explorer_selects_the_item_or_opens_the_folder(world, monkeypatch):
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    listed(win, win.left, 2)
    started = []
    monkeypatch.setattr(win, "_start_file_manager", started.append)
    cursor_on(win.left, "a.txt")
    win.show_in_file_manager()
    win.show_in_file_manager(folder_only=True)
    assert started == [platform.file_manager_command(str(left / "a.txt"), True),
                       platform.file_manager_command(str(left), False)]


def test_the_explorer_command_quotes_the_path_for_select():
    if platform.IS_WINDOWS:
        assert platform.file_manager_command("C:/a b/c.txt", True).endswith(' /select,"C:/a b/c.txt"')


# 19 ----------------------------------------------------------------------------------------------------------------------------
def test_ctrl_backspace_goes_to_the_root_and_stands_on_the_way_back(world):
    win, _d, left, *_ = world
    deep = left / "x" / "y"
    deep.mkdir(parents=True)
    win.left.set_folder(str(deep))
    pump(win, lambda: win.left.path == str(deep))
    win.active.table.setFocus()
    key(win, Qt.Key.Key_Backspace, Qt.KeyboardModifier.ControlModifier)
    root = os.path.splitdrive(str(deep))[0] + os.sep if os.name == "nt" else "/"
    pump(win, lambda: os.path.normcase(win.left.path) == os.path.normcase(root))
    first = str(deep).split(os.sep)[1]
    assert win.left.current_entry().name.lower() == first.lower()


# 20 ----------------------------------------------------------------------------------------------------------------------------
def test_space_on_a_folder_adds_up_its_size(world):
    win, _d, left, *_ = world
    (left / "sub").mkdir()
    (left / "sub" / "a.bin").write_bytes(b"z" * 5000)
    listed(win, win.left, 2)
    cursor_on(win.left, "sub")
    win.active.table.setFocus()
    key(win, Qt.Key.Key_Space)
    pump(win, lambda: win.left.model.has_tree_size(str(left / "sub")))
    assert str(left / "sub") in win.selection


# 21 ----------------------------------------------------------------------------------------------------------------------------
def test_copy_names_and_this_folders_path(world):
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    (left / "b.txt").write_text("b")
    listed(win, win.left, 3)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    win.copy_marked_names()
    assert sorted(QApplication.clipboard().text().splitlines()) == ["a.txt", "b.txt"]
    win.copy_folder_path()
    assert QApplication.clipboard().text() == str(left)
