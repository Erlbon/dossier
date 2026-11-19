"""The Linux launcher and "Open Folders with Dossier" (card 52A): the launcher text, install and remove, mimeapps.list changed one
key at a time with a way back, the first-start offer and the Settings entries. Nothing real is written: every folder is tmp_path."""
from __future__ import annotations

import os

import pytest

from dossier.core import desktop_entries as D
from dossier.core import linux_desktop as L

BS = chr(92)


def _round_trip(words: list) -> list:
    """What a desktop would run for the ``Exec`` line with one file: the value is unescaped, split into words, field codes applied."""
    entry = D.parse_entry(L.launcher_text(words), "dossier.desktop", lang="")
    entry.exec = D._unescape(entry.exec)
    return D.exec_commands(entry, ["/f"])[0]


# the launcher ---------------------------------------------------------------------------------------------------------------------
def test_the_launcher_is_a_valid_desktop_entry_that_takes_files():
    entry = D.parse_entry(L.launcher_text(["/opt/dossier/dossier"], icon="/x/dossier.png"), "dossier.desktop", lang="")
    assert entry.kind == "Application" and entry.name == "Dossier" and entry.icon == "/x/dossier.png"
    assert entry.exec == "/opt/dossier/dossier %F" and not entry.terminal
    assert "inode/directory" in entry.mime_types and "FileManager" in entry.categories
    assert D.exec_commands(entry, ["/home/a/Music"]) == [["/opt/dossier/dossier", "/home/a/Music"]]


@pytest.mark.parametrize("words", [
    ["/home/a b/Dossier 1/dossier"],
    ["/opt/it's/dossier"],
    ["/opt/" + BS + "odd/dos$ier`x`\"q\"/dossier"],
    ["/opt/100%/dossier", "-m", "dossier"],
    ["/usr/bin/python3", "-m", "dossier"],
])
def test_the_exec_line_quotes_a_path_as_the_standard_says(words):
    assert _round_trip(words) == words + ["/f"]


def test_a_path_with_spaces_is_in_double_quotes_and_a_backslash_is_four():
    assert L.exec_word("/a b/dossier") == '"/a b/dossier"'
    assert L.exec_word("/plain/dossier") == "/plain/dossier"
    assert L.exec_word("a" + BS + "b c") == '"a' + BS * 4 + 'b c"'
    assert L.exec_word("100%") == "100%%"


def test_from_source_the_command_runs_the_package_and_the_built_program_runs_itself():
    assert L.program_command(frozen=True, executable="/opt/d/dossier") == ["/opt/d/dossier"]
    assert L.program_command(frozen=False, executable="/usr/bin/python3") == ["/usr/bin/python3", "-m", "dossier"]


def test_install_writes_the_launcher_and_the_icon_and_remove_takes_them_away(tmp_path):
    from dossier.gui import appicon
    data = str(tmp_path / "share")
    path = L.install_launcher(data, ["/opt/dossier/dossier"], appicon.PNG)
    assert path == os.path.join(data, "applications", "dossier.desktop") and L.is_installed(data)
    icon = os.path.join(data, "icons", "hicolor", "256x256", "apps", "dossier.png")
    assert open(icon, "rb").read() == open(appicon.PNG, "rb").read()
    assert D.read_entry(path, lang="").icon == icon
    assert os.listdir(os.path.dirname(path)) == ["dossier.desktop"]            # no temporary file left behind
    L.install_launcher(data, ["/opt/other/dossier"], appicon.PNG)               # again: replaced, not doubled
    assert D.read_entry(path, lang="").exec == "/opt/other/dossier %F"
    assert L.remove_launcher(data) and not L.is_installed(data) and not os.path.exists(icon)
    assert not L.remove_launcher(data)


