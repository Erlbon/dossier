"""The test helper picks Git for Windows' sftp-server before the Windows OpenSSH one (the GitHub runner has both, the OpenSSH one first)."""
import os

from tests import sftp_server


def test_git_for_windows_build_is_chosen_even_when_another_is_on_the_path(tmp_path, monkeypatch):
    git_root = tmp_path / "Git"
    (git_root / "cmd").mkdir(parents=True)
    (git_root / "usr" / "lib" / "ssh").mkdir(parents=True)
    (git_root / "cmd" / "git.exe").write_text("")
    wanted = git_root / "usr" / "lib" / "ssh" / "sftp-server.exe"
    wanted.write_text("")
    other = tmp_path / "OpenSSH" / "sftp-server.exe"
    other.parent.mkdir()
    other.write_text("")
    monkeypatch.setattr(sftp_server.shutil, "which", lambda name: {"git": str(git_root / "cmd" / "git.exe"), "sftp-server": str(other)}.get(name))
    assert os.path.normpath(sftp_server.find_sftp_server()) == os.path.normpath(str(wanted))
    monkeypatch.setattr(sftp_server, "CANDIDATES", ())
    wanted.unlink()
    assert sftp_server.find_sftp_server() == str(other)                  # nothing else: whatever is on the path
