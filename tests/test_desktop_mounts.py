"""Card 48A (2026-11-18): shares and phones mounted by the Linux desktop (GVfs, kio-fuse) appear, and Mount... works on the Mac
(``open smb://``) and Linux (``gio mount``)."""
from __future__ import annotations

from dossier.core import drives, home, mounting, platform

BS = chr(92)
MOUNTS = [
    "/dev/sda2 / ext4 rw 0 0",
    "gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw,nosuid 0 0",
    "kio-fuse /run/user/1000/kio-fuse-AbCd fuse.kio-fuse rw 0 0",
    "tmpfs /run/user/1000 tmpfs rw 0 0",
    "portal /run/user/1000/doc fuse.portal rw 0 0",
]
GVFS = ["smb-share:server=nas,share=media", "mtp:host=SAMSUNG_SAMSUNG_Android_R58", "google-drive:host=gmail.com,user=kari",
        "sftp:host=pi.local,user=kari"]


def _listdir(folder):
    assert folder == "/run/user/1000/gvfs"
    return GVFS


def test_desktop_mounts_are_listed_with_readable_names_and_kinds():
    vols = platform.volumes_from_mounts(MOUNTS, _listdir)
    by_root = {r: (l, k) for r, l, k in vols}
    assert by_root["/"] == ("System", "fixed")
    gv = "/run/user/1000/gvfs/"
    assert by_root[gv + GVFS[0]] == ("media on nas", "network")
    assert by_root[gv + GVFS[1]] == ("SAMSUNG SAMSUNG Android R58", "removable")
    assert by_root[gv + GVFS[2]][1] == "network" and "kari@gmail.com" in by_root[gv + GVFS[2]][0]
    assert by_root[gv + GVFS[3]] == ("pi.local (kari) (sftp)", "network")
    assert by_root["/run/user/1000/kio-fuse-AbCd"] == ("KDE network folders", "network")
    assert "/run/user/1000/doc" not in by_root and "/run/user/1000" not in by_root


def test_a_desktop_share_is_a_network_drive_by_its_name_so_delete_warns():
    vols = platform.volumes_from_mounts(MOUNTS, _listdir)
    found = drives.list_drives(vols, "/home/kari")
    share = next(d for d in found if d.path.endswith("share=media"))
    assert share.name == "media on nas" and share.kind == "network"
    assert drives.is_network_path(share.path + "/film.mkv", found)


def test_the_home_page_shows_desktop_mounts_by_name():
    vols = [v for v in platform.volumes_from_mounts(MOUNTS, _listdir) if v[0] != "/run/user/1000/kio-fuse-AbCd"]
    provider = home.HomeProvider(volumes=lambda: vols, home=lambda: "/home/kari", exists=lambda p: False)
    names = {e.name: e for e in home.build_entries(provider)}
    assert names["media on nas"].kind == "network"
    assert names["SAMSUNG SAMSUNG Android R58"].kind == "removable"


def test_mount_takes_the_macs_and_linux_url_form(monkeypatch):
    assert mounting.clean_address(mounting.SMB, "smb://nas/My%20Media") == BS * 2 + "nas" + BS + "My Media"
    assert mounting.clean_address(mounting.NFS, "nfs://nas/volume1/media") == "nas:/volume1/media"
    assert mounting.share_url(mounting.SMB, BS * 2 + "nas" + BS + "My Media") == "smb://nas/My%20Media"
    assert mounting.share_url(mounting.NFS, "nas:/volume1/media") == "nfs://nas/volume1/media"
    monkeypatch.setattr(mounting, "IS_WINDOWS", False)
    monkeypatch.setattr(mounting, "IS_MACOS", True)
    assert mounting.build_command(mounting.SMB, BS * 2 + "nas" + BS + "media") == ["open", "smb://nas/media"]
    monkeypatch.setattr(mounting, "IS_MACOS", False)
    assert mounting.build_command(mounting.SMB, BS * 2 + "nas" + BS + "media") == ["gio", "mount", "smb://nas/media"]


def test_a_mount_that_wants_a_login_is_recognised():
    assert mounting.wants_login("gio: smb://nas/media: Password required for share media on nas")
    assert not mounting.wants_login("gio: smb://nas/media: Host is down")
