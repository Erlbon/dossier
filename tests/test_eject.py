"""Card 47A (2026-11-18): Eject on all three systems (core/eject.py)."""
from __future__ import annotations

import subprocess

from dossier.core import eject

BS = chr(92)


def test_only_removable_drives_discs_and_shares_can_be_ejected():
    assert eject.can_eject("/media/kari/STICK", "removable")
    assert eject.can_eject("E:" + BS, "optical")
    assert eject.can_eject("Z:" + BS, "network")
    assert not eject.can_eject("C:" + BS, "fixed")
    assert not eject.can_eject("/", "removable")


def test_each_system_gets_its_own_command(monkeypatch):
    monkeypatch.setattr(eject, "IS_WINDOWS", False)
    monkeypatch.setattr(eject, "IS_MACOS", True)
    assert eject.eject_commands("/Volumes/STICK", "removable") == [["diskutil", "eject", "/Volumes/STICK"]]
    assert eject.eject_commands("/Volumes/media", "network") == [["diskutil", "unmount", "/Volumes/media"]]
    monkeypatch.setattr(eject, "IS_MACOS", False)
    gio = lambda name: "/usr/bin/gio" if name == "gio" else None       # noqa: E731
    assert eject.eject_commands("/media/kari/STICK", "removable", gio) == [["gio", "mount", "--eject", "/media/kari/STICK"]]
    share = "/run/user/1000/gvfs/smb-share:server=nas,share=media"
    assert eject.eject_commands(share, "network", gio) == [["gio", "mount", "--unmount", share]]
    assert eject.eject_commands("/mnt/nas", "network", lambda n: None) == [["umount", "/mnt/nas"]]
    monkeypatch.setattr(eject, "IS_WINDOWS", True)
    assert eject.eject_commands("E:" + BS, "removable") == []                   # done in-process
    cmd = eject.eject_commands("Z:" + BS, "network")[0]
    assert cmd[1:] == ["use", "Z:", "/delete"] and cmd[0].lower().endswith("net.exe")


def test_a_refusal_passes_on_the_systems_reason(monkeypatch):
    monkeypatch.setattr(eject, "IS_WINDOWS", False)
    monkeypatch.setattr(eject, "IS_MACOS", True)

    def busy(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "Volume STICK on disk4s1 failed to eject: in use by Preview")

    result = eject.eject("/Volumes/STICK", "removable", runner=busy)
    assert not result.ok and "in use by Preview" in result.output
    ok = eject.eject("/Volumes/STICK", "removable", runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""))
    assert ok.ok


def test_windows_eject_says_when_a_file_is_open(monkeypatch):
    monkeypatch.setattr(eject, "IS_WINDOWS", True)

    def held(root):
        err = OSError(32, "in use")
        err.winerror = 32
        raise err

    result = eject.eject("E:" + BS, "removable", windows_eject=held)
    assert not result.ok and "another program has a file open" in result.output
    assert eject.eject("E:" + BS, "removable", windows_eject=lambda root: None).ok


def test_queued_copies_to_the_drive_are_found():
    assert eject.touches("/media/kari/STICK", ["/home/kari/a.txt", "/media/kari/STICK/b.txt"])
    assert not eject.touches("/media/kari/STICK", ["/media/kari/STICK2/b.txt"])
