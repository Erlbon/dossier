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
    assert clean_address(SMB, B * 2 + "nas" + B + "my media") == B * 2 + "nas" + B + "my media"      # spaces are fine
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

from PyQt6.QtWidgets import QDialog  # noqa: E402

from dossier.core.home import ADD_NETWORK, HomeProvider, build_entries  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def test_the_home_page_has_one_entry_for_adding_a_share(world):
    entries = build_entries(HomeProvider(volumes=lambda: [], exists=lambda p: False, environ={}))
    shares = [e for e in entries if e.kind == "action" and e.path == ADD_NETWORK]
    assert [(e.path, e.name) for e in shares] == [(ADD_NETWORK, "Add a network share...")]


def answer(win, monkeypatch, protocol=SMB, address="", mount=False, letter=""):
    """Make the dialog answer: fill it in and press its default button."""
    def fake(self, dlg):
        dlg.protocol.setCurrentIndex(dlg.protocol.findData(protocol))
        dlg.address.setText(address)
        dlg.mount.setChecked(mount) if protocol == SMB else None
        if letter:
            dlg.letter.setCurrentIndex(dlg.letter.findData(letter))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(type(win), "_ask_mount", fake)


def test_an_smb_share_without_mounting_is_just_saved_on_the_home_page(world, monkeypatch):
    win, d, *_ = world
    win.mount_runner = lambda *a, **k: pytest.fail("must not mount")
    answer(win, monkeypatch, SMB, "//nas/media", mount=False)
    win.add_network_share()
    assert win._saved_list("home/network") == [B * 2 + "nas" + B + "media"] and "Saved" in win.status.text()


@pytest.mark.skipif(sys.platform != "win32", reason="the commands are built for Windows")
def test_ticking_mount_runs_the_system_command_and_saves_nothing(world, monkeypatch):
    win, d, *_ = world
    seen = []
    win.mount_runner = lambda argv, **k: (seen.append(argv), subprocess.CompletedProcess(argv, 0, "ok", ""))[1]
    answer(win, monkeypatch, SMB, "//nas/media", mount=True, letter="Y:")
    win.add_network_share()
    pump(win, lambda: d.outputs)
    assert seen and seen[0][:3] == ["net", "use", "Y:"] and win._saved_list("home/network") == []


def test_nfs_is_always_mounted_and_the_dialog_says_so(world, monkeypatch):
    from dossier.gui.mounting import MountDialog
    win, d, *_ = world
    dlg = MountDialog(win, ["Y:"], True)
    dlg.protocol.setCurrentIndex(dlg.protocol.findData(NFS))
    assert dlg.mount.isChecked() and not dlg.mount.isEnabled() and dlg.letter.isEnabled() and dlg.ok.text() == "Mount"
    assert dlg.values()[3] is True
    dlg.protocol.setCurrentIndex(dlg.protocol.findData(SMB))
    dlg.mount.setChecked(False)
    assert dlg.mount.isEnabled() and not dlg.letter.isEnabled() and dlg.ok.text() == "Add" and dlg.values()[3] is False


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
