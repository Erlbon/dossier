"""Ctrl+C / Ctrl+X / Ctrl+V on files, through the system clipboard and the real key presses."""
import os
import struct

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QByteArray, QMimeData, Qt, QUrl  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import file_clipboard  # noqa: E402
from tests.helpers import wait_planned  # noqa: E402
from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401

CTRL = Qt.KeyboardModifier.ControlModifier


def pick_first(win, panel_name="left"):
    panel = getattr(win, panel_name)
    panel.refresh()
    panel.table.setCurrentIndex(panel.model.index(1, 0))


def test_ctrl_c_then_ctrl_v_copies_into_the_other_panel(world):
    win, _d, left, right, _t = world
    (left / "a.txt").write_text("A")
    pick_first(win)
    key(win, Qt.Key.Key_C, CTRL)
    assert "Copied 1 item" in win.status.text()
    key(win, Qt.Key.Key_Tab)                                   # the right panel is active now
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: (right / "a.txt").exists())
    assert (left / "a.txt").exists() and (right / "a.txt").read_text() == "A"


def test_ctrl_x_then_ctrl_v_moves_and_empties_the_clipboard(world):
    win, _d, left, right, _t = world
    (left / "a.txt").write_text("A")
    pick_first(win)
    key(win, Qt.Key.Key_X, CTRL)
    key(win, Qt.Key.Key_Tab)
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: (right / "a.txt").exists())
    assert not (left / "a.txt").exists()
    assert file_clipboard.get() == ([], False)                 # nothing left to paste a second time


def test_pasting_into_the_same_folder_keeps_both(world):
    win, dialogs, left, _r, _t = world
    from dossier.core.ops import Resolution
    dialogs.conflict_answer = Resolution.KEEP_BOTH
    (left / "a.txt").write_text("A")
    pick_first(win)
    key(win, Qt.Key.Key_C, CTRL)
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: len(list(left.iterdir())) == 2)
    assert len(list(left.iterdir())) == 2


def test_what_dossier_copies_is_what_explorer_expects(world):
    win, _d, left, _r, _t = world
    (left / "a.txt").write_text("A")
    pick_first(win)
    key(win, Qt.Key.Key_X, CTRL)
    data = QApplication.clipboard().mimeData()
    assert [os.path.normpath(u.toLocalFile()) for u in data.urls()] == [str(left / "a.txt")]
    assert file_clipboard.get() == ([str(left / "a.txt")], True)
    assert struct.unpack("<I", bytes(data.data(file_clipboard.WIN_EFFECT)))[0] == file_clipboard.DROP_MOVE
    assert bytes(data.data(file_clipboard.GNOME)).startswith(b"cut\nfile:///")
    assert bytes(data.data(file_clipboard.KDE_CUT)) == b"1"
    key(win, Qt.Key.Key_C, CTRL)
    data = QApplication.clipboard().mimeData()
    assert struct.unpack("<I", bytes(data.data(file_clipboard.WIN_EFFECT)))[0] == file_clipboard.DROP_COPY
    assert bytes(data.data(file_clipboard.GNOME)).startswith(b"copy\n")
    assert not data.hasFormat(file_clipboard.KDE_CUT)


def explorer_clipboard(paths, effect):
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    if effect is not None:
        data.setData(file_clipboard.WIN_EFFECT, QByteArray(struct.pack("<I", effect)))
    QApplication.clipboard().setMimeData(data)


def test_paste_takes_files_copied_in_explorer(world):
    win, _d, left, right, tmp = world
    (tmp / "outside.txt").write_text("X")
    explorer_clipboard([tmp / "outside.txt"], file_clipboard.DROP_COPY)
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: (left / "outside.txt").exists())
    assert (tmp / "outside.txt").exists()


def test_paste_takes_files_cut_in_explorer_as_a_move(world):
    win, _d, left, _r, tmp = world
    (tmp / "outside.txt").write_text("X")
    explorer_clipboard([tmp / "outside.txt"], file_clipboard.DROP_MOVE)
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: (left / "outside.txt").exists())
    assert not (tmp / "outside.txt").exists()


def test_a_plain_url_list_is_a_copy(world):
    win, _d, left, _r, tmp = world
    (tmp / "outside.txt").write_text("X")
    explorer_clipboard([tmp / "outside.txt"], None)
    key(win, Qt.Key.Key_V, CTRL)
    pump(win, lambda: (left / "outside.txt").exists())
    assert (tmp / "outside.txt").exists()


def test_paste_with_no_files_says_so_and_changes_nothing(world):
    win, dialogs, left, _r, _t = world
    QApplication.clipboard().clear()
    key(win, Qt.Key.Key_V, CTRL)
    assert "no files" in win.status.text()
    assert list(left.iterdir()) == []
    QApplication.clipboard().setText("just words")                 # text is offered as a new file (a name is asked; cancelling makes nothing)
    key(win, Qt.Key.Key_V, CTRL)
    assert list(left.iterdir()) == []


def test_files_that_vanished_are_not_pasted(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("A")
    pick_first(win)
    key(win, Qt.Key.Key_C, CTRL)
    (left / "a.txt").unlink()
    key(win, Qt.Key.Key_Tab)
    key(win, Qt.Key.Key_V, CTRL)
    wait_planned(win)                                           # the sources are looked at while the plan is made
    assert dialogs.infos and "Nothing to do" in dialogs.infos[-1][1] and "no longer there" in dialogs.infos[-1][1]
    assert list(right.iterdir()) == []
