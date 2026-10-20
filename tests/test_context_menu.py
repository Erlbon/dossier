"""The right-click menu: what it offers, and that it acts on the right items."""
import os
import zipfile

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QContextMenuEvent  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def texts(menu):
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


def find(menu, text):
    return next(a for a in menu.actions() if a.text().split("\t")[0] == text)


def row_of(win, name):
    return win.left.model.row_of(name)


def filled(win, left, names=("a.txt", "b.txt", "c.txt")):
    for n in names:
        (left / n).write_text(n)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= len(names) + 1)


def test_a_file_gets_the_file_commands(world):
    win, d, left, *_ = world
    filled(win, left)
    menu = win.build_context_menu(win.left, row_of(win, "a.txt"))
    t = texts(menu)
    assert t[:3] == ["Open", "View", "Edit"] and "Rename" in t and "Delete" in t and "Properties" in t
    assert "Open in a New Tab" not in t and "Unpack..." not in t
    assert "Pack to Zip..." in t and "Copy to the Other Panel" in t and "Copy the Path as Text" in t


def test_a_folder_gets_the_folder_commands(world):
    win, d, left, *_ = world
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: row_of(win, "box") >= 0)
    t = texts(win.build_context_menu(win.left, row_of(win, "box")))
    assert "Open in a New Tab" in t and "Open in the Other Panel" in t and "View" not in t and "Edit" not in t


def test_archives_get_unpack_and_other_than_zip_also_convert(world):
    win, d, left, *_ = world
    for n in ("a.zip", "b.7z", "c.txt"):
        (left / n).write_bytes(b"x")
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 4)
    zipmenu = texts(win.build_context_menu(win.left, row_of(win, "a.zip")))
    sevenmenu = texts(win.build_context_menu(win.left, row_of(win, "b.7z")))
    assert "Unpack..." in zipmenu and "Convert Archive to Zip" not in zipmenu
    assert "Unpack..." in sevenmenu and "Convert Archive to Zip" in sevenmenu
    assert "Unpack..." not in texts(win.build_context_menu(win.left, row_of(win, "c.txt")))


def test_empty_space_gets_the_folder_commands(world):
    win, d, left, *_ = world
    t = texts(win.build_context_menu(win.left, -1))
    assert t[:3] == ["New Folder", "Paste", "Select All"] and "Terminal Here" in t and "Refresh" in t
    assert "Properties of This Folder" in t and "All Files Below This Folder" in t and "Search..." in t


def test_the_up_row_gets_the_folder_menu_not_an_item_menu(world):
    win, d, left, *_ = world
    filled(win, left)
    assert "New Folder" in texts(win.build_context_menu(win.left, 0))


def test_several_marked_items_disable_what_needs_one(world):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    menu = win.build_context_menu(win.left, row_of(win, "a.txt"))
    assert not find(menu, "Rename").isEnabled() and not find(menu, "View").isEnabled()
    assert find(menu, "Delete").isEnabled() and find(menu, "Pack to Zip...").isEnabled()


def test_right_clicking_an_unmarked_item_acts_on_that_item_alone_and_keeps_the_marks(world):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    seen = []
    win.pack_to_zip = lambda: seen.append(list(win.active.targets()))          # before the menu is built: it keeps the method it saw
    menu = win.build_context_menu(win.left, row_of(win, "c.txt"))
    find(menu, "Pack to Zip...").trigger()
    assert seen == [[str(left / "c.txt")]]
    assert sorted(os.path.basename(p) for p in win.left.marked_here()) == ["a.txt", "b.txt"]       # untouched
    assert win.active.target_override is None                                                    # and back to normal


def test_right_clicking_a_marked_item_acts_on_all_the_marked_ones(world):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    seen = []
    win.pack_to_zip = lambda: seen.append(sorted(os.path.basename(p) for p in win.active.targets()))
    menu = win.build_context_menu(win.left, row_of(win, "b.txt"))
    find(menu, "Pack to Zip...").trigger()
    assert seen == [["a.txt", "b.txt"]]


def test_delete_from_the_menu_deletes_only_what_was_clicked(world):
    win, d, left, *_ = world
    filled(win, left)
    win.selection.add([str(left / "a.txt")])
    find(win.build_context_menu(win.left, row_of(win, "c.txt")), "Delete").trigger()
    pump(win, lambda: d.confirms)
    assert "c.txt" in d.confirms[-1][1] and "a.txt" not in d.confirms[-1][1]


