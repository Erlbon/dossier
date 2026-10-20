"""The Windows shell menu: which items qualify, and (on Windows) the real shell filling a menu for a real file."""
import os
import sys
import threading

import pytest

from dossier.core import shellmenu as sm

windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows shell")


@pytest.fixture(autouse=True)
def _quiet_first_chance_com_exceptions():
    """Shell extensions raise and catch exceptions of their own inside COM (RPC_E_DISCONNECTED...). Python's fault handler would print a
    scary "Windows fatal exception" for them although nothing is wrong, so it is off for these tests and back on after."""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was:
        faulthandler.enable()


@windows
def test_only_real_paths_in_one_folder_qualify(tmp_path):
    a, b = str(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    assert sm.can_show([a]) and sm.can_show([a, b])
    assert not sm.can_show([]) and not sm.can_show(["zip://C:/x.zip/in.txt"]) and not sm.can_show(["home://"])
    assert not sm.can_show([a, str(tmp_path / "sub" / "c.txt")])              # two folders: no single menu
    assert not sm.can_show(["relative.txt"]) and not sm.can_show([None])
    assert sm.folder_can_show(str(tmp_path)) and not sm.folder_can_show("home://") and not sm.folder_can_show("mem://x")


def test_other_systems_never_offer_it(monkeypatch):
    monkeypatch.setattr(sm, "IS_WINDOWS", False)
    assert not sm.can_show(["/tmp/a"]) and not sm.folder_can_show("/tmp")
    assert "Windows" in sm.show(["/tmp/a"], 0, 0).error


def in_sta(work):
    """Run ``work`` on a new thread and give back its result (the shell wants its own apartment, as the program does)."""
    box = {}

    def run():
        try:
            box["value"] = work()
        except BaseException as e:   # noqa: BLE001
            box["error"] = e
    t = threading.Thread(target=run)
    t.start()
    t.join(60)
    assert not t.is_alive(), "the shell did not answer"
    if "error" in box:
        raise box["error"]
    return box["value"]


@windows
def test_the_real_shell_fills_a_menu_for_a_file_and_names_cut_copy_and_delete(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hi")

    def look():
        with sm.Session([str(f)]) as s:
            count = s.fill()
            verbs = {s.verb(i) for i in range(sm.FIRST_ID, sm.FIRST_ID + count + 1)}
            return count, verbs

    count, verbs = in_sta(look)
    assert count > 3
    assert {"cut", "copy", "delete", "rename"} <= verbs, verbs


@windows
def test_the_real_shell_fills_a_menu_for_several_files_and_for_the_folder_itself(tmp_path):
    for n in ("a.txt", "b.txt"):
        (tmp_path / n).write_text(n)

    def several():
        with sm.Session([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]) as s:
            return s.fill()

    def folder():
        with sm.Session([str(tmp_path)], background=True) as s:
            count = s.fill(extended=True)
            return count, {s.verb(i) for i in range(sm.FIRST_ID, sm.FIRST_ID + count + 1)}

    assert in_sta(several) > 3
    count, verbs = in_sta(folder)
    assert count > 2 and "new" in verbs                                  # Paste appears only with files on the clipboard


@windows
def test_a_path_the_shell_cannot_find_is_an_error_not_a_crash(tmp_path):
    result = sm.show([str(tmp_path / "no" / "such.txt")], 0, 0)
    assert result.error and not result.verb and not result.ran


@windows
def test_the_whole_show_path_opens_the_real_menu_and_closes_without_a_choice(tmp_path):
    import ctypes
    import time
    f = tmp_path / "hello.txt"
    f.write_text("hi")
    done = []
    thread = sm.show_in_thread([str(f)], 50, 50, done.append)
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    end = time.time() + 20
    while time.time() < end and not done:
        menu = user32.FindWindowW("#32768", None)                 # the class of a pop-up menu
        if menu:
            user32.PostMessageW(menu, 0x100, 0x1B, 0)             # WM_KEYDOWN, Escape: only into that menu's own thread queue
            time.sleep(0.2)
        time.sleep(0.05)
    thread.join(10)
    assert done and done[0] == sm.Outcome(), done
