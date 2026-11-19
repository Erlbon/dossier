"""Taildrop in the window: Send to Device in the right-click menu, Files Waiting for You on the Home page. A fake runner stands in for tailscale."""
import pytest

pytest.importorskip("PyQt6")

from dossier.core import tailnet  # noqa: E402
from dossier.core.ops import Resolution  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401
from tests.test_servers_gui import wait  # noqa: E402,F401
from tests.test_tailnet import STATUS  # noqa: E402


@pytest.fixture
def drop(monkeypatch):
    monkeypatch.setattr(tailnet, "read_devices", lambda *a, **k: tailnet.parse_status(STATUS))
    monkeypatch.setattr(tailnet, "find_tailscale", lambda: "ts")
    log = []
    return log


def loaded(win):
    win.refresh_tailnet(force=True)
    wait(win, lambda: win.tailnet_items())


def send_menu(win, row):
    menu = win.build_context_menu(win.left, row)
    sub = next((a for a in menu.actions() if a.text() == "Send to Device"), None)
    return sub.menu() if sub else None


def test_the_send_menu_lists_the_other_devices_online_ones_usable_and_offline_ones_greyed(world, drop):
    win, d, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    loaded(win)
    sub = send_menu(win, win.left.model.row_of("a.txt"))
    assert [(a.text(), a.isEnabled()) for a in sub.actions()] == [("homeserver3", True), ("alpha-nas", False), ("zeta-phone", False)]
    assert "offline" in sub.actions()[1].toolTip()


def test_no_send_menu_without_tailscale_for_a_folder_or_with_the_tailnet_switched_off(world, drop):
    win, d, left, *_ = world
    (left / "a.txt").write_text("a")
    (left / "sub").mkdir()
    win.left.refresh()
    assert send_menu(win, win.left.model.row_of("a.txt")) is None            # nothing read yet: no Tailscale
    loaded(win)
    assert send_menu(win, win.left.model.row_of("sub")) is None
    win.act_tailnet.setChecked(False)
    assert send_menu(win, win.left.model.row_of("a.txt")) is None


def test_sending_runs_file_cp_for_each_marked_file_on_a_thread_and_says_what_happened(world, drop):
    win, d, left, *_ = world
    for n in ("a.txt", "b.txt"):
        (left / n).write_text(n)
    win.left.refresh()
    loaded(win)
    win.taildrop_runner = lambda command, cancel=None: (drop.append(command) or (0, ""))
    sub = send_menu(win, win.left.model.row_of("a.txt"))
    sub.actions()[0].trigger()                                   # the item right-clicked, unmarked: that file alone
    wait(win, lambda: len(drop) == 1 and "Sent" in win.status.text())
    assert drop[0] == ["ts", "file", "cp", str(left / "a.txt"), "100.118.213.22:"]
    assert win.status.text().startswith("Sent 1 file to homeserver3")
    win.send_to_device([str(left / "a.txt"), str(left / "b.txt")], "homeserver3")
    wait(win, lambda: len(drop) == 3 and "Sent 2 files" in win.status.text())
    assert [c[3] for c in drop[1:]] == [str(left / "a.txt"), str(left / "b.txt")]


def test_a_failed_send_shows_the_programs_own_words(world, drop):
    win, d, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    loaded(win)
    win.taildrop_runner = lambda command, cancel=None: (1, "Taildrop is not enabled for this device")
    win.send_to_device([str(left / "a.txt")], "homeserver3")
    wait(win, lambda: d.infos)
    assert "Taildrop is not enabled for this device" in d.infos[-1][1] and "a.txt" in d.infos[-1][1]


def received(drop, files, code=0, text=""):
    def run(command, cancel=None):
        drop.append(command)
        for name, body in files.items():
            (__import__("pathlib").Path(command[3]) / name).write_text(body)
        return code, text
    return run


def test_receiving_shows_a_plan_then_places_the_files_and_removes_its_folder(world, drop):
    win, d, left, right, tmp = world
    dest = tmp / "incoming"
    dest.mkdir()
    (dest / "photo.jpg").write_text("old")
    d.folder_answer = str(dest)
    d.conflict_answer = Resolution.KEEP_BOTH
    loaded(win)
    win.taildrop_runner = received(drop, {"photo.jpg": "new", "note.txt": "n"})
    win._home_action("home://#taildrop-receive")
    wait(win, lambda: len(d.confirms) == 1 and not win.busy)
    wait(win, lambda: (dest / "note.txt").exists() and not win.busy)
    assert drop[0][:3] == ["ts", "file", "get"] and drop[0][3].startswith(str(dest))
    assert d.folders_asked[0][0] == "Receive Taildrop Files" and d.folders_asked[0][1]          # the default folder was offered
    title, text = d.confirms[0]
    assert "photo.jpg" in text and "note.txt" in text and str(dest) in text
    assert (dest / "photo.jpg").read_text() == "old"                                           # never overwritten silently
    assert len(list(dest.glob("photo*"))) == 2 and "new" in [p.read_text() for p in dest.glob("photo*")]      # kept both
    wait(win, lambda: not any(p.name.startswith(".dossier-taildrop-") for p in dest.iterdir()))


def test_receiving_with_nothing_waiting_says_so_and_leaves_no_folder(world, drop):
    win, d, left, right, tmp = world
    dest = tmp / "incoming"
    dest.mkdir()
    d.folder_answer = str(dest)
    loaded(win)
    win.taildrop_runner = received(drop, {})
    win.receive_taildrop()
    wait(win, lambda: d.infos)
    assert d.infos[-1][1] == "No files are waiting for you." and list(dest.iterdir()) == []


def test_receiving_cancelled_at_the_folder_question_runs_nothing(world, drop):
    win, d, *_ = world
    d.folder_answer = None
    loaded(win)
    win.taildrop_runner = received(drop, {})
    win.receive_taildrop()
    wait(win, lambda: getattr(d, "folders_asked", None))
    pump(win)
    assert drop == []


def test_the_receive_row_is_on_the_home_page_only_when_tailscale_answers(world, drop):
    win, *_ = world

    def names():
        win.left.go_home()
        pump(win, lambda: win.left.is_home)
        return [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    assert "Fetch files sent to you..." not in names()
    loaded(win)
    assert "Fetch files sent to you..." in names()
