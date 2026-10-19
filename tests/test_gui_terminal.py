"""The command line under the panels, the terminal buttons, interpreter choice and the elevated warning."""
import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import dossier.gui.main_window as mw  # noqa: E402
from dossier.core.platform import IS_WINDOWS  # noqa: E402
from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs, key  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Recorder:
    def __init__(self):
        self.launches = []
        self.fail = None

    def __call__(self, launch):
        if self.fail:
            raise self.fail
        self.launches.append(launch)


@pytest.fixture
def world(app, tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "my file.txt").write_text("x")
    (left / "a&b.txt").write_text("y")
    dialogs = FakeDialogs()
    rec = Recorder()
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(right)), dialogs=dialogs,
                     terminal_launcher=rec)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)
    yield win, dialogs, rec, left, right, tmp_path
    win.close()


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


# typing goes to the command line -------------------------------------------------------------------------------
def test_typing_in_a_panel_starts_a_command(world):
    win, *_ = world
    QTest.keyClicks(win.active.table, "ec")
    assert win.cmdline.text() == "ec" and win.cmdline.hasFocus()


def test_space_marks_when_nothing_is_typed_and_types_a_space_otherwise(world):
    win, *_ = world
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    QTest.keyClick(win.left.table, Qt.Key.Key_Space)
    QApplication.processEvents()
    assert len(win.selection) == 1
    QTest.keyClicks(win.left.table, "echo")
    win.left.table.setFocus()
    QTest.keyClick(win.left.table, Qt.Key.Key_Space)
    assert win.cmdline.text() == "echo " and len(win.selection) == 1


def test_backspace_edits_the_command_before_it_goes_up(world):
    win, _d, _r, left, *_ = world
    QTest.keyClicks(win.left.table, "ab")
    win.left.table.setFocus()
    QTest.keyClick(win.left.table, Qt.Key.Key_Backspace)
    assert win.cmdline.text() == "a" and win.left.path == str(left)
    win.cmdline.clear()
    QTest.keyClick(win.left.table, Qt.Key.Key_Backspace)
    assert win.left.path == str(left.parent)


def test_escape_clears_the_line_and_returns_to_the_panel(world):
    win, *_ = world
    QTest.keyClicks(win.active.table, "abc")
    QTest.keyClick(win.cmdline, Qt.Key.Key_Escape)
    assert win.cmdline.text() == "" and win.active.table.hasFocus()


def test_up_and_down_walk_this_sessions_history(world):
    win, *_ = world
    win.cmdline.remember("first")
    win.cmdline.remember("second")
    win.cmdline.setText("draft")
    QTest.keyClick(win.cmdline, Qt.Key.Key_Up)
    assert win.cmdline.text() == "second"
    QTest.keyClick(win.cmdline, Qt.Key.Key_Up)
    assert win.cmdline.text() == "first"
    QTest.keyClick(win.cmdline, Qt.Key.Key_Down)
    QTest.keyClick(win.cmdline, Qt.Key.Key_Down)
    assert win.cmdline.text() == "draft"


def test_the_prompt_shows_the_active_panels_folder(world):
    win, *_ = world
    assert "left" in win.prompt.text() and win.prompt.text().endswith(">")
    key(win, Qt.Key.Key_Tab)
    assert "right" in win.prompt.text()


# running ---------------------------------------------------------------------------------------------------------------
def test_enter_runs_the_command_in_the_panels_folder_and_shows_its_output(world):
    win, dialogs, *_ = world
    QTest.keyClicks(win.left.table, "cd" if win.profile.kind == "cmd" else "pwd")
    QTest.keyClick(win.left.table, Qt.Key.Key_Return)
    wait_for(lambda: dialogs.outputs)
    assert "left" in dialogs.outputs[0][1] and win.cmdline.text() == ""
    assert win.cmdline.history


def test_placeholders_are_expanded_and_quoted_for_the_interpreter(world):
    win, dialogs, *_ = world
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("my file.txt"), 0))
    win.cmdline.setText("echo %f")
    win.run_command_line()
    wait_for(lambda: dialogs.outputs)
    assert "my file.txt" in dialogs.outputs[0][1]


def test_a_hostile_name_does_not_become_a_second_command(world):
    win, dialogs, *_ = world
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("a&b.txt"), 0))
    win.cmdline.setText("echo %f")
    win.run_command_line()
    wait_for(lambda: dialogs.outputs)
    out = dialogs.outputs[0][1]
    assert "a&b.txt" in out and "'b.txt' is not recognized" not in out


def test_an_unusable_placeholder_is_explained_and_the_text_stays(world):
    win, dialogs, *_ = world
    win.cmdline.setText("echo %o %f")
    win.left.table.setCurrentIndex(win.left.model.index(0, 0))        # the .. row: no current item
    win.run_command_line()
    assert dialogs.infos and "%f" in dialogs.infos[-1][1] and win.cmdline.text() == "echo %o %f"


def test_enter_with_nothing_typed_still_opens_the_folder_under_the_cursor(world):
    win, _d, _r, left, *_ = world
    (left / "sub").mkdir()
    win.left.refresh()
    win.left.table.setCurrentIndex(win.left.model.index(1, 0))
    QTest.keyClick(win.left.table, Qt.Key.Key_Return)
    assert win.left.path == str(left / "sub")