def test_the_menu_opens_from_a_real_right_click_and_from_the_menu_key(world, monkeypatch):
    win, d, left, *_ = world
    filled(win, left)
    shown = []
    monkeypatch.setattr(type(win), "_popup_menu", lambda self, menu, pos: shown.append((texts(menu), pos)))
    view = win.left.table.viewport()
    spot = win.left.table.visualRect(win.left.model.index(row_of(win, "b.txt"), 0)).center()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, spot, view.mapToGlobal(spot))
    win.left.table.contextMenuEvent(event)
    assert shown and "Rename" in shown[-1][0] and win.left.current_name() == "b.txt"
    key = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(5, 5))
    win.left.table.setCurrentIndex(win.left.model.index(row_of(win, "c.txt"), 0))
    win.left.table.contextMenuEvent(key)
    assert len(shown) == 2 and "Rename" in shown[-1][0]


def test_the_home_page_gets_its_own_short_menus(world):
    win, d, left, *_ = world
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home and win.left.model.entry_count() > 3)
    m = win.left.model
    drive = next(r for r in range(m.entry_count()) if m.entry_at(r).kind in ("fixed", "other", "removable"))
    t = texts(win.build_context_menu(win.left, drive))
    assert t == ["Open", "Open in a New Tab"]
    action = next(r for r in range(m.entry_count()) if m.entry_at(r).kind == "action")
    assert texts(win.build_context_menu(win.left, action)) == ["Add a network share"]
    header = next(r for r in range(m.entry_count()) if m.entry_at(r).kind == "header")
    assert texts(win.build_context_menu(win.left, header)) == ["Add a Network Share..."]


def test_a_pinned_folder_can_be_removed_from_the_menu(world):
    win, d, left, *_ = world
    win.save_network_location("\\\\nas\\media") if False else None
    win._save_list("home/pins", [str(left)])
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home and any(win.left.model.entry_at(r).kind == "pin" for r in range(win.left.model.entry_count())))
    m = win.left.model
    pin = next(r for r in range(m.entry_count()) if m.entry_at(r).kind == "pin")
    menu = win.build_context_menu(win.left, pin)
    assert "Remove from the Home Page" in texts(menu)
    find(menu, "Remove from the Home Page").trigger()
    pump(win, lambda: d.confirms)


def test_inside_an_open_zip_the_item_menu_still_works(world):
    from dossier.core.zipfs import archive_root
    win, d, left, *_ = world
    z = left / "a.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("in.txt", "I")
    win.left.set_folder(archive_root(str(z)))
    pump(win, lambda: win.left.path.startswith("zip://") and win.left.model.entry_count() >= 2)
    t = texts(win.build_context_menu(win.left, row_of(win, "in.txt")))
    assert "Copy to the Other Panel" in t and "Delete" in t


# Batch Rename, Terminal Here and Pin on the menu ---------------------------------------------------------------------------
def submenu(menu, text):
    return next(a for a in menu.actions() if a.text() == text).menu()


def test_the_item_menu_has_batch_rename_and_a_folder_has_terminal_and_pin(world):
    win, d, left, *_ = world
    filled(win, left, ("a.txt",))
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: row_of(win, "box") >= 0)
    file_menu = win.build_context_menu(win.left, row_of(win, "a.txt"))
    assert [a.text().split("\t")[0] for a in submenu(file_menu, "Batch Rename").actions()] == [
        "By Pattern...", "Search and Replace in Names...", "Change Case...", "Number the Files..."]
    assert "Terminal Here" not in texts(file_menu) and "Pin to the Home Page" not in texts(file_menu)
    folder_menu = win.build_context_menu(win.left, row_of(win, "box"))
    assert "Terminal Here" in texts(folder_menu) and "Pin to the Home Page" in texts(folder_menu)


def test_terminal_here_opens_in_the_folder_that_was_clicked_not_the_one_shown(world):
    win, d, left, *_ = world
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: row_of(win, "box") >= 0)
    seen = []
    win.open_terminal = lambda admin=False, profile=None, folder="": seen.append(folder)
    find(win.build_context_menu(win.left, row_of(win, "box")), "Terminal Here").trigger()
    assert seen == [str(left / "box")]


