"""The commander window, driven offscreen with real key events (plan step 7)."""
import os
import shutil
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.ops import Resolution  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeDialogs:
    def __init__(self):
        self.infos = []
        self.confirms = []
        self.texts = []
        self.conflict_answer = Resolution.SKIP
        self.confirm_answer = True

    def info(self, title, text):
        self.infos.append((title, text))

    def confirm(self, title, text, ok_label="OK"):
        self.confirms.append((title, text))
        return self.confirm_answer

    def ask_text(self, title, label, default=""):
        return self.texts.pop(0) if self.texts else None

    def ask_conflict(self, text):
        return self.conflict_answer

    def make_progress(self, title, on_cancel):
        class Box:
            def update(self, done, total): pass
            def close(self): pass
        return Box()


@pytest.fixture
def world(app, tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (tmp_path / "bin").mkdir()

    def trasher(path):
        shutil.move(path, str(tmp_path / "bin" / (str(time.time_ns()) + "-" + os.path.basename(path))))

    dialogs = FakeDialogs()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=dialogs,
                     trasher=trasher)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)      # window shortcuts only fire in an active window
    yield win, dialogs, left, right, tmp_path
    win.close()


def pump(win, until=lambda: True, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if not win.busy and until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


def key(win, k, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(win.active.table, k, mods)
    QApplication.processEvents()


def names(panel):
    m = panel.model
    return [m.entry_at(r).name for r in range(m.entry_count())]


def test_both_panels_list_their_folders_with_an_up_row_and_folders_first(world):
    win, _d, left, right, _t = world
    (left / "b.txt").write_text("b")
    (left / "adir").mkdir()
    (left / "a.txt").write_text("a")
    win.left.refresh()
    assert names(win.left) == ["..", "adir", "a.txt", "b.txt"]
    assert names(win.right) == [".."]


def test_space_marks_and_moves_down_and_status_counts(world):
    win, _d, left, _r, _t = world
    for n in ("a", "b", "c"):
        (left / n).write_text(n * 10)
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_Space)
    key(win, Qt.Key.Key_Space)
    pump(win)
    assert len(win.selection) == 2
    assert win.left.current_name() == "c"
    assert "2 marked" in win.status.text()


def test_tab_switches_the_active_panel(world):
    win, *_ = world
    assert win.active is win.left
    key(win, Qt.Key.Key_Tab)
    assert win.active is win.right
    key(win, Qt.Key.Key_Tab)
    assert win.active is win.left


def test_f5_copies_marked_files_to_the_other_panel_and_undo_removes_them(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("A")
    (left / "b.txt").write_text("B")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_Space)
    key(win, Qt.Key.Key_Space)
    pump(win)
    key(win, Qt.Key.Key_F5)
    pump(win, lambda: (right / "b.txt").exists())
    assert (right / "a.txt").read_text() == "A" and (left / "a.txt").exists()
    assert len(win.selection) == 0                      # marks are cleared after a copy
    assert names(win.right) == ["..", "a.txt", "b.txt"]  # the other panel refreshed
    win.undo()
    assert not (right / "a.txt").exists() and not (right / "b.txt").exists()


def test_f6_moves_the_item_under_the_cursor_when_nothing_is_marked(world):
    win, _d, left, right, _t = world
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_F6)
    pump(win, lambda: (right / "a.txt").exists())
    assert not (left / "a.txt").exists()
    assert names(win.left) == [".."]


def test_conflict_skip_leaves_the_target_untouched(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("NEW")
    (right / "a.txt").write_text("OLD")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    dialogs.conflict_answer = Resolution.SKIP
    key(win, Qt.Key.Key_F5)
    pump(win)
    assert (right / "a.txt").read_text() == "OLD"


def test_declined_confirmation_changes_nothing(world):
    win, dialogs, left, right, _t = world
    (left / "a.txt").write_text("A")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    dialogs.confirm_answer = False
    key(win, Qt.Key.Key_F5)
    pump(win)
    assert not (right / "a.txt").exists()


def test_f8_deletes_to_the_bin(world):
    win, dialogs, left, _r, tmp = world
    (left / "gone.txt").write_text("x")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_F8)
    pump(win, lambda: not (left / "gone.txt").exists())
    assert len(os.listdir(tmp / "bin")) == 1


def test_f7_creates_a_folder_and_f2_renames(world):
    win, dialogs, left, _r, _t = world
    dialogs.texts = ["newdir"]
    key(win, Qt.Key.Key_F7)
    assert (left / "newdir").is_dir() and win.left.current_name() == "newdir"
    dialogs.texts = ["renamed"]
    key(win, Qt.Key.Key_F2)
    pump(win, lambda: (left / "renamed").exists())
    assert not (left / "newdir").exists()


