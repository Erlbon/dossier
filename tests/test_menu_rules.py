"""The rules that keep the menus from drifting (menu review 2026-11-05; CLAUDE.md, "Menus").

A new command that breaks one of these goes into a submenu, takes the label of its menu-bar command, or is named here with the reason.
"""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

from dossier.gui.menus import command_keys, command_label  # noqa: E402

HEADINGS = ["File", "Edit", "Mark", "View", "Go", "Tools", "Network", "Settings", "Help"]
MAX_ENTRIES = 15          # File has 15; one more and a group of it becomes a submenu
# right-click labels that say the same command better for the thing clicked on
CONTEXT_LABELS = {"Open in the Other Panel", "Compare with the Other Panel...", "Properties of This Folder"}
# submenus that list what the owner saved: one saved item is one entry
SAVED_LISTS = {"Restore", "Add to Marks", "Forget", "Open Tab Set", "Add Tab Set", "Forget Tab Set"}
# window shortcuts that are in no menu on purpose
NOT_IN_A_MENU = set()


def visible(menu):
    return [a for a in menu.actions() if a.isVisible()]


def every_menu(win):
    todo = [a.menu() for a in win.menuBar().actions()]
    while todo:
        menu = todo.pop()
        menu.aboutToShow.emit()                               # the menus that fill themselves when opened
        yield menu
        todo += [a.menu() for a in menu.actions() if a.menu() is not None]


def path_of(menu):
    return menu.title().replace("&", "")


def test_the_headings(world):
    win, *_ = world
    assert [a.text().replace("&", "") for a in win.menuBar().actions()] == HEADINGS


def test_no_menu_is_too_long_and_no_submenu_holds_one_entry(world):
    win, *_ = world
    for menu in every_menu(win):
        entries = [a for a in visible(menu) if not a.isSeparator()]
        assert len(entries) <= MAX_ENTRIES, f"{path_of(menu)} has {len(entries)} entries: group some into a submenu"
        if menu not in [a.menu() for a in win.menuBar().actions()] and path_of(menu) not in SAVED_LISTS:
            assert len(entries) != 1, f"the submenu {path_of(menu)} holds one entry: put it in its parent"


def test_separators_only_between_groups(world):
    win, *_ = world
    for sharing_on in (False, True):
        win.set_sharing_allowed(sharing_on)
        for menu in every_menu(win):
            seps = [a.isSeparator() for a in visible(menu)]
            if not seps:
                continue
            where = path_of(menu)
            assert not seps[0] and not seps[-1], f"{where} starts or ends with a separator"
            assert not any(a and b for a, b in zip(seps, seps[1:])), f"{where} has two separators in a row"
    win.set_sharing_allowed(False)


def test_no_grey_sentences_in_the_menus(world):
    """An explanation is a tooltip: a greyed line (an entry the menu owns, not a command of the window) looks like a command that cannot
    run. A live state (Client for NFS: ...) and an empty list (Nothing saved yet) are allowed."""
    win, *_ = world
    for menu in every_menu(win):
        for a in visible(menu):
            if not a.isSeparator() and not a.isEnabled() and a.menu() is None and a.parent() is menu:
                assert a.text() == "Nothing saved yet" or a.text().startswith("Client for NFS:"), f"{path_of(menu)}: grey line {a.text()!r}"


def test_every_window_shortcut_is_in_a_menu(world):
    win, *_ = world
    in_menus = {id(a) for menu in every_menu(win) for a in menu.actions()}
    missing = sorted(command_label(a) for a in win.actions()
                     if a.shortcuts() and id(a) not in in_menus and command_label(a) not in NOT_IN_A_MENU)
    assert missing == [], f"shortcuts in no menu (only Keyboard Shortcuts would show them): {missing}"


def right_click_menus(win, folder):
    """The right-click menus of a file, a folder, an archive and empty space, and their submenus."""
    (folder / "a.txt").write_text("a")
    (folder / "sub").mkdir()
    with zipfile.ZipFile(folder / "b.7z.zip", "w") as z:
        z.writestr("x.txt", "x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    menus = [win.build_context_menu(win.left, win.left.model.row_of(n)) for n in ("a.txt", "sub", "b.7z.zip")]
    menus.append(win.build_context_menu(win.left, -1))
    out = []
    while menus:
        m = menus.pop()
        out.append(m)
        menus += [a.menu() for a in m.actions() if a.menu() is not None]
    return out


def test_right_click_says_what_the_menu_bar_says(world):
    """A right-click entry that runs a menu-bar command has its label (or one of CONTEXT_LABELS) and exactly its keys."""
    win, _d, left, *_ = world
    labels = {}
    for menu in every_menu(win):
        for a in menu.actions():
            if not a.isSeparator() and a.menu() is None:
                labels.setdefault(command_label(a), []).append(a)
    checked = 0
    for menu in right_click_menus(win, left):
        for a in menu.actions():
            if a.isSeparator() or a.menu() is not None:
                continue
            label, _, keys = a.text().partition("\t")
            if label in CONTEXT_LABELS:
                continue
            for bar in labels.get(label, []):
                assert keys == command_keys(bar), f"right-click {label!r} shows {keys!r}, the menu bar has {command_keys(bar)!r}"
                checked += 1
    assert checked >= 20


def test_the_right_click_hint_follows_a_changed_function_key(world):
    win, _d, left, *_ = world
    (left / "a.txt").write_text("a")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 2)
    def hint():
        menu = win.build_context_menu(win.left, win.left.model.row_of("a.txt"))
        return next(a for a in menu.actions() if a.text().startswith("Change Dates and Attributes...")).text().partition("\t")[2]
    assert hint() == "Shift+F2"
    win._fkey_table = {layer: {n: c for n, c in keys.items() if c != "change_dates"} for layer, keys in win._fkey_table.items()}
    win._fkey_table.setdefault("ctrl", {})[2] = "change_dates"
    win.apply_fkey_shortcuts()
    assert hint() == "Ctrl+F2"


def test_claude_md_names_the_question_of_every_menu():
    text = open(os.path.join(os.path.dirname(__file__), "..", "CLAUDE.md"), encoding="utf-8").read()
    section = text.split("## Menus", 1)[1].split("\n## ", 1)[0]
    for heading in HEADINGS:
        assert f"**{heading}**" in section, heading