def test_pin_from_the_menu_pins_the_clicked_folder(world):
    win, d, left, *_ = world
    (left / "box").mkdir()
    win.left.refresh()
    pump(win, lambda: row_of(win, "box") >= 0)
    find(win.build_context_menu(win.left, row_of(win, "box")), "Pin to the Home Page").trigger()
    assert win._saved_list("home/pins") == [str(left / "box")]


def test_batch_rename_from_the_menu_works_on_the_clicked_item_even_when_nothing_is_marked(world):
    win, d, left, *_ = world
    filled(win, left, ("a.txt", "b.txt"))
    win.selection.add([str(left / "a.txt")])
    seen = []
    win.rename_by_pattern = lambda: seen.append([e.name for e in win._entries_to_rename()])
    menu = win.build_context_menu(win.left, row_of(win, "b.txt"))
    find_sub = submenu(menu, "Batch Rename")
    next(a for a in find_sub.actions() if a.text().startswith("By Pattern")).trigger()
    assert seen == [["b.txt"]]                                          # the clicked item, not the marked a.txt


# the Windows menu at the bottom -----------------------------------------------------------------------------------------------
WIN_ENTRY = "More Options (Windows Menu)..."


@pytest.mark.skipif(os.name != "nt", reason="the Windows shell menu")
def test_the_windows_menu_is_the_last_entry_of_item_and_empty_space_menus(world):
    win, d, left, *_ = world
    filled(win, left)
    t = texts(win.build_context_menu(win.left, row_of(win, "a.txt")))
    assert t[-1] == WIN_ENTRY and t[-2] == "Properties"
    assert texts(win.build_context_menu(win.left, -1))[-1] == WIN_ENTRY


def test_it_is_not_offered_for_archives_search_results_or_the_home_page(world, monkeypatch):
    win, d, left, *_ = world
    filled(win, left)
    monkeypatch.setattr("dossier.core.shellmenu.IS_WINDOWS", False)
    assert WIN_ENTRY not in texts(win.build_context_menu(win.left, row_of(win, "a.txt")))
    assert WIN_ENTRY not in texts(win.build_context_menu(win.left, -1))
    monkeypatch.undo()
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    assert WIN_ENTRY not in texts(win.build_context_menu(win.left, -1))


@pytest.mark.skipif(os.name != "nt", reason="the Windows shell menu")
def test_choosing_it_starts_the_shell_menu_on_those_items_and_our_own_verbs_run_here(world, monkeypatch):
    win, d, left, right, tmp = world
    filled(win, left)
    started = []

    def fake(self, paths, x, y, on_done, background, extended):
        started.append((paths, background))
        from dossier.core.shellmenu import Outcome
        on_done(Outcome(verb=started_verb[0]))
    started_verb = ["copy"]
    monkeypatch.setattr(type(win), "_start_shell_menu", fake)
    menu = win.build_context_menu(win.left, row_of(win, "b.txt"))
    find(menu, WIN_ENTRY).trigger()
    pump(win)
    assert started == [([str(left / "b.txt")], False)]
    from dossier.gui import file_clipboard
    assert file_clipboard.get()[0] == [str(left / "b.txt")]                 # Copy ran as Dossier's own command, on that item
    started_verb[0] = "delete"
    find(win.build_context_menu(win.left, row_of(win, "c.txt")), WIN_ENTRY).trigger()
    pump(win, lambda: d.confirms)
    assert "c.txt" in d.confirms[-1][1]                                      # our own delete confirmation, not the shell's


@pytest.mark.skipif(os.name != "nt", reason="the Windows shell menu")
def test_what_the_shell_ran_refreshes_the_lists_and_errors_are_said(world, monkeypatch):
    win, d, left, right, tmp = world
    filled(win, left)
    from dossier.core.shellmenu import Outcome
    answers = [Outcome(ran=True), Outcome(error="The Windows menu failed: boom"), Outcome()]
    monkeypatch.setattr(type(win), "_start_shell_menu", lambda self, p, x, y, done, bg, ext: done(answers.pop(0)))
    (left / "new-from-shell.txt").write_text("n")                           # what a shell command may have created
    find(win.build_context_menu(win.left, -1), WIN_ENTRY).trigger()
    pump(win, lambda: win.left.model.row_of("new-from-shell.txt") >= 0)
    find(win.build_context_menu(win.left, -1), WIN_ENTRY).trigger()
    pump(win, lambda: "boom" in win.status.text())
    find(win.build_context_menu(win.left, -1), WIN_ENTRY).trigger()
    pump(win)
