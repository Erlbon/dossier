"""An interactive SSH session on a server from the terminal button, F12 and Tools > SSH Terminal Here: the command line is built safely, the host
key must have been approved, and nothing about a password is ever put on it."""
import pytest

from dossier.core import servers, sshlink, terminals
from dossier.core.sshlink import ConnectError, HostKey

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, world  # noqa: E402,F401

CONN = servers.Connection(name="Home", host="nas.example", user="alice", port=2222, key_file="C:/keys/id nas")


def fake_ssh(monkeypatch, found=True):
    monkeypatch.setattr(sshlink, "find_tool", lambda name: "/usr/bin/ssh" if found else "")


def test_the_session_command_uses_the_approved_host_keys_and_a_terminal_and_no_password_helper(monkeypatch):
    fake_ssh(monkeypatch)
    argv = sshlink.session_command(CONN, "/h/known_hosts", "/home/alice/my music")
    assert argv[0] == "/usr/bin/ssh"
    assert "StrictHostKeyChecking=yes" in argv and "UserKnownHostsFile=/h/known_hosts" in argv
    assert argv[argv.index("-p") + 1] == "2222" and argv[argv.index("-i") + 1] == "C:/keys/id nas" and "IdentitiesOnly=yes" in argv
    assert "-t" in argv and "alice@nas.example" in argv
    assert "BatchMode=yes" not in argv and not any("askpass" in a.lower() for a in argv)       # ssh asks for a password itself, in the window
    assert argv[-1] == "cd '/home/alice/my music' && exec \"${SHELL:-/bin/sh}\" -l"


def test_a_folder_name_cannot_become_a_command(monkeypatch):
    fake_ssh(monkeypatch)
    nasty = "/tmp/x'; rm -rf ~; '"
    last = sshlink.session_command(CONN, "/h/kh", nasty)[-1]
    assert last.startswith("cd '/tmp/x'\"'\"'; rm -rf ~; '\"'\"'' && exec ")              # one quoted word, the quote itself escaped
    for bad in ("/a\nb", "/a\rb", "/a" + chr(0) + "b"):
        with pytest.raises(ConnectError):
            sshlink.session_command(CONN, "/h/kh", bad)


def test_no_remote_folder_means_the_servers_own_start_folder_and_a_missing_ssh_is_explained(monkeypatch):
    fake_ssh(monkeypatch)
    plain = servers.Connection(name="Home", host="nas.example")
    argv = sshlink.session_command(plain, "/h/kh")
    assert argv[-1] == "nas.example" and "-i" not in argv
    fake_ssh(monkeypatch, found=False)
    with pytest.raises(ConnectError, match="OpenSSH is not installed"):
        sshlink.session_command(plain, "/h/kh")


def test_the_ssh_command_is_hosted_like_a_local_terminal_session(monkeypatch):
    argv = ["ssh", "-t", "alice@nas", "cd '/a;b' && exec sh"]
    monkeypatch.setattr(terminals, "IS_WINDOWS", True)
    wt = terminals.ssh_launch(argv, "C:/Users/me", windows_terminal="wt.exe")
    assert wt.argv[:3] == ["wt.exe", "-d", "C:/Users/me"] and wt.argv[3:6] == argv[:3] and wt.argv[-1] == "cd '/a" + chr(92) + ";b' && exec sh"
    plain = terminals.ssh_launch(argv, "C:/Users/me")
    assert plain.argv == argv and not plain.elevate
    monkeypatch.setattr(terminals, "IS_WINDOWS", False)
    linux = terminals.ssh_launch(argv, "/home/me", emulator="xterm", which=lambda n: "/usr/bin/" + n)
    assert linux.argv == ["xterm", "-e", *argv] and not linux.elevate


# in the window -------------------------------------------------------------------------------------------------------------
class Recorder:
    def __init__(self):
        self.launches = []

    def __call__(self, launch):
        self.launches.append(launch)


@pytest.fixture
def ssh_window(world, monkeypatch):
    win, d, left, right, tmp = world
    fake_ssh(monkeypatch)
    rec = Recorder()
    win.launch_terminal = rec
    win._save_connections([CONN])
    return win, d, rec


def approve(win, host="nas.example", port=2222):
    win.known_hosts().add(host, port, [HostKey("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIexample")])


def test_a_session_opens_in_the_folder_shown_for_a_server_whose_key_was_approved(ssh_window):
    win, d, rec = ssh_window
    approve(win)
    win.open_ssh_terminal("sftp://alice@nas.example:2222/home/alice/music")
    assert len(rec.launches) == 1 and d.infos == []
    argv = rec.launches[0].argv
    assert "alice@nas.example" in argv and argv[-1].startswith("cd /home/alice/music && exec ")
    assert "UserKnownHostsFile=" + sshlink.option_path(win.known_hosts().path) in argv


def test_a_server_whose_host_key_was_never_approved_is_refused_with_a_reason(ssh_window):
    win, d, rec = ssh_window
    win.open_ssh_terminal("sftp://alice@nas.example:2222/home/alice")
    assert rec.launches == [] and "host key" in d.infos[-1][1]


def test_only_a_server_folder_can_have_a_session_and_an_unknown_server_is_said_so(ssh_window):
    win, d, rec = ssh_window
    win.open_ssh_terminal(str(win.left.path))
    assert rec.launches == [] and "SFTP or SCP server" in d.infos[-1][1]
    win.open_ssh_terminal("sftp://bob@elsewhere/home")
    assert rec.launches == [] and "not in your list" in d.infos[-1][1]


def test_the_terminal_command_on_a_server_folder_opens_a_session_and_admin_is_refused(ssh_window):
    win, d, rec = ssh_window
    approve(win)
    win.open_terminal(folder="sftp://alice@nas.example:2222/srv")
    assert len(rec.launches) == 1 and rec.launches[0].argv[-1].startswith("cd /srv && exec ")
    win.open_terminal(admin=True, folder="sftp://alice@nas.example:2222/srv")
    assert len(rec.launches) == 1 and "administrator terminal is for this computer" in d.infos[-1][1]
    win.open_terminal(folder="webdav://x@host/a")
    assert len(rec.launches) == 1 and "SSH session" in d.infos[-1][1]


def test_the_terminal_buttons_menu_offers_the_session_only_on_a_server(ssh_window, monkeypatch):
    win, d, rec = ssh_window
    menu = win.build_terminal_menu()
    ssh = next(a for a in menu.actions() if a.text() == "Open an SSH Session to This Server")
    assert not ssh.isEnabled()
    monkeypatch.setattr(type(win.active), "path", property(lambda self: "sftp://alice@nas.example:2222/srv"))
    ssh = next(a for a in win.build_terminal_menu().actions() if a.text() == "Open an SSH Session to This Server")
    assert ssh.isEnabled()


def test_the_command_is_a_menu_action_and_a_function_key_choice(world):
    from dossier.gui import fkeys
    win, *_ = world
    assert "open_ssh_terminal" in fkeys.COMMANDS and "open_ssh_terminal" in win._command_actions
    assert win._command_actions["open_ssh_terminal"][0].text() == "SSH Terminal Here"
