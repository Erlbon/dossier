"""Tools > Change Dates and Attributes and Tools > New Link: the dialogs and what the window does with their answers."""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from dossier.core import filetimes as ft  # noqa: E402
from dossier.core import links  # noqa: E402
from tests.test_gui_commander import app, key, names, pump, world  # noqa: E402,F401

T = 1_600_000_000


def wait(until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def make(folder, name, text="x", mtime=T):
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return str(path)


def show(win, folder_panel, count):
    folder_panel.refresh()
    pump(win, lambda: folder_panel.model.entry_count() >= count)


def test_the_dates_dialog_previews_then_applies(world, monkeypatch):
    win, d, left, right, tmp = world
    a, b = make(left, "a.txt"), make(left, "b.txt")
    show(win, win.left, 3)
    win.selection.add([a, b])
    seen = {}

    def drive(dialog):
        dialog.rule_box.setCurrentIndex(dialog.rule_box.findData(ft.SHIFT))
        dialog.value.setText("+1d")
        dialog.replan()
        wait(lambda: dialog.apply_button.isEnabled() and dialog.table.topLevelItemCount() == 2)
        seen["rows"] = dialog.table.topLevelItemCount()
        seen["headers"] = [dialog.table.headerItem().text(i) for i in range(dialog.table.columnCount())]
        seen["first"] = [dialog.table.topLevelItem(0).text(i) for i in range(dialog.table.columnCount())]
        seen["summary"] = dialog.summary.text()
        seen["on_disk_before"] = os.stat(a).st_mtime
        dialog.apply_button.click()
        dialog.exec = lambda: None
    monkeypatch.setattr(win, "_show_dates_dialog", drive)
    win.change_dates()
    pump(win, lambda: os.stat(a).st_mtime == T + 86400 and os.stat(b).st_mtime == T + 86400)
    assert seen["rows"] == 2 and seen["headers"][:3] == ["Name", "Modified now", "Modified after"]
    assert seen["first"][1].startswith("2020-09-13") and seen["first"][2].startswith("2020-09-14")
    assert "2 items will change" in seen["summary"] and "Nothing is written until you press Apply" in seen["summary"]
    assert seen["on_disk_before"] == T                          # the preview wrote nothing
    pump(win, lambda: "Changed 2 items" in win.status.text())


def test_a_bad_date_is_said_and_nothing_can_be_applied(world, monkeypatch):
    win, d, left, right, tmp = world
    a = make(left, "a.txt")
    show(win, win.left, 2)
    win.selection.add([a])
    seen = {}

    def drive(dialog):
        dialog.value.setText("next tuesday")
        dialog.replan()
        QApplication.processEvents()
        seen["summary"] = dialog.summary.text()
        seen["apply"] = dialog.apply_button.isEnabled()
        dialog.reject()
    monkeypatch.setattr(win, "_show_dates_dialog", drive)
    win.change_dates()
    assert "not a date" in seen["summary"] and seen["apply"] is False
    assert os.stat(a).st_mtime == T


def test_the_table_headers_resize_and_sort(world, monkeypatch):
    win, d, left, right, tmp = world
    show(win, win.left, 1)
    make(left, "a.txt")
    make(left, "b.txt")
    show(win, win.left, 3)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    seen = {}

    def drive(dialog):
        seen["sorting"] = dialog.table.isSortingEnabled()
        seen["mode"] = dialog.table.header().sectionResizeMode(0)
        dialog.reject()
    monkeypatch.setattr(win, "_show_dates_dialog", drive)
    win.change_dates()
    assert seen["sorting"] and seen["mode"].name == "Interactive"


def test_the_attributes_can_be_set_from_the_dialog(world, monkeypatch):
    win, d, left, right, tmp = world
    a = make(left, "a.txt")
    show(win, win.left, 2)
    win.selection.add([a])

    def drive(dialog):
        dialog.date_boxes["modified"].setChecked(False)
        dialog.flag_boxes["readonly"].setCheckState(Qt.CheckState.Checked)
        dialog.replan()
        wait(lambda: dialog.apply_button.isEnabled())
        dialog.apply_button.click()
    monkeypatch.setattr(win, "_show_dates_dialog", drive)
    win.change_dates()
    pump(win, lambda: "readonly" in ft.read_flags(a))
    assert os.stat(a).st_mtime == T


def test_nothing_chosen_to_change_and_items_that_are_not_local(world, monkeypatch):
    win, d, left, right, tmp = world
    show(win, win.left, 1)
    win.selection.clear()
    win.change_dates()
    assert "mark items" in win.status.text()
    opened = []
    monkeypatch.setattr(win, "_show_dates_dialog", lambda dialog: opened.append(dialog))
    monkeypatch.setattr(win.active, "targets", lambda: ["zip://x.zip/inner.txt"])
    win.change_dates()
    assert opened == [] and "drive of this computer" in win.status.text()


def test_a_hard_link_is_made_into_the_other_panel(world, monkeypatch):
    win, d, left, right, tmp = world
    make(left, "a.txt", "hello")
    show(win, win.left, 2)
    key(win, Qt.Key.Key_Down)
    seen = {}

    def drive(dialog):
        seen["folder"] = dialog.folder.text()
        seen["name"] = dialog.name.text()
        seen["symlink_name"] = seen.pop("name")
        dialog.radios[links.HARDLINK].setChecked(True)
        seen["name"] = dialog.name.text()                       # the name followed the kind: a hard link keeps the extension
        dialog.name.setText("b.txt")
        dialog.exec = lambda: None
        dialog.accept()
    monkeypatch.setattr(win, "_show_link_dialog", drive)
    win.new_link()
    wait(lambda: (right / "b.txt").exists())
    assert (right / "b.txt").read_text() == "hello" and seen["folder"] == str(right) and seen["symlink_name"] == "a.txt - link" and seen["name"] == "a - link.txt"
    pump(win, lambda: "Made hard link" in win.status.text())


def test_a_refused_link_opens_the_dialog_again_with_the_reason(world, monkeypatch):
    win, d, left, right, tmp = world
    make(left, "a.txt", "hello")
    make(right, "taken.txt", "mine")
    show(win, win.left, 2)
    key(win, Qt.Key.Key_Down)
    shown = []

    def drive(dialog):
        shown.append((dialog.error.text(), dialog.name.text(), dialog.kind()))
        if len(shown) == 1:
            dialog.radios[links.HARDLINK].setChecked(True)
            dialog.name.setText("taken.txt")
            dialog.accept()
        else:
            dialog.reject()
    monkeypatch.setattr(win, "_show_link_dialog", drive)
    win.new_link()
    wait(lambda: len(shown) == 2)
    assert shown[1][0] and "already there" in shown[1][0] and shown[1][1] == "taken.txt" and shown[1][2] == links.HARDLINK
    assert (right / "taken.txt").read_text() == "mine"


def test_the_link_dialog_offers_only_what_fits(world):
    win, d, left, right, tmp = world
    from dossier.gui.dates_links import LinkDialog
    folder_dialog = LinkDialog(win, str(left), str(right), True)
    assert not folder_dialog.radios[links.HARDLINK].isEnabled()
    file_dialog = LinkDialog(win, str(left / "a.txt"), str(right), False)
    assert not file_dialog.radios[links.JUNCTION].isEnabled() and file_dialog.radios[links.HARDLINK].isEnabled()
    file_dialog.radios[links.HARDLINK].setChecked(True)
    assert not file_dialog.relative.isEnabled()
    assert folder_dialog.answer()[0] == links.SYMLINK


def test_the_menus_have_both_commands(world):
    win, d, left, right, tmp = world
    texts = {a.text() for a in win.findChildren(type(win.menuBar().actions()[0])) if a.text()}
    assert "Change Dates and Attributes..." in texts and "New Link..." in texts
