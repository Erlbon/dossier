"""Functionality review 2026-11-05, card 26: Go > Folder Tree... (Alt+F10), the popup only: the drive's folders as a tree, opened down to
the folder the panel shows; Enter goes there and the popup closes."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_tree_opens_at_the_panels_folder_and_enter_goes_there(world):
    from dossier.gui.folder_tree import FolderTreePopup
    win, _d, left, *_ = world
    (left / "sub" / "deeper").mkdir(parents=True)
    popup = FolderTreePopup(win, str(left))
    target = popup.model.index(str(left / "sub" / "deeper"))
    for _ in range(200):                                          # the model reads the folders on its own thread
        QApplication.processEvents()
        target = popup.model.index(str(left / "sub" / "deeper"))
        if target.isValid():
            break
    assert target.isValid()
    popup._go(target)
    assert popup.chosen == os.path.normpath(str(left / "sub" / "deeper"))
    popup.deleteLater()


def test_alt_f10_goes_to_the_folder_chosen_and_a_server_has_no_tree(world, monkeypatch):
    win, _d, left, *_ = world
    (left / "sub").mkdir()

    def choose(popup):
        popup.chosen = str(left / "sub")
        return True
    monkeypatch.setattr(win, "_ask_folder_tree", choose)
    win.show_folder_tree()
    pump(win, lambda: win.left.path == str(left / "sub"))
    monkeypatch.setattr(win.left, "real_folder", lambda: "sftp://host/etc")
    win.show_folder_tree()
    assert "drives of this computer" in win.status.text()
