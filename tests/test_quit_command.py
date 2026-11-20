"""``dossier quit`` (also exit and --quit): every running Dossier of the user closes as Ctrl+Q does, without a question, except one with
unsaved notepad text, which stays open and says why. The installer asks it before an update, only of copies that know it.

Every test here has a settings file of its own (tmp_path): ``dossier quit`` must never reach the Dossier the tests run beside."""
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from dossier.core.version import APP_VERSION  # noqa: E402
from dossier.gui import quit_command as Q  # noqa: E402
from tests.helpers import wait_for  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_installer import read  # noqa: E402


def listener(settings_file, kind="window", busy=""):
    win = QWidget()
    win.show()
    win.listener = Q.QuitListener(win, settings_file, kind, lambda: busy, win.close)
    assert win.listener.listening
    return win


def test_every_running_dossier_closes_and_one_with_unsaved_text_says_why(app, tmp_path):
    settings = str(tmp_path / "dossier.ini")
    window, viewer = listener(settings), listener(settings, "viewer")
    notepad = listener(settings, "notepad", busy="it has unsaved changes in notes.txt")
    assert len(os.listdir(tmp_path / "running")) == 3
    lines = []
    assert Q.main(settings, out=lines.append) == 1
    assert sorted(lines) == ["Dossier closed.", "Dossier's notepad stays open: it has unsaved changes in notes.txt.",
                             "Dossier's picture viewer closed."]
    assert not window.isVisible() and not viewer.isVisible() and notepad.isVisible()
    assert os.listdir(tmp_path / "running") == [notepad.listener.key]
    notepad.close()


def test_nothing_running_and_a_dossier_that_died_are_said_plainly(app, tmp_path):
    settings = str(tmp_path / "dossier.ini")
    (tmp_path / "running").mkdir()
    (tmp_path / "running" / "999-dead").write_text('{"name": "dossier-quit-nobody-999", "kind": "window", "pid": 999}')
    lines = []
    assert Q.main(settings, out=lines.append) == 0
    assert lines == ["No Dossier is running."] and os.listdir(tmp_path / "running") == []      # the dead one's file is gone


def test_the_window_closes_saving_its_panels_but_not_over_unsaved_notepad_text(world):
    win, _d, left, right, tmp = world
    (left / "a.txt").write_text("a")
    win.edit_file(str(left / "a.txt"))
    pump(win, lambda: win.editors)
    editor = win.editors[0]
    page = editor.pages()[0] if hasattr(editor, "pages") else editor
    page.editor.setText("changed")
    answers = Q.quit_running(win.settings.fileName(), close_ms=2000)
    assert [a["closing"] for a in answers] == [False] and "a.txt" in answers[0]["reason"] and win.isVisible()
    page.editor.setModified(False)
    page._extra_dirty = False
    answers = Q.quit_running(win.settings.fileName(), close_ms=10000)
    assert [(a["kind"], a["closing"], a["gone"]) for a in answers] == [("window", True, True)]
    assert not win.isVisible() and win.settings.value("panel/left") == str(left)              # closed as Ctrl+Q does, panels kept


def test_dossier_quit_exit_and_dash_dash_quit_never_start_a_window(app, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDACTOR_CONFIG_DIR", str(tmp_path / "profile"))   # its own settings: never the real Dossier's
    from dossier.gui import app as app_mod
    from dossier.gui import main_window
    monkeypatch.setattr(main_window, "MainWindow", lambda *a, **k: pytest.fail("a window was started"))
    for word in ("quit", "exit", "--quit"):
        assert app_mod.main(["dossier", word]) == 0
    assert capsys.readouterr().out.count("No Dossier is running.") == 3


def test_an_older_dossier_that_does_not_listen_is_closed_the_ordinary_way(app, tmp_path, monkeypatch):
    """0.12 and older do not listen: their windows get Windows' ordinary close request (as from their own close button), the ones
    that answered are skipped, and one still open afterwards (asking about unsaved text) is said so."""
    from dossier.core import platform
    asked, alive = [], {111: False, 222: True}
    monkeypatch.setattr(platform, "ask_windows_to_close", lambda exe, skip: asked.append((exe, set(skip))) or [111, 222])
    monkeypatch.setattr(platform, "process_running", lambda pid: alive[pid])
    window = listener(str(tmp_path / "dossier.ini"))
    answers = Q.quit_running(str(tmp_path / "dossier.ini"))
    older = Q.close_older({a["pid"] for a in answers}, close_ms=200)
    assert asked == [("dossier.exe", {os.getpid()})] and not window.isVisible()
    assert [(a["pid"], a["gone"]) for a in older] == [(111, True), (222, False)]


def test_older_copies_are_never_asked_from_a_scratch_profile_or_a_given_settings_file(app, tmp_path, monkeypatch):
    """A test's or the release gate's profile must never reach the Dossier the owner has open."""
    from dossier.core import platform
    asked = []
    monkeypatch.setattr(platform, "ask_windows_to_close", lambda *a: asked.append(a) or [])
    Q.main(str(tmp_path / "dossier.ini"), out=lambda _t: None)
    monkeypatch.setenv("REDACTOR_CONFIG_DIR", str(tmp_path / "profile"))
    Q.main(None, out=lambda _t: None)
    assert asked == []
    monkeypatch.delenv("REDACTOR_CONFIG_DIR")
    from dossier.gui import app_settings
    monkeypatch.setattr(app_settings, "open_settings", lambda path=None: __import__("PyQt6.QtCore", fromlist=["QSettings"]).QSettings(
        str(tmp_path / "usual.ini"), __import__("PyQt6.QtCore", fromlist=["QSettings"]).QSettings.Format.IniFormat))
    lines = []
    assert Q.main(None, out=lines.append) == 0 and len(asked) == 1 and lines == ["No Dossier is running."]   # the usual profile asks


def test_the_installer_asks_a_running_dossier_to_quit_only_when_it_knows_how():
    iss = read("installer", "dossier.iss")
    assert '#define UpdateQuitArgs "--quit"' in iss and '#define UpdateQuitCheck "InstalledKnowsQuit"' in iss
    day, number = Q.SINCE.split("#")
    assert f"CompareStr(Day, '{day}') > 0) or ((Day = '{day}') and (N >= {int(number)}))" in iss
    assert "{C61A77AD-D4A2-44EB-8CFB-B15A58A735F3}_is1" in iss                       # the uninstall entry of this AppId
    assert APP_VERSION >= Q.SINCE                                                   # this build knows it
