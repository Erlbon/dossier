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
        self.verify_answer = None            # None: leave the checkbox as offered
        self.transfer_offered_verify = None
        self.outputs = []
        self.save_answer = "discard"
        self.disk_answer = "overwrite"
        self.save_path = None

    def info(self, title, text):
        self.infos.append((title, text))

    def confirm(self, title, text, ok_label="OK"):
        self.confirms.append((title, text))
        return self.confirm_answer

    def confirm_transfer(self, title, text, ok_label, verify):
        self.confirms.append((title, text))
        self.transfer_offered_verify = verify
        if not self.confirm_answer:
            return None
        return self.verify_answer if self.verify_answer is not None else verify

    def ask_save(self, name):
        return self.save_answer

    def ask_changed_on_disk(self, name):
        return self.disk_answer

    def ask_save_path(self, default):
        return self.save_path

    def show_output(self, title, text):
        self.outputs.append((title, text))

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


def test_drive_selector_defaults_to_the_dropdown_and_switches_to_the_strip(world):
    win, _d, _l, _r, tmp = world
    for panel in (win.left, win.right):
        assert panel.drive_bar.style == "menu"
        assert panel.drive_bar.chip.isVisible() and not panel.drive_bar.strip.isVisible()
    win.set_drive_style("strip")
    for panel in (win.left, win.right):
        assert panel.drive_bar.strip.isVisible() and not panel.drive_bar.chip.isVisible()
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs())
    again.show()
    try:
        assert again.left.drive_bar.style == "strip" and again.drive_style_actions["strip"].isChecked()
    finally:
        again.close()


def test_drive_list_marks_the_current_drive_and_lists_home(world):
    win, _d, left, *_ = world
    bar = win.left.drive_bar
    assert bar.current is not None and os.path.normcase(str(left)).startswith(os.path.normcase(bar.current.path))
    assert bar.chip.text() == bar.current.name
    names_ = [a.text().split("\t")[0] for a in bar.menu.actions()]
    assert any(n.startswith("Home") for n in names_)
    win.set_drive_style("strip")
    assert bar._strip_buttons[bar.current.path].isChecked()


def test_choosing_a_drive_goes_to_its_root_and_back_to_the_remembered_folder(world):
    win, _d, left, *_ = world
    bar = win.left.drive_bar
    home = next(d for d in bar.drives if d.kind == "home")
    (left / "deep").mkdir()
    win.left.set_folder(str(left / "deep"))
    here = bar.current
    bar.chosen.emit(home)
    assert win.left.path == home.path
    if here is not None:
        bar.chosen.emit(here)                               # back where this panel last was on that drive
        assert win.left.path == str(left / "deep")


def test_alt_f1_opens_the_drive_list_of_the_left_panel(world):
    win, *_ = world
    win.left.open_drive_menu()
    QApplication.processEvents()
    assert win.left.drive_bar.menu.isVisible()
    win.left.drive_bar.menu.close()


def test_f_key_bar_only_offers_working_commands(world):
    win, *_ = world
    assert [b.text() for b in win._fkey_buttons] == ["F2 Rename", "F3 View", "F4 Edit", "F5 Copy", "F6 Move", "F7 Folder", "F8 Delete"]


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


def test_the_window_asks_windows_for_no_border_and_again_after_a_theme_change(world, monkeypatch):
    win, *_ = world
    calls = []
    import dossier.gui.main_window as mw
    monkeypatch.setattr(mw, "set_window_border", lambda hwnd, color: calls.append(color) or True)
    win.set_scheme("dark")
    win.set_scheme("light")
    assert calls and set(calls) == {None}                   # None: no border at all