def test_the_folders_follow_the_xdg_variables(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c")}
    assert L.data_home(env, "/nobody") == str(tmp_path / "d") and L.config_home(env, "/nobody") == str(tmp_path / "c")
    assert L.data_home({}, str(tmp_path)) == os.path.join(str(tmp_path), ".local", "share")
    assert L.config_home({}, str(tmp_path)) == os.path.join(str(tmp_path), ".config")


def test_only_the_linux_tarball_counts_as_the_tarball():
    assert L.running_from_tarball(linux=True, channel="linux-tarball")
    assert not L.running_from_tarball(linux=True, channel="source")
    assert not L.running_from_tarball(linux=True, channel="windows-zip")
    assert not L.running_from_tarball(linux=False, channel="linux-tarball")


# mimeapps.list ---------------------------------------------------------------------------------------------------------------------
ORIGINAL = ("# my choices" + chr(10) + "[Default Applications]" + chr(10) + "text/plain=gedit.desktop;" + chr(10) +
            "inode/directory=org.gnome.Nautilus.desktop;" + chr(10) + "image/png=gimp.desktop;" + chr(10) + chr(10) +
            "[Added Associations]" + chr(10) + "text/plain=vim.desktop;" + chr(10))


def _write(config, text):
    os.makedirs(config, exist_ok=True)
    with open(L.mimeapps_path(config), "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _read(config):
    with open(L.mimeapps_path(config), encoding="utf-8", newline="") as f:
        return f.read()


def test_setting_the_folder_default_changes_only_that_key_and_keeps_the_old_one_second(tmp_path):
    config = str(tmp_path / "config")
    _write(config, ORIGINAL)
    before = L.set_folder_default(config)
    assert before == "org.gnome.Nautilus.desktop;"
    new = _read(config)
    assert new == ORIGINAL.replace("inode/directory=org.gnome.Nautilus.desktop;", "inode/directory=dossier.desktop;org.gnome.Nautilus.desktop;")
    assert L.is_folder_default(config)
    assert D.parse_mimeapps([new]).default["inode/directory"] == ["dossier.desktop", "org.gnome.Nautilus.desktop"]


def test_the_way_back_puts_the_old_value_in_place_byte_for_byte(tmp_path):
    config = str(tmp_path / "config")
    _write(config, ORIGINAL)
    before = L.set_folder_default(config)
    assert L.restore_folder_default(config, before) and _read(config) == ORIGINAL
    assert not L.is_folder_default(config)


def test_a_missing_file_a_missing_group_and_a_missing_key_are_created_and_taken_away_again(tmp_path):
    config = str(tmp_path / "newconfig")                                         # no folder, no file
    assert L.set_folder_default(config) is None
    assert _read(config) == "[Default Applications]" + chr(10) + "inode/directory=dossier.desktop;" + chr(10)
    assert L.restore_folder_default(config, None)
    assert D.parse_mimeapps([_read(config)]).default == {}

    only_added = "[Added Associations]" + chr(10) + "text/plain=vim.desktop;"        # a group, but not that one, and no final newline
    _write(config, only_added)
    assert L.set_folder_default(config, fallback=("org.kde.dolphin.desktop",)) is None
    text = _read(config)
    assert text.startswith(only_added + chr(10)) and D.parse_mimeapps([text]).added == {"text/plain": ["vim.desktop"]}
    assert D.parse_mimeapps([text]).default["inode/directory"] == ["dossier.desktop", "org.kde.dolphin.desktop"]
    assert L.restore_folder_default(config, None)
    assert D.parse_mimeapps([_read(config)]).default == {} and "text/plain=vim.desktop;" in _read(config)

    _write(config, "[Default Applications]" + chr(10) + "text/plain=gedit.desktop;" + chr(10) + chr(10) + "[Added Associations]" + chr(10))
    L.set_folder_default(config)                                                 # the group exists, the key does not: added in the group
    assert D.parse_mimeapps([_read(config)]).default == {"text/plain": ["gedit.desktop"], "inode/directory": ["dossier.desktop"]}
    assert _read(config).index("inode/directory") < _read(config).index("[Added Associations]")


def test_windows_line_endings_comments_and_other_groups_survive(tmp_path):
    config = str(tmp_path / "config")
    text = "[Default Applications]" + "\r" + chr(10) + "# keep me" + "\r" + chr(10) + "inode/directory=thunar.desktop;" + "\r" + chr(10)
    _write(config, text)
    before = L.set_folder_default(config)
    assert before == "thunar.desktop;" and "# keep me" in _read(config)
    L.restore_folder_default(config, before)
    assert _read(config) == text


def test_switching_on_twice_does_not_lose_the_way_back(tmp_path):
    config = str(tmp_path / "config")
    _write(config, ORIGINAL)
    first = L.set_folder_default(config)
    again = L.set_folder_default(config)
    assert first == again == "org.gnome.Nautilus.desktop;"


def test_a_choice_the_user_made_since_is_not_undone(tmp_path):
    config = str(tmp_path / "config")
    _write(config, ORIGINAL)
    before = L.set_folder_default(config)
    _write(config, ORIGINAL.replace("org.gnome.Nautilus", "org.kde.dolphin"))   # the user picked Dolphin in the system settings
    assert not L.restore_folder_default(config, before)
    assert "inode/directory=org.kde.dolphin.desktop;" in _read(config)


def test_set_key_drops_a_repeated_line_of_the_same_key():
    text = "[Default Applications]" + chr(10) + "a/b=1;" + chr(10) + "c/d=2;" + chr(10) + "a/b=3;" + chr(10)
    assert L.set_key(text, L.DEFAULT_GROUP, "a/b", "9;") == "[Default Applications]" + chr(10) + "a/b=9;" + chr(10) + "c/d=2;" + chr(10)


def test_no_temporary_file_is_left_beside_mimeapps_list(tmp_path):
    config = str(tmp_path / "config")
    L.set_folder_default(config)
    assert os.listdir(config) == ["mimeapps.list"]


# the command line ----------------------------------------------------------------------------------------------------------------
def test_a_launcher_passes_folders_and_files_and_addresses(tmp_path):
    a, b, c = tmp_path / "a b", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    note = b / "note.txt"
    note.write_text("x")
    from urllib.parse import quote
    uri = "file://" + quote(str(a).replace(os.sep, "/") if os.sep == "/" else "/" + str(a).replace(os.sep, "/"))
    assert L.folders_from_arguments([str(a), str(note)]) == [str(a), str(b)]                          # a file: its folder
    assert L.folders_from_arguments(["--flag", str(tmp_path / "gone"), str(c), str(b), str(a)]) == [str(c), str(b)]    # only two
    if os.sep == "/":
        assert L.folders_from_arguments([uri]) == [str(a)]
    assert L.folders_from_arguments([]) == []


# the window --------------------------------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from tests.test_gui_commander import pump, world, app  # noqa: E402,F401


def _homes(win, tmp_path):
    win.desktop_homes = (str(tmp_path / "share"), str(tmp_path / "config"))
    win.program_words = ["/opt/dossier/dossier"]
    win.desktop_names = ()
    return win.desktop_homes


def test_the_first_start_from_the_tarball_asks_once_and_adds_the_launcher(world):
    win, dialogs, _l, _r, tmp = world
    data, _config = _homes(win, tmp)
    win.linux_first_start(tarball=True, linux=True)
    pump(win, until=lambda: L.is_installed(data))
    assert len(dialogs.confirms) == 1 and dialogs.confirms[0][0] == "Application menu"
    assert L.is_installed(data)
    win.linux_first_start(tarball=True, linux=True)
    assert len(dialogs.confirms) == 1                                            # asked once


def test_a_no_is_remembered_and_nothing_is_written(world):
    win, dialogs, _l, _r, tmp = world
    data, _config = _homes(win, tmp)
    dialogs.confirm_answer = False
    win.linux_first_start(tarball=True, linux=True)
    win.linux_first_start(tarball=True, linux=True)
    assert len(dialogs.confirms) == 1 and not L.is_installed(data)
    win.linux_add_launcher()                                                     # Settings offers it again
    pump(win, until=lambda: L.is_installed(data))
    assert L.is_installed(data)


def test_not_asked_on_windows_or_from_source_or_the_mac(world):
    win, dialogs, _l, _r, tmp = world
    _homes(win, tmp)
    win.linux_first_start(tarball=True, linux=False)                              # Windows and the Mac
    win.linux_first_start(tarball=False, linux=True)                              # Linux, but run from source
    win.linux_first_start()                                                       # as main() calls it, on a PC that is not Linux
    from dossier.core.platform import IS_LINUX
    if not IS_LINUX:
        pump(win)
        assert dialogs.confirms == []
        assert win.settings.value("linux/launcher_offered") is None
    else:
        assert dialogs.confirms == []


def test_the_settings_entries_exist_only_on_linux(world):
    win, _d, _l, _r, tmp = world
    from PyQt6.QtWidgets import QMenu
    assert win.build_linux_desktop_menu(QMenu(), linux=False) is None
    parent = QMenu()
    menu = win.build_linux_desktop_menu(parent, linux=True)
    assert [a.text() for a in parent.actions()] == ["Linux Desktop"]
    assert [a.text() for a in menu.actions()] == ["Add Dossier to the Application Menu", "Open Folders with Dossier"]
    assert win.act_open_folders.isCheckable() and not win.act_open_folders.isChecked()      # off by default


def test_open_folders_with_dossier_switches_on_with_a_way_back(world):
    win, _d, _l, _r, tmp = world
    data, config = _homes(win, tmp)
    from PyQt6.QtWidgets import QMenu
    win.build_linux_desktop_menu(QMenu(), linux=True)
    os.makedirs(config)
    with open(L.mimeapps_path(config), "w", encoding="utf-8") as f:
        f.write("[Default Applications]" + chr(10) + "inode/directory=thunar.desktop;" + chr(10))
    win.act_open_folders.setChecked(True)
    pump(win, until=win.open_folders_with_dossier)
    assert L.is_installed(data) and L.is_folder_default(config) and win.open_folders_with_dossier()
    assert L.folder_default(config) == "dossier.desktop;thunar.desktop;"
    win.act_open_folders.setChecked(False)
    pump(win, until=lambda: not win.open_folders_with_dossier())
    assert L.folder_default(config) == "thunar.desktop;" and not win.open_folders_with_dossier()
    assert not win.act_open_folders.isChecked()


def test_the_desktops_own_file_is_changed_too_and_put_back_exactly(world):
    """Question 72A: gnome-mimeapps.list wins over mimeapps.list, so where it names a folder program it is changed as well, and
    switching off puts back exactly what was there. A desktop file that names nothing for folders is not created or touched."""
    win, _d, _l, _r, tmp = world
    _data, config = _homes(win, tmp)
    win.desktop_names = ("GNOME", "KDE")
    from PyQt6.QtWidgets import QMenu
    win.build_linux_desktop_menu(QMenu(), linux=True)
    os.makedirs(config)
    gnome = os.path.join(config, "gnome-mimeapps.list")
    kde = os.path.join(config, "kde-mimeapps.list")
    gnome_text = "[Default Applications]" + chr(10) + "inode/directory=org.gnome.Nautilus.desktop;" + chr(10)
    kde_text = "[Default Applications]" + chr(10) + "text/plain=kate.desktop;" + chr(10)
    for path, text in ((gnome, gnome_text), (kde, kde_text)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    win.act_open_folders.setChecked(True)
    pump(win, until=win.open_folders_with_dossier)
    with open(gnome, encoding="utf-8", newline="") as f:
        assert L.get_key(f.read(), L.DEFAULT_GROUP, L.FOLDER_TYPE) == "dossier.desktop;org.gnome.Nautilus.desktop;"
    with open(kde, encoding="utf-8", newline="") as f:
        assert f.read() == kde_text                                              # names no folder program: left alone
    win.act_open_folders.setChecked(False)
    pump(win, until=lambda: not win.open_folders_with_dossier())
    with open(gnome, encoding="utf-8", newline="") as f:
        assert f.read() == gnome_text
    assert not os.path.exists(L.mimeapps_path(config)) or L.folder_default(config) is None


def test_a_desktop_file_without_a_folder_key_or_already_dossier_is_not_written(tmp_path):
    config = str(tmp_path)
    assert L.set_desktop_folder_defaults(config, ("GNOME",)) == {}                  # no file: none created
    assert not os.path.exists(os.path.join(config, "gnome-mimeapps.list"))
    path = os.path.join(config, "gnome-mimeapps.list")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Default Applications]" + chr(10) + "inode/directory=dossier.desktop;" + chr(10))
    assert L.set_desktop_folder_defaults(config, ("GNOME",)) == {}
    assert L.restore_desktop_folder_defaults({path: "pcmanfm.desktop;"}) == 1
    assert L.folder_default_value("x") == "x;"
