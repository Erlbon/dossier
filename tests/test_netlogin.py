"""A network share that refuses us: Windows' own sign-in dialog is asked for, then the folder is opened again."""
import sys

import pytest

from dossier.core import netlogin
from tests.test_gui_commander import app, world  # noqa: F401  (the window fixtures)

B = chr(92)
SHARE = B * 2 + "nas" + B + "media"
FOLDER = SHARE + B + "tv"


def refusal(code: int) -> OSError:
    e = PermissionError(13, "Logon failure")
    e.winerror = code                                                      # type: ignore[attr-defined]
    return e


def test_share_of_gives_the_server_and_share_only():
    assert netlogin.share_of(FOLDER + B + "s01") == SHARE
    assert netlogin.share_of("//nas/media/tv") == SHARE
    assert netlogin.share_of(B * 2 + "nas") == "" and netlogin.share_of("C:" + B + "x") == ""
    assert netlogin.share_of("sftp://host/x") == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows error numbers")
def test_only_login_errors_on_a_share_ask_for_a_login():
    assert netlogin.needs_login(refusal(1326), FOLDER) and netlogin.needs_login(refusal(5), FOLDER)
    assert not netlogin.needs_login(refusal(53), FOLDER)                   # the network path was not found: a login cannot help
    assert not netlogin.needs_login(refusal(1326), "C:" + B + "x")         # not a share


def test_the_login_dialog_gets_the_share_and_a_cancel_means_no():
    seen = []
    assert netlogin.ask_login(FOLDER, 7, lambda share, hwnd: (seen.append((share, hwnd)), 0)[1]) is True
    assert seen == [(SHARE, 7)]
    assert netlogin.ask_login(FOLDER, 0, lambda share, hwnd: netlogin.CANCELLED) is False
    assert netlogin.ask_login("C:" + B + "x", 0, lambda *a: pytest.fail("not a share")) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows error numbers")
def test_a_refused_share_prompts_once_and_opens_after_the_login(world):  # noqa: F811
    win, d, left, right, tmp = world
    state = {"logged_in": False}
    real = win.left.fs.list

    def listing(path):
        if path == FOLDER and not state["logged_in"]:
            raise refusal(1326)
        return [] if path == FOLDER else real(path)

    asked = []

    def connector(share, hwnd):
        asked.append(share)
        state["logged_in"] = True
        return 0

    win.left.fs.list = listing
    win.login_connector = connector
    win.left.set_folder(FOLDER)
    assert asked == [SHARE] and win.left.path == FOLDER


@pytest.mark.skipif(sys.platform != "win32", reason="Windows error numbers")
def test_a_second_refusal_after_the_login_is_reported_not_asked_again(world):  # noqa: F811
    win, d, left, right, tmp = world
    real = win.left.fs.list

    def listing(path):
        if path == FOLDER:
            raise refusal(5)
        return real(path)

    asked = []
    win.left.fs.list = listing
    win.login_connector = lambda share, hwnd: (asked.append(share), 0)[1]
    messages = []
    win.left.message.connect(messages.append)
    win.left.set_folder(FOLDER)
    assert asked == [SHARE] and any("Cannot open" in m for m in messages) and win.left.path != FOLDER


@pytest.mark.skipif(sys.platform != "win32", reason="Windows error numbers")
def test_cancelling_the_login_says_so(world):  # noqa: F811
    win, d, left, right, tmp = world
    real = win.left.fs.list
    win.left.fs.list = lambda path: (_ for _ in ()).throw(refusal(1326)) if path == FOLDER else real(path)
    win.login_connector = lambda share, hwnd: netlogin.CANCELLED
    win.left.set_folder(FOLDER)
    assert "not logged in" in win.status.text() and win.left.path != FOLDER
