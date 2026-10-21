"""Connecting through the system's ssh: host keys and known hosts, the password helper, the command line, and a whole connect against a fake
``ssh`` that serves a real ``sftp-server``."""
import json
import os
import subprocess
import sys

import pytest

from dossier.core import askpass, sshlink
from dossier.core.servers import Connection
from tests.sftp_server import find_sftp_server, find_sh, make_fake_ssh

ED25519 = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
RSA_LIKE = "AAAAB3NzaC1yc2EAAAADAQABAAABgQC" + "A" * 80
needs_server = pytest.mark.skipif(find_sftp_server() is None, reason="no sftp-server on this computer")


# host keys -------------------------------------------------------------------------------------------------------------------------
def test_the_fingerprint_is_the_one_ssh_keygen_shows(tmp_path):
    fp = sshlink.fingerprint(ED25519)
    assert fp.startswith("SHA256:") and not fp.endswith("=") and len(fp) == len("SHA256:") + 43
    tool = sshlink.find_tool("ssh-keygen")
    if tool:
        key = tmp_path / "k.pub"
        key.write_text(f"ssh-ed25519 {ED25519}\n")
        shown = subprocess.run([tool, "-l", "-f", str(key)], capture_output=True, text=True).stdout
        assert fp in shown


def test_the_keyscan_output_is_read_and_the_best_key_comes_first():
    text = (f"# files.example.com:22 SSH-2.0-OpenSSH_9.6\nfiles.example.com ssh-rsa {RSA_LIKE}\n"
            f"# files.example.com:22 SSH-2.0-OpenSSH_9.6\nfiles.example.com ssh-ed25519 {ED25519}\nfiles.example.com ssh-ed25519 {ED25519}\n"
            "garbage line\n")
    keys = sshlink.parse_keyscan(text)
    assert [k.type for k in keys] == ["ssh-ed25519", "ssh-rsa"] and keys[0].fingerprint.startswith("SHA256:")
    assert sshlink.parse_keyscan("") == []


def test_approved_keys_are_kept_and_a_different_key_is_a_changed_host(tmp_path):
    kh = sshlink.KnownHosts(str(tmp_path / "sub" / "known_hosts"))
    key = sshlink.HostKey("ssh-ed25519", ED25519)
    other = sshlink.HostKey("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIOther" + "x" * 20)
    assert kh.check("h.example.com", 22, [key]) == "unknown"
    kh.add("h.example.com", 22, [key])
    kh.add("h.example.com", 22, [key])                                             # twice is once
    assert kh.check("h.example.com", 22, [key]) == "known" and kh.check("h.example.com", 22, [other]) == "changed"
    assert kh.check("h.example.com", 22, [other, key]) == "known"
    assert kh.check("other.example.com", 22, [key]) == "unknown"
    kh.add("h.example.com", 2222, [other])                                          # another port is another server
    assert "[h.example.com]:2222 ssh-ed25519" in open(kh.path).read() and kh.check("h.example.com", 2222, [key]) == "changed"
    assert open(kh.path).read().count("h.example.com ssh-ed25519") == 1
    kh.remove("h.example.com", 22)
    assert kh.check("h.example.com", 22, [key]) == "unknown" and kh.check("h.example.com", 2222, [other]) == "known"


def test_what_ssh_says_is_turned_into_a_sentence_the_owner_can_act_on():
    f = sshlink.friendly
    assert "user name, the password or the key" in f("me@h: Permission denied (publickey,password).")
    assert "no computer with that name" in f("ssh: Could not resolve hostname nope: Name or service not known")
    assert "did not answer in time" in f("ssh: connect to host h port 22: Connection timed out")
    assert "refused the connection" in f("ssh: connect to host h port 22: Connection refused")
    assert "no SFTP service" in f("subsystem request failed on channel 0")
    assert "host key has changed" in f("WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!")
    assert f("something odd\nlast line") == "last line" and f("") == ""


