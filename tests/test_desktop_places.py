"""The fixes of section 1.9 of the Mac and Linux review (2026-11-18): the desktop's own folder names on Linux, iCloud Drive and
Applications on the Mac, the Mac's hidden flag, and AppleDouble ``._`` files as hidden and as junk."""
from __future__ import annotations

import os
import types

from dossier.core import health_rules, home, platform, search
from dossier.core.vfs import Entry


USER_DIRS = """# This file is written by xdg-user-dirs-update
XDG_DESKTOP_DIR="$HOME/Skrivebord"
XDG_DOWNLOAD_DIR="$HOME/Nedlastinger"
XDG_DOCUMENTS_DIR="/data/Dokumenter"
XDG_MUSIC_DIR="$HOME/"
XDG_PICTURES_DIR="relative/not/allowed"
"""


def test_user_dirs_file_gives_the_desktops_own_names():
    found = platform.parse_user_dirs(USER_DIRS, "/home/kari")
    assert found == {"DESKTOP": "/home/kari/Skrivebord", "DOWNLOAD": "/home/kari/Nedlastinger", "DOCUMENTS": "/data/Dokumenter"}


def test_linux_home_page_uses_the_names_of_user_dirs(monkeypatch):
    monkeypatch.setattr(platform, "IS_LINUX", True)
    monkeypatch.setattr(platform, "IS_MACOS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/kari/.config")
    folders = dict(platform.user_folders("/home/kari", read=lambda path: USER_DIRS))
    assert folders["Skrivebord"] == "/home/kari/Skrivebord"
    assert folders["Nedlastinger"] == "/home/kari/Nedlastinger"
    assert folders["Dokumenter"] == "/data/Dokumenter"
    assert folders["Music"] == os.path.join("/home/kari", "Music")            # turned off in the file: the English name stays
    assert "Desktop" not in folders


def test_a_missing_user_dirs_file_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(platform, "IS_LINUX", True)
    monkeypatch.setattr(platform, "IS_MACOS", False)

    def missing(path):
        raise FileNotFoundError(path)

    assert [t for t, _p in platform.user_folders("/home/kari", read=missing)] == [e for _k, e in platform.KNOWN_FOLDERS]


def test_mac_home_page_has_icloud_drive_and_applications(monkeypatch):
    monkeypatch.setattr(platform, "IS_LINUX", False)
    monkeypatch.setattr(platform, "IS_MACOS", True)
    provider = home.HomeProvider(volumes=lambda: [], home=lambda: "/Users/kari", exists=lambda p: True)
    titles = dict(home.place_folders(provider))
    assert titles["Applications"] == "/Applications"
    assert titles["iCloud Drive"] == os.path.join("/Users/kari", "Library", "Mobile Documents", "com~apple~CloudDocs")


def test_the_macs_hidden_flag_counts_as_hidden(monkeypatch):
    monkeypatch.setattr(search, "IS_WINDOWS", False)
    st = types.SimpleNamespace(st_mode=0o40755, st_flags=0x8000)
    bits = platform.mode_and_flags(st)
    assert bits & platform.HIDDEN_FLAG
    assert "H" in search.attribute_letters(Entry(name="Library", path="/Users/kari/Library", is_dir=True, attrs=bits))
    plain = platform.mode_and_flags(types.SimpleNamespace(st_mode=0o40755))
    assert "H" not in search.attribute_letters(Entry(name="Documents", path="/x", is_dir=True, attrs=plain))


def test_appledouble_files_are_hidden_on_every_system(monkeypatch):
    for windows in (True, False):
        monkeypatch.setattr(search, "IS_WINDOWS", windows)
        monkeypatch.setattr(platform, "IS_WINDOWS", windows)
        assert "H" in search.attribute_letters(Entry(name="._photo.jpg", path="x", is_dir=False, attrs=0o100644 if not windows else 0x20))
        assert "H" not in search.attribute_letters(Entry(name="photo.jpg", path="x", is_dir=False, attrs=0o100644 if not windows else 0x20))


def test_appledouble_files_are_junk_in_health():
    assert health_rules.is_junk_name("._photo.jpg")
    assert health_rules.is_junk_name(".DS_Store")
    assert not health_rules.is_junk_name("_photo.jpg")
    found = list(health_rules.junk(None, Entry(name="._song.mp3", path="/m/._song.mp3", is_dir=False)))
    assert len(found) == 1


class _FakeXattrs:
    def __init__(self, store):
        self.store = store

    def _list(self, path):
        return list(self.store.get(path, {}))

    def _get(self, path, name):
        return self.store[path][name]

    def _set(self, path, name, value):
        if path == "/full/dst":
            raise OSError("no room")
        self.store.setdefault(path, {})[name] = value


def test_a_copy_keeps_every_extended_attribute_as_it_is():
    from dossier.core import filetags
    store = {"/a/src": {filetags.FINDER_TAGS: b"red-with-colour", "com.apple.metadata:kMDItemWhereFroms": b"site",
                        "security.selinux": b"label"}}
    backend = _FakeXattrs(store)
    assert filetags.copy_attributes("/a/src", "/b/dst", backend)
    assert store["/b/dst"] == {filetags.FINDER_TAGS: b"red-with-colour", "com.apple.metadata:kMDItemWhereFroms": b"site"}
    assert not filetags.copy_attributes("/a/src", "/full/dst", backend)