def test_bad_folder_name_is_refused(world):
    win, dialogs, left, _r, _t = world
    dialogs.texts = ["a/b"]
    key(win, Qt.Key.Key_F7)
    assert dialogs.infos and os.listdir(left) == []


def test_enter_opens_a_folder_and_backspace_goes_up_to_where_we_came_from(world):
    win, _d, left, _r, _t = world
    (left / "sub").mkdir()
    (left / "sub" / "f.txt").write_text("x")
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    key(win, Qt.Key.Key_Return)
    assert win.left.path == str(left / "sub") and names(win.left) == ["..", "f.txt"]
    key(win, Qt.Key.Key_Backspace)
    assert win.left.path == str(left) and win.left.current_name() == "sub"


def test_the_note_is_the_last_row_of_the_list_and_scrolls_with_it(world):
    win, _d, left, _r, _t = world
    for i in range(40):
        (left / f"f{i:02d}.txt").write_text("x")
    (left / "README.md").write_text("# Hello\n\nThe note text.")
    win.left.refresh()
    model, table = win.left.model, win.left.table
    assert model.note_row == model.entry_count()          # directly after the last entry
    assert "The note text." in win.left.note.toPlainText()
    bar = table.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    QApplication.processEvents()
    top_y = win.left.note.geometry().top()
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    assert win.left.note.geometry().top() < top_y          # it moved up with the scrolling list
    assert model.rowCount() == model.entry_count() + 1


def test_a_folder_without_a_note_has_no_note_row(world):
    win, _d, left, _r, _t = world
    (left / "a.txt").write_text("x")
    win.left.refresh()
    assert win.left.model.note_row == -1
    assert win.left.model.rowCount() == win.left.model.entry_count()


def test_columns_sort_and_keep_folders_first(world):
    win, _d, left, _r, _t = world
    (left / "small").write_text("1")
    (left / "big").write_text("1" * 500)
    (left / "dir").mkdir()
    win.left.refresh()
    win.left.model.sort(1, Qt.SortOrder.DescendingOrder)
    assert names(win.left) == ["..", "dir", "big", "small"]


def test_session_is_restored(world, app):
    win, dialogs, left, right, tmp = world
    (left / "sub").mkdir()
    win.left.set_folder(str(left / "sub"))
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs())
    try:
        assert again.left.path == str(left / "sub")
        assert again.right.path == str(right)
    finally:
        again.close()


def test_the_inactive_panel_is_never_dimmed(world):
    win, *_ = world
    assert win.left.table.styleSheet() == "" and win.right.table.styleSheet() == ""
    key(win, Qt.Key.Key_Tab)
    assert win.left.table.styleSheet() == "" and win.right.table.styleSheet() == ""
    assert win.right.bar.styleSheet() != "" and win.left.bar.styleSheet() == ""


def test_color_scheme_menu_switches_persists_and_restyles(world):
    win, _d, left, _r, tmp = world
    (left / "a.txt").write_text("x")
    win.left.refresh()
    win.set_scheme("dark")
    from dossier.gui import theme
    assert theme.current()["bg"] == theme.DARK["bg"] and win.scheme_actions["dark"].isChecked()
    win.left.set_active(True)
    assert "#d4a94f" in win.left.bar.styleSheet()           # the dark accent, solid
    win.set_scheme("light")
    assert "#8a6410" in win.left.bar.styleSheet()           # restyled to the light accent
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs())
    try:
        assert again.theme.scheme == "light" and again.scheme_actions["light"].isChecked()
    finally:
        again.close()


def test_f_key_bar_only_offers_working_commands(world):
    win, *_ = world
    assert [b.text() for b in win._fkey_buttons] == ["F2 Rename", "F5 Copy", "F6 Move", "F7 Folder", "F8 Delete"]


def test_the_active_panel_is_obvious_in_three_ways(world):
    from PyQt6.QtGui import QColor, QPalette
    from dossier.gui import theme
    win, *_ = world
    t = theme.current()
    # active (left): accent frame, solid accent bar, full cursor row
    assert t["accent"] in win.left.styleSheet() and "transparent" in win.right.styleSheet()
    assert t["accent"] in win.left.bar.styleSheet() and win.right.bar.styleSheet() == ""
    active_hl = win.left.table.palette().color(QPalette.ColorRole.Highlight)
    quiet_hl = win.right.table.palette().color(QPalette.ColorRole.Highlight)
    assert active_hl == QColor(t["cursor_bg"]) and quiet_hl == QColor(t["line"]) and active_hl != quiet_hl
    key(win, Qt.Key.Key_Tab)
    assert t["accent"] in win.right.styleSheet() and "transparent" in win.left.styleSheet()
    assert win.right.table.palette().color(QPalette.ColorRole.Highlight) == QColor(t["cursor_bg"])
