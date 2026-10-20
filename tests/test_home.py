"""The Home page as a file system: drives, places, pinned folders and network, without touching the disks.
The made-up computer is built with os.path so the same tests hold on Windows and Linux."""
import os

import pytest

from dossier.core.home import (ADD_NETWORK, HOME_URL, MOUNT_SHARE, HomeFileSystem, HomeProvider, RouterFileSystem, build_entries,
                               is_home, is_shortcut_kind, place_folders, removable_from_home)
from dossier.core.vfs import LocalFileSystem, NotWritable

J = os.path.join
BASE = os.path.abspath(os.sep)
C_ROOT, D_ROOT, Z_ROOT = J(BASE, "c"), J(BASE, "d"), J(BASE, "z")
ME = J(C_ROOT, "Users", "me")
SHARE = "//server/media"
VOLUMES = [(C_ROOT, "Windows", "fixed"), (D_ROOT, "", "removable"), (Z_ROOT, SHARE, "network")]
PINNED, GONE = J(D_ROOT, "pinned"), J(D_ROOT, "gone")
EXISTING = {ME, J(ME, "Documents"), J(ME, "Downloads"), J(ME, "OneDrive"), PINNED, J(ME, "Dropbox")}


def provider(**kw):
    base = dict(volumes=lambda: VOLUMES, home=lambda: ME, exists=lambda p: p in EXISTING,
                environ={}, pins=lambda: [], network=lambda: [])
    base.update(kw)
    return HomeProvider(**base)


def kinds(entries):
    return [e.kind for e in entries]


def test_is_home_recognises_the_page_and_nothing_else():
    assert is_home("home://") and is_home("home:") and not is_home("home://#drives") and not is_home(C_ROOT)


def test_sections_come_in_order_with_headers():
    entries = build_entries(provider(pins=lambda: [PINNED], network=lambda: ["//nas/share"]))
    assert [e.name for e in entries if e.kind == "header"] == ["Local drives", "Places", "Pinned folders", "Network"]
    assert kinds(entries)[0] == "header" and entries[-1].kind == "action" and [e.path for e in entries[-2:]] == [ADD_NETWORK, MOUNT_SHARE]


def test_local_drives_are_listed_with_labels_and_kinds_and_network_drives_go_to_the_network_section():
    entries = build_entries(provider())
    drives = [e for e in entries if e.kind in ("fixed", "removable")]
    assert [e.path for e in drives] == [C_ROOT, D_ROOT]
    assert "Windows" in drives[0].name and all(e.is_dir for e in drives)
    net = [e for e in entries if e.kind == "network"]
    assert len(net) == 1 and net[0].path == Z_ROOT and net[0].detail == SHARE
    first_network_header = next(i for i, e in enumerate(entries) if e.kind == "header" and e.name == "Network")
    assert entries.index(net[0]) > first_network_header


def test_places_list_only_folders_that_exist_and_cloud_folders_are_found_once():
    names = [t for t, _ in place_folders(provider())]
    assert names == ["Home", "Documents", "Downloads", "OneDrive", "Dropbox"]
    via_env = place_folders(provider(environ={"OneDrive": J(ME, "OneDrive")}))
    assert [t for t, _ in via_env].count("OneDrive") == 1                       # the same folder is not listed twice
    cloud = J(BASE, "e", "Cloud")
    elsewhere = place_folders(provider(environ={"OneDrive": cloud}, exists=lambda p: p in EXISTING | {cloud}))
    assert ("OneDrive", cloud) in elsewhere


def test_pinned_folders_and_saved_network_locations_appear_and_a_missing_pin_says_so():
    entries = build_entries(provider(pins=lambda: [PINNED, GONE], network=lambda: ["//nas/share"]))
    pins = [e for e in entries if e.kind == "pin"]
    assert [e.name for e in pins] == ["pinned", "gone"]
    assert pins[0].detail == PINNED and "not found" in pins[1].detail
    loc = [e for e in entries if e.kind == "netloc"]
    assert loc[0].name == "//nas/share" and loc[0].path == "//nas/share"


def test_there_is_no_pinned_section_when_nothing_is_pinned():
    assert "Pinned folders" not in [e.name for e in build_entries(provider())]


def test_entry_kinds_tell_what_can_be_opened_and_what_can_be_removed():
    for kind in ("fixed", "removable", "network", "place", "pin", "netloc"):
        assert is_shortcut_kind(kind)
    assert not is_shortcut_kind("header") and not is_shortcut_kind("action")
    assert removable_from_home("pin") and removable_from_home("netloc")
    assert not removable_from_home("fixed") and not removable_from_home("place")


def test_listing_the_page_never_asks_the_disks_anything():
    asked = []
    p = provider(exists=lambda path: asked.append(path) or False)
    build_entries(p)
    assert all(a.startswith(ME) for a in asked)                                 # only the user's folders were checked


# the file systems ---------------------------------------------------------------------------------------------------
def test_the_home_file_system_has_one_read_only_folder():
    fs = HomeFileSystem(provider())
    assert fs.is_root(HOME_URL) and fs.parent(HOME_URL) is None and not fs.writable
    assert fs.stat(HOME_URL).is_dir and fs.list(HOME_URL)
    with pytest.raises(FileNotFoundError):
        fs.list("home://elsewhere")
    with pytest.raises(NotWritable):
        fs.mkdir("home://x")
    with pytest.raises(NotWritable):
        fs.remove("home://x")
    with pytest.raises(NotWritable):
        fs.open_read("home://x")


def test_the_router_sends_each_path_to_its_own_system(tmp_path):
    router = RouterFileSystem(LocalFileSystem(), HomeFileSystem(provider()))
    assert router.list(HOME_URL)[0].kind == "header"
    (tmp_path / "f.txt").write_text("x")
    assert [e.name for e in router.list(str(tmp_path))] == ["f.txt"]
    assert router.parent(HOME_URL) is None and router.parent(str(tmp_path)) == str(tmp_path.parent)
    assert router.join(str(tmp_path), "f.txt") == str(tmp_path / "f.txt")
    assert router.basename(str(tmp_path / "f.txt")) == "f.txt"
    router.mkdir(str(tmp_path / "new"))
    assert (tmp_path / "new").is_dir()
    with pytest.raises(NotWritable):
        router.mkdir("home://new")
    assert router.sep == LocalFileSystem().sep and router.case_sensitive == LocalFileSystem().case_sensitive


def test_a_drive_root_has_no_parent_on_the_local_system(tmp_path):
    local = LocalFileSystem()
    root = tmp_path.anchor
    assert local.is_root(root) and local.parent(root) is None
    assert local.parent(str(tmp_path)) is not None