def test_an_unknown_command_reports_instead_of_hanging(world):
    win, dialogs, *_ = world
    win.cmdline.setText("definitely_not_a_program_xyz")
    win.run_command_line()
    wait_for(lambda: dialogs.outputs or "Done" in win.status.text())
    assert "Done" in win.status.text()


# terminals --------------------------------------------------------------------------------------------------------------------
def test_terminal_opens_in_the_active_panels_folder_and_the_other_panels_on_request(world):
    win, _d, rec, left, right, _t = world
    win.open_terminal()
    assert rec.launches[-1].cwd == str(left) and not rec.launches[-1].elevate
    win.open_terminal(other=True)
    assert rec.launches[-1].cwd == str(right)
    assert "Terminal opened" in win.status.text()


def test_the_administrator_terminal_asks_the_system_to_elevate_and_never_for_a_password(world):
    win, _d, rec, left, *_ = world
    win.open_terminal(admin=True)
    launch = rec.launches[-1]
    if IS_WINDOWS:
        assert launch.elevate                      # the UAC prompt, shown by Windows
    else:
        assert launch.argv[-2:] == ["sudo", "-s"]   # typed inside the terminal
    assert "Administrator terminal" in win.status.text()


def test_a_declined_or_failed_launch_is_explained(world):
    win, dialogs, rec, *_ = world
    rec.fail = OSError("the administrator terminal was not started (declined)")
    win.open_terminal(admin=True)
    assert dialogs.infos and "declined" in dialogs.infos[-1][1]


def test_a_remote_folder_has_no_terminal(world, monkeypatch):
    win, dialogs, rec, *_ = world
    monkeypatch.setattr(type(win.active), "path", property(lambda self: "sftp://host/x"))
    win.open_terminal()
    assert not rec.launches and dialogs.infos and "this computer" in dialogs.infos[-1][1]


def test_every_installed_interpreter_has_its_own_visible_button_on_a_separate_line(world):
    win, _d, rec, left, *_ = world
    installed = [p for p, path in win.profiles if path]
    assert installed and set(win.terminal_buttons) == {p.id for p in installed}
    assert win.terminal_bar.isVisible() and win.terminal_bar is not win.cmdline.parentWidget()
    for p in installed:
        win.terminal_buttons[p.id].click()
        assert rec.launches[-1].cwd == str(left)
    assert len(rec.launches) == len(installed)
    commands = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}["Commands"]
    texts = [a.text() for a in commands.actions() if not a.isSeparator()]
    assert "Terminal Here" in texts and "Administrator Terminal Here" in texts


def test_an_interpreter_that_is_not_installed_gets_no_button(app, tmp_path):
    only = {"cmd.exe": "C:/x/cmd.exe", "sh": "/bin/sh"}
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)),
                     dialogs=FakeDialogs(), terminal_launcher=Recorder(), which=lambda n: only.get(n))
    try:
        assert set(win.terminal_buttons) <= {"cmd", "login-shell"} and win.terminal_buttons
    finally:
        win.close()


def test_the_administrator_switch_elevates_the_next_terminal_only_and_looks_dangerous(world):
    win, _d, rec, *_ = world
    first = next(iter(win.terminal_buttons.values()))
    assert not win.admin_toggle.isChecked() and win.admin_toggle.styleSheet() == ""
    win.admin_toggle.setChecked(True)
    assert win.admin_toggle.styleSheet() != ""
    first.click()
    if IS_WINDOWS:
        assert rec.launches[-1].elevate
    else:
        assert rec.launches[-1].argv[-2:] == ["sudo", "-s"]
    assert not win.admin_toggle.isChecked()           # one terminal only
    first.click()
    assert not rec.launches[-1].elevate


def test_the_command_line_interpreter_is_chosen_next_to_the_line_and_remembered(world, app):
    win, _d, rec, left, right, tmp = world
    ids = [win.interpreter.itemData(i) for i in range(win.interpreter.count())]
    assert ids and win.interpreter.currentData() == win.profile.id
    pick = ids[-1]
    win.interpreter.setCurrentIndex(ids.index(pick))
    assert win.profile.id == pick
    titles = [a.text() for a in {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}["Settings"].actions()]
    assert "Command Interpreter" not in titles          # it is not hidden in the settings
    win.close()
    again = MainWindow(settings_path=str(tmp / "s.ini"), dialogs=FakeDialogs(), terminal_launcher=Recorder())
    try:
        assert again.profile.id == pick and again.interpreter.currentData() == pick
    finally:
        again.close()


def test_without_any_interpreter_the_row_is_hidden_and_the_command_line_explains(app, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)),
                     dialogs=FakeDialogs(), terminal_launcher=Recorder(), which=lambda n: None)
    try:
        win.show()
        assert win.profile is None and not win.terminal_buttons and not win.terminal_bar.isVisible()
        win.cmdline.setText("echo hi")
        win.run_command_line()
        assert win.dialogs.infos and "interpreter" in win.dialogs.infos[-1][1]
    finally:
        win.close()


def test_running_with_administrator_rights_is_visible_in_the_title(app, tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "is_elevated", lambda: True)
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(tmp_path), str(tmp_path)),
                     dialogs=FakeDialogs(), terminal_launcher=Recorder())
    try:
        assert win.windowTitle() == "Dossier (Administrator)"
    finally:
        win.close()
