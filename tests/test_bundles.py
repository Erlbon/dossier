"""Mac apps and packages, Linux launchers and runnable files (card 50A)."""
from __future__ import annotations

import stat

from dossier.core import bundles as B
from dossier.core import desktop_entries as D
from dossier.core.vfs import Entry


def test_mac_packages_are_folders_with_known_extensions_on_the_mac_only():
    assert B.is_package("Mail.app", True, mac=True) and B.is_package("Talk.key", True, mac=True)
    assert B.is_package("Photos Library.photoslibrary/", True, mac=True)
    assert not B.is_package("Mail.app", True, mac=False)                 # Windows and Linux: a plain folder
    assert not B.is_package("Mail.app", False, mac=True)                 # a file is no package
    assert not B.is_package("Projects", True, mac=True)
    assert B.is_app("Mail.app") and not B.is_app("Talk.key")


def test_launchers_get_their_own_name_and_a_broken_one_keeps_its_file_name():
    entries = [Entry("firefox.desktop", "/d/firefox.desktop", False), Entry("broken.desktop", "/d/broken.desktop", False),
               Entry("notes.txt", "/d/notes.txt", False), Entry("dir.desktop", "/d/dir.desktop", True)]
    read = lambda p: D.DesktopApp("firefox.desktop", p, "Firefox", exec="firefox %u") if "firefox" in p else None  # noqa: E731
    named = B.name_launchers(entries, read, linux=True)
    assert [B.shown_name(e) for e in named] == ["Firefox", "broken.desktop", "notes.txt", "dir.desktop"]
    assert named[0].name == "firefox.desktop"                            # the file keeps its name for every operation
    assert B.name_launchers(entries, read, linux=False) is entries


def test_runnable_means_the_run_bit_on_a_file_of_no_known_type():
    run = stat.S_IFREG | 0o755
    assert B.is_runnable("install", False, run, windows=False)
    assert B.is_runnable("App.AppImage", False, run, windows=False)
    assert not B.is_runnable("photo.jpg", False, run, windows=False)    # a FAT stick gives every file the run bit
    assert not B.is_runnable("build.sh", False, run, windows=False)     # a script has its own rule
    assert not B.is_runnable("firefox.desktop", False, run, windows=False)
    assert not B.is_runnable("install", False, stat.S_IFREG | 0o644, windows=False)
    assert not B.is_runnable("bin", True, stat.S_IFDIR | 0o755, windows=False)
    assert not B.is_runnable("install", False, run, windows=True)
