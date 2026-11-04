"""Scripts run on Enter (Settings > Opening Files > Run Scripts on Enter), in their own folder; Ctrl+Enter shows them."""
import subprocess
import sys

import pytest

from dossier.core import scripts

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows scripts")


def test_which_files_are_scripts():
    assert scripts.is_script("x.PY")
    assert not scripts.is_script("notes.txt") and not scripts.is_script("app.exe")
    if sys.platform == "win32":
        assert scripts.is_script("go.bat") and scripts.is_script("go.CMD") and scripts.is_script("go.ps1")
    assert scripts.launch_for("notes.txt") is None


@WINDOWS
@pytest.mark.parametrize("name, body", [
    ("go.bat", "@echo off\r\ncd > where.txt\r\n"),
    ("go.cmd", "@echo off\r\ncd > where.txt\r\n"),
    ("go.ps1", "(Get-Location).Path | Out-File -Encoding ascii where.txt\r\n"),
])
def test_a_script_really_runs_in_its_own_folder_whatever_the_folder_is_called(tmp_path, name, body):
    """The same command Enter starts, run here without a window: the script finds its folder as its working folder."""
    folder = tmp_path / "it's a & b (1)"
    folder.mkdir()
    script = folder / name
    script.write_text(body, encoding="ascii")
    launch = scripts.launch_for(str(script))
    assert launch.cwd == str(folder)
    done = subprocess.run(launch.argv, cwd=launch.cwd, capture_output=True, text=True, timeout=60,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (folder / "where.txt").read_text(encoding="ascii").strip().lower() == str(folder).lower()


@WINDOWS
def test_a_powershell_script_is_started_as_explorers_run_with_powershell():
    launch = scripts.launch_for("C:\\x\\it's.ps1")
    command = launch.argv[-1]
    assert launch.argv[0] == "powershell.exe" and "Set-ExecutionPolicy -Scope Process Bypass" in command and "AllSigned" in command
    assert command.endswith("& 'C:\\x\\it''s.ps1'")


# the window ----------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.helpers import settle  # noqa: E402


@pytest.fixture
def scripted(world):
    win, d, left, right, tmp = world
    started, viewed = [], []
    win.launch_terminal = lambda launch: started.append(launch)
    win.view_file = lambda paths: viewed.append(list(paths))
    win.system_opened = []
    win._open_with_system = lambda p: win.system_opened.append(p)                # never really started by a test
    name = "go.bat" if sys.platform == "win32" else "go.sh"
    (left / name).write_text("echo hi\n")
    (left / "notes.txt").write_text("hi")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of(name) >= 0)
    return win, d, str(left / name), started, viewed


def test_enter_runs_a_script_and_ctrl_enter_shows_it(scripted):
    win, d, path, started, viewed = scripted
    assert win.run_scripts()                                                      # on unless switched off
    assert win._open_file(path) and len(started) == 1 and started[0].cwd == str(scripts.os.path.dirname(path))
    assert win._open_file(path, alternate=True) and viewed == [[path]]
    assert win._open_file(path.replace("go.", "notes.").rsplit(".", 1)[0] + ".txt")
    settle(win)                                                                   # its first bytes are read on a thread
    assert len(viewed) == 2                                                       # text: the viewer, as before


def test_switched_off_enter_shows_a_script_and_ctrl_enter_runs_it_through_windows(scripted):
    win, d, path, started, viewed = scripted
    win.set_run_scripts(False)
    assert not win.run_scripts()
    assert win._open_file(path)
    settle(win)
    assert viewed == [[path]] and not started
    assert win._open_file(path, alternate=True)
    settle(win)
    assert win.system_opened == [path] and len(viewed) == 1                       # handed to the Windows program
    win.set_run_scripts(True)
    assert win.run_scripts()


def test_everything_in_the_viewer_wins_over_running(scripted):
    win, d, path, started, viewed = scripted
    win.set_open_choice("all")
    assert win._open_file(path) and viewed == [[path]] and not started


def test_a_script_that_cannot_start_says_why(scripted):
    win, d, path, started, viewed = scripted

    def refuse(launch):
        raise OSError(2, "The system cannot find the file specified")
    win.launch_terminal = refuse
    win._open_file(path)
    assert d.infos and "could not be started" in d.infos[-1][1]


def test_the_setting_is_in_the_opening_files_menu(scripted):
    win, *_ = scripted
    assert win.act_run_scripts.isCheckable() and win.act_run_scripts.isChecked() and "Run Scripts on Enter" in win.act_run_scripts.text()