# the password helper ---------------------------------------------------------------------------------------------------------------
def test_the_helper_answers_password_questions_only():
    env = {askpass.VARIABLE: "s3cret"}
    assert askpass.answer("me@host's password: ", env) == b"s3cret\n"
    assert askpass.answer("Enter passphrase for key '/home/me/.ssh/id_ed25519': ", env) == b"s3cret\n"
    assert askpass.answer("Are you sure you want to continue connecting (yes/no)? ", env) == b""
    assert askpass.answer("password", {}) == b"\n"


def test_the_shim_hands_a_password_with_awkward_characters_over_untouched(tmp_path):
    shim = sshlink.askpass_shim(str(tmp_path / "ssh"))
    assert os.path.isfile(shim) and sshlink.askpass_shim(str(tmp_path / "ssh")) == shim            # made once, reused
    secret = 'a%b^c&d"e|f<g>h \u00e6\u00f8\u00e5 !x$y'
    env = dict(os.environ, **{askpass.VARIABLE: secret})
    done = subprocess.run([shim, "me@host's password: "], capture_output=True, env=env, creationflags=sshlink.no_window())
    assert done.stdout.decode("utf-8").rstrip("\r\n") == secret
    assert secret not in open(shim, encoding="utf-8").read()                                       # never written to a file


# the command line ------------------------------------------------------------------------------------------------------------------
def test_the_command_line_is_strict_about_host_keys_and_never_holds_a_password(tmp_path, monkeypatch):
    monkeypatch.setattr(sshlink, "find_tool", lambda name: "/usr/bin/ssh")
    c = Connection("Files", "files.example.com", "me", 2222, key_file="C:/keys/id_ed25519")
    cmd = sshlink.ssh_command(c, "/cfg/known_hosts", with_password=False)
    joined = " ".join(cmd)
    assert cmd[0] == "/usr/bin/ssh" and "StrictHostKeyChecking=yes" in joined and "UserKnownHostsFile=/cfg/known_hosts" in joined
    assert "-p 2222" in joined and "BatchMode=yes" in joined and "-i C:/keys/id_ed25519" in joined and "IdentitiesOnly=yes" in joined
    assert cmd[-3:] == ["-s", "me@files.example.com", "sftp"] and "ServerAliveInterval" in joined
    with_pw = " ".join(sshlink.ssh_command(c, "/cfg/known_hosts", with_password=True))
    assert "BatchMode" not in with_pw                                                                # a password may be asked for
    monkeypatch.setattr(sshlink, "find_tool", lambda name: "")
    with pytest.raises(sshlink.ConnectError, match="OpenSSH is not installed"):
        sshlink.ssh_command(c, "/cfg/known_hosts")


def test_a_known_hosts_path_with_a_space_is_quoted_for_ssh_and_written_with_forward_slashes(monkeypatch):
    monkeypatch.setattr(sshlink, "find_tool", lambda name: "/usr/bin/ssh")
    assert sshlink.option_path(r"C:\Users\My Name\ssh\known_hosts") == '"C:/Users/My Name/ssh/known_hosts"'
    assert sshlink.option_path("/home/me/known_hosts") == "/home/me/known_hosts"
    cmd = sshlink.ssh_command(Connection("T", "h", "me"), r"C:\Users\My Name\known_hosts")
    assert 'UserKnownHostsFile="C:/Users/My Name/known_hosts"' in cmd
    assert sshlink.short_path(r"C:\nospaces\x") == r"C:\nospaces\x"


def test_the_environment_carries_the_password_and_nothing_else_does(tmp_path):
    env = sshlink.environment("/cfg/askpass.cmd", "pw")
    assert env["SSH_ASKPASS"] == "/cfg/askpass.cmd" and env["SSH_ASKPASS_REQUIRE"] == "force" and env[askpass.VARIABLE] == "pw"
    assert "DISPLAY" in env


