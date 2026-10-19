import os

from dossier.core.filetypes import BY_EXTENSION, DRIVE_ICONS, all_icon_names, icon_name

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "dossier", "gui", "icons", "tabler")


def test_every_mapped_icon_has_a_file():
    missing = [n for n in sorted(all_icon_names()) if not os.path.isfile(os.path.join(ICON_DIR, n + ".svg"))]
    assert missing == []


def test_the_icons_used_by_the_commander_exist():
    for n in ("copy", "arrows-right-left", "trash", "pencil", "folder-plus", "refresh", "arrow-up", "search"):
        assert os.path.isfile(os.path.join(ICON_DIR, n + ".svg")), n


def test_the_licence_of_the_icons_is_shipped_with_them():
    text = open(os.path.join(ICON_DIR, "LICENSE-tabler.txt"), encoding="utf-8").read()
    assert text.startswith("MIT License") and "Permission is hereby granted" in text


def test_names_follow_kind_then_extension_ignoring_case():
    assert icon_name("x", is_dir=True) == "folder"
    assert icon_name("..", is_up=True, is_dir=True) == "corner-left-up"
    assert icon_name("l", is_link=True, is_dir=True) == "link"
    assert icon_name("Cover.JPG") == "photo"
    assert icon_name("a.EPUB") == "book" and icon_name("a.cbz") == "book-2"
    assert icon_name("README.md") == "markdown"
    assert icon_name("archive.tar.gz") == "file-zip"
    assert icon_name("noext") == "file" and icon_name("weird.zzz") == "file"


def test_no_extension_is_claimed_by_two_groups():
    from dossier.core.filetypes import GROUPS
    seen = {}
    for icon, exts in GROUPS.items():
        for e in exts.split():
            assert e not in seen, f"{e} is in both {seen[e]} and {icon}"
            seen[e] = icon
    assert len(seen) == len(BY_EXTENSION)


def test_every_drive_kind_has_an_icon():
    for kind in ("fixed", "removable", "network", "optical", "other", "home"):
        assert kind in DRIVE_ICONS
