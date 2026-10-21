"""Enter and double-click on a file: the viewer or the program Windows has for it, by a setting; Ctrl+Enter does the other thing."""
import os

import pytest

from dossier.core import viewmodes

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402

from tests.test_gui_commander import app, key, pump, world  # noqa: E402,F401


def test_the_rule_for_each_setting_and_for_ctrl_enter(tmp_path):
    text, binary = tmp_path / "a.txt", tmp_path / "b.bin"
    text.write_text("hello")
    binary.write_bytes(bytes(range(256)) * 4)
    assert viewmodes.opens_in_viewer(str(text), "viewer") and not viewmodes.opens_in_viewer(str(binary), "viewer")
    assert not viewmodes.opens_in_viewer(str(text), "viewer", alternate=True) and viewmodes.opens_in_viewer(str(binary), "viewer", alternate=True)
    assert not viewmodes.opens_in_viewer(str(text), "system") and viewmodes.opens_in_viewer(str(text), "system", alternate=True)
    assert viewmodes.opens_in_viewer(str(binary), "all") and not viewmodes.opens_in_viewer(str(binary), "all", alternate=True)
    assert viewmodes.opens_in_viewer("zip:x!/pic.PNG", "viewer", local=False)
    assert not viewmodes.opens_in_viewer("zip:x!/doc.docx", "viewer", local=False)


@pytest.fixture
def opened(monkeypatch):
    """The files handed to the Windows program (nothing is really started)."""
    from PyQt6.QtGui import QDesktopServices
    seen = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: seen.append(os.path.normpath(url.toLocalFile())) or True)
    return seen


def cursor_on(win, name):
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of(name) >= 0)
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of(name), 0))


def test_enter_shows_a_text_file_in_the_viewer_and_sends_a_binary_file_to_windows(world, opened):
    win, _d, left, _r, _t = world
    (left / "note.txt").write_text("hello")
    (left / "prog.bin").write_bytes(bytes(range(256)) * 4)
    cursor_on(win, "note.txt")
    key(win, Qt.Key.Key_Return)
    assert len(win.viewers) == 1 and opened == []
    cursor_on(win, "prog.bin")
    key(win, Qt.Key.Key_Return)
    assert len(win.viewers) == 1 and opened == [str(left / "prog.bin")]


def test_ctrl_enter_does_the_other_thing_and_marks_stay_as_they_were(world, opened):
    win, _d, left, _r, _t = world
    (left / "note.txt").write_text("hello")
    (left / "other.txt").write_text("x")
    cursor_on(win, "note.txt")
    win.selection.add([str(left / "other.txt")])
    key(win, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert opened == [str(left / "note.txt")] and not win.viewers
    assert win.selection.paths() == [str(left / "other.txt")]
    key(win, Qt.Key.Key_Return)                                # Enter views the file under the cursor, not the marked one
    assert len(win.viewers) == 1


def test_the_setting_is_kept_and_changes_what_enter_does(world, opened):
    win, _d, left, _r, _t = world
    (left / "note.txt").write_text("hello")
    cursor_on(win, "note.txt")
    assert win.open_choice() == "viewer"
    win.set_open_choice("system")
    assert win.settings.value("open/files") == "system" and win.open_actions["system"].isChecked()
    key(win, Qt.Key.Key_Return)
    assert opened == [str(left / "note.txt")] and not win.viewers
    key(win, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(win.viewers) == 1
    win.settings.setValue("open/files", "nonsense")
    assert win.open_choice() == "viewer"
