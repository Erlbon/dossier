"""The Linux desktop's launchers, associations and type table (core/desktop_entries.py), from the published freedesktop standards."""
from __future__ import annotations

import os

import pytest

from dossier.core import desktop_entries as D

GEDIT = """[Desktop Entry]
Name=Text Editor
Name[nb]=Tekstredigerer
Comment=Edit text files
Exec=gedit %U
Icon=org.gnome.gedit
MimeType=text/plain;
Categories=GNOME;Utility;
Terminal=false

[Desktop Action new-window]
Name=New Window
Exec=gedit --new-window
"""

VIM = """[Desktop Entry]
Name=Vim
Exec=vim %F
Terminal=true
MimeType=text/plain;text/x-python;
NoDisplay=true
"""


def test_a_launcher_is_read_with_its_localised_name_and_only_its_main_group():
    app = D.parse_entry(GEDIT, "/usr/share/applications/org.gnome.gedit.desktop", lang="nb_NO.UTF-8")
    assert app.name == "Tekstredigerer"
    assert app.exec == "gedit %U"                                       # not the action's
    assert app.mime_types == ("text/plain",)
    assert app.shown_in_menus(())
    assert D.parse_entry(GEDIT, "x.desktop", lang="C").name == "Text Editor"
    assert D.parse_entry("no group here", "x.desktop") is None


def test_exec_is_split_as_the_standard_says():
    assert D.split_exec('"/opt/My App/run" --flag "a \\"b\\"" plain') == ["/opt/My App/run", "--flag", 'a "b"', "plain"]
    with pytest.raises(D.BadExec):
        D.split_exec('"unclosed')


def test_exec_codes_give_one_command_for_a_list_and_one_per_file_otherwise():
    many = D.DesktopApp("v.desktop", "/x/v.desktop", "Viewer", exec="viewer --open %F")
    assert D.exec_commands(many, ["/a", "/b"]) == [["viewer", "--open", "/a", "/b"]]
    one = D.DesktopApp("e.desktop", "/x/e.desktop", "Editor", exec="editor %f %i %%x", icon="ed")
    assert D.exec_commands(one, ["/a", "/b"]) == [["editor", "/a", "--icon", "ed", "%x"], ["editor", "/b", "--icon", "ed", "%x"]]
    uri = D.DesktopApp("b.desktop", "/x/b.desktop", "Browser", exec="browser %u")
    assert D.exec_commands(uri, ["/a b"])[0][1].startswith("file://") and "%20" in D.exec_commands(uri, ["/a b"])[0][1]
    none = D.DesktopApp("c.desktop", "/x/c.desktop", "Calc", exec="calc")
    assert D.exec_commands(none, []) == [["calc"]]


def test_the_default_comes_first_then_added_then_the_programs_own_lists(tmp_path):
    apps = {"gedit.desktop": D.parse_entry(GEDIT, "gedit.desktop", "gedit.desktop", "C"),
            "vim.desktop": D.parse_entry(VIM, "vim.desktop", "vim.desktop", "C"),
            "kate.desktop": D.DesktopApp("kate.desktop", "kate.desktop", "Kate", exec="kate %U", mime_types=("text/plain",)),
            "gone.desktop": D.DesktopApp("gone.desktop", "gone.desktop", "Gone", exec="gone", mime_types=("text/plain",), hidden=True)}
    assoc = D.parse_mimeapps(["[Default Applications]\ntext/plain=missing.desktop;vim.desktop;\n"
                              "[Removed Associations]\ntext/plain=kate.desktop;\n",
                              "[Default Applications]\ntext/plain=gedit.desktop\n"])
    parents = {"text/x-python": ["text/plain"]}
    names = [a.name for a in D.apps_for_type("text/x-python", apps, assoc, parents)]
    assert names == ["Vim", "Text Editor"]                               # vim is the default; kate removed; the hidden one gone


def test_a_files_type_comes_from_the_heaviest_pattern():
    globs = D.parse_globs2("# comment\n50:text/plain:*.txt\n50:text/x-readme:readme*\n55:application/x-gzip-tar:*.tar.gz\n"
                           "50:application/gzip:*.gz\n")
    assert D.type_of("notes.TXT", False, globs) == "text/plain"
    assert D.type_of("a.tar.gz", False, globs) == "application/x-gzip-tar"
    assert D.type_of("folder", True, globs) == "inode/directory"
    assert D.type_of("unknown.zzqq", False, globs) == "application/octet-stream"


def test_launchers_are_found_by_id_and_the_users_own_copy_wins(tmp_path):
    user, system = tmp_path / "user", tmp_path / "system"
    (user / "applications").mkdir(parents=True)
    (system / "applications" / "kde").mkdir(parents=True)
    (user / "applications" / "gedit.desktop").write_text(GEDIT.replace("Name=Text Editor", "Name=Mine"), encoding="utf-8")
    (system / "applications" / "gedit.desktop").write_text(GEDIT, encoding="utf-8")
    (system / "applications" / "kde" / "okular.desktop").write_text(VIM.replace("Vim", "Okular"), encoding="utf-8")
    found = D.applications([str(user), str(system)], lang="C")
    assert found["gedit.desktop"].name == "Mine"
    assert found["kde-okular.desktop"].name == "Okular"
    desk = D.Desktop(found, D.Associations(), D.MimeDatabase(D.parse_globs2("50:text/plain:*.txt\n")))
    assert [a.name for a in desk.programs_for("a.txt")] == ["Mine", "Okular"]
    assert [a.name for a in desk.menu_programs()] == ["Mine"]


def test_the_data_and_config_folders_follow_the_environment():
    env = {"XDG_DATA_HOME": "/h/data", "XDG_DATA_DIRS": "/usr/share:/opt/share", "XDG_CONFIG_HOME": "/h/cfg"}
    assert D.data_dirs(env, "/h") == ["/h/data", "/usr/share", "/opt/share"]
    assert D.config_dirs(env, "/h") == ["/h/cfg", "/etc/xdg"]
    assert D.data_dirs({}, "/h")[0] == os.path.join("/h", ".local", "share")
