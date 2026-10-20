"""Mounting SMB and NFS shares through the system: address cleaning, commands, the NFS check, the window flow."""
import subprocess
import sys
import time

import pytest

from dossier.core import mounting
from dossier.core.mounting import NFS, SMB, clean_address, free_letters

B = chr(92)


def test_share_addresses_are_cleaned_and_bad_ones_refused():
    assert clean_address(SMB, "//nas/media/") == B * 2 + "nas" + B + "media"
    assert clean_address(SMB, '"' + B * 2 + "nas" + B + "media" + B + "tv" + '"') == B * 2 + "nas" + B + "media" + B + "tv"
    assert clean_address(SMB, B * 2 + "nas") == ""                          # no share name
    assert clean_address(SMB, "https://nas/media") == "" and clean_address(SMB, "") == ""
    assert clean_address(SMB, B * 2 + "nas" + B + "my media") == ""         # spaces are not accepted here
    assert clean_address(NFS, "nas:/export/data") == "nas:/export/data"
    assert clean_address(SMB, "nas:/export") == ""                          # the server:/export form is NFS only


def test_free_letters_skip_used_ones_and_a_b():
    letters = free_letters(["C:" + B, "D:" + B, "Z:" + B])
    assert "C:" not in letters and "Z:" not in letters and "A:" not in letters and letters[0] == "Y:"


@pytest.mark.skipif(sys.platform != "win32", reason="the commands are built for Windows")
def test_the_commands_never_carry_a_password():
    smb = mounting.build_command(SMB, B * 2 + "nas" + B + "media", "Y:")
    assert smb == ["net", "use", "Y:", B * 2 + "nas" + B + "media", "/persistent:no"]
    nfs = mounting.build_command(NFS, "nas:/export", "")
    assert nfs[0] == "mount" and nfs[-1] == "*" and not any("pass" in a.lower() for a in smb + nfs)


def test_the_nfs_check_looks_for_mount_exe_without_admin_rights(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows only")
    (tmp_path / "System32").mkdir()
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert mounting.nfs_client_installed() is False
    (tmp_path / "System32" / "mount.exe").write_text("x")
    assert mounting.nfs_client_installed() is True


def test_a_run_reports_output_and_failure_without_raising():
    ok = mounting.run_command(["x"], runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, "done\n", ""))
    assert ok.ok and ok.output == "done"
    bad = mounting.run_command(["x"], runner=lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "System error 53"))
    assert not bad.ok and "53" in bad.output

    def missing(*a, **k):
        raise FileNotFoundError(2, "no such program")
    assert not mounting.run_command(["x"], runner=missing).ok

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)
    assert "No answer" in mounting.run_command(["x"], runner=slow).output


pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.core.home import MOUNT_SHARE, HomeProvider, build_entries  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_home_page_offers_the_mount_action(world):
    entries = build_entries(HomeProvider(volumes=lambda: [], exists=lambda p: False, environ={}))
    assert any(e.path == MOUNT_SHARE and e.kind == "action" for e in entries)


@pytest.mark.skipif(sys.platform != "win32", reason="the commands are built for Windows")
def test_the_window_mounts_through_the_runner_and_shows_what_the_system_said(world):
    win, d, *_ = world
    seen = []

    def fake(argv, **k):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "The command completed successfully.", "")

    win.mount_runner = fake
    win.mount_share_with(SMB, "//nas/media", "Y:")
    pump(win, lambda: d.outputs)
    assert seen and seen[0][:3] == ["net", "use", "Y:"]
    assert "completed successfully" in d.outputs[-1][1] and "Mounted" in d.outputs[-1][0]


def test_a_bad_address_is_explained_and_nothing_runs(world):
    win, d, *_ = world
    win.mount_runner = lambda *a, **k: pytest.fail("must not run")
    win.mount_share_with(SMB, "not a share", "")
    assert d.infos and "not a share address" in d.infos[-1][1]


def test_nfs_without_the_client_explains_how_to_switch_it_on_and_runs_nothing(world, monkeypatch):
    win, d, *_ = world
    monkeypatch.setattr(mounting, "nfs_client_installed", lambda: False)
    win.mount_runner = lambda *a, **k: pytest.fail("must not run")
    win.mount_share_with(NFS, "nas:/export", "")
    assert "Enable-WindowsOptionalFeature" in d.infos[-1][1]
    assert win.nfs_status_text() == "Client for NFS: not switched on"