# a whole connect, against a fake ssh that serves a real sftp-server ----------------------------------------------------------------
@needs_server
def test_a_connect_runs_ssh_the_way_it_should_and_gives_a_working_session(tmp_path, monkeypatch):
    log = tmp_path / "call.json"
    make_fake_ssh(tmp_path, monkeypatch, "serve", str(log))
    c = Connection("T", "host.example.com", "me", 2200)
    link = sshlink.connect(c, "hunter2", str(tmp_path / "known_hosts"), str(tmp_path / "ssh"))
    try:
        assert link.client.version == 3
        (tmp_path / "hello.txt").write_text("hi")
        names = [n.name for n in link.client.listdir(str(tmp_path).replace(os.sep, "/"))]
        assert "hello.txt" in names
    finally:
        link.client.close()
    call = json.loads(log.read_text())
    assert "-s" in call["args"] and call["args"][-1] == "sftp" and "me@host.example.com" in call["args"] and "2200" in call["args"]
    assert "hunter2" not in " ".join(call["args"])                                                   # never on the command line
    assert call["env"][askpass.VARIABLE] == "hunter2" and call["env"]["SSH_ASKPASS_REQUIRE"] == "force"
    assert "BatchMode=yes" not in " ".join(call["args"])


@needs_server
def test_without_a_password_ssh_is_told_never_to_ask(tmp_path, monkeypatch):
    log = tmp_path / "call.json"
    make_fake_ssh(tmp_path, monkeypatch, "serve", str(log))
    link = sshlink.connect(Connection("T", "h", "me"), "", str(tmp_path / "kh"), str(tmp_path / "ssh"))
    link.client.close()
    assert "BatchMode=yes" in " ".join(json.loads(log.read_text())["args"])


def test_a_refused_login_a_refused_connection_and_a_silent_server_become_plain_sentences(tmp_path, monkeypatch):
    make_fake_ssh(tmp_path, monkeypatch, "deny")
    with pytest.raises(sshlink.ConnectError, match="user name, the password or the key"):
        sshlink.connect(Connection("T", "h", "me"), "wrong", str(tmp_path / "kh"), str(tmp_path / "ssh"))
    make_fake_ssh(tmp_path, monkeypatch, "refused")
    with pytest.raises(sshlink.ConnectError, match="refused the connection"):
        sshlink.connect(Connection("T", "h", "me"), "", str(tmp_path / "kh"), str(tmp_path / "ssh"))
    make_fake_ssh(tmp_path, monkeypatch, "silent")
    with pytest.raises(sshlink.ConnectError):
        sshlink.connect(Connection("T", "h", "me"), "", str(tmp_path / "kh"), str(tmp_path / "ssh"), timeout=1)


def test_the_scp_kind_asks_ssh_for_a_shell_not_for_the_sftp_service(monkeypatch):
    monkeypatch.setattr(sshlink, "find_tool", lambda name: "/usr/bin/ssh")
    c = Connection("Old box", "old.example.com", "root", 22, protocol="scp")
    cmd = sshlink.ssh_command(c, "/cfg/known_hosts", shell=True)
    assert cmd[-3:] == ["-T", "root@old.example.com", "sh"] and "-s" not in cmd
    assert c.url("/etc") == "scp://root@old.example.com/etc"


@pytest.mark.skipif(find_sh() is None, reason="no POSIX shell on this computer")
def test_a_connect_of_the_scp_kind_gives_a_working_shell_session(tmp_path, monkeypatch):
    log = tmp_path / "call.json"
    make_fake_ssh(tmp_path, monkeypatch, "shell", str(log))
    c = Connection("Old", "old.example.com", "root", protocol="scp")
    link = sshlink.connect(c, "", str(tmp_path / "kh"), str(tmp_path / "ssh"))
    try:
        out, status = link.client.run("echo hello")
        assert out.strip() == b"hello" and status == 0
    finally:
        link.client.close()
    assert "-T" in json.loads(log.read_text())["args"]
