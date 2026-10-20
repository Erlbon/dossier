"""The tools bar: programs and folders of programs, started on the marked items."""
import os

import pytest

from dossier.core import tools as T

SEP = os.sep


# the arguments ------------------------------------------------------------------------------------------------------
def test_words_are_cut_at_spaces_and_quotes_keep_a_space_together():
    assert T.split_words('--open "a b" c') == ["--open", "a b", "c"]
    assert T.split_words("") == [] and T.split_words('""') == [""] and T.split_words("  x   y ") == ["x", "y"]
    with pytest.raises(T.BadTool):
        T.split_words('"never closed')


def test_files_become_separate_arguments_and_one_value_stays_one_argument():
    files = ["C:" + SEP + "my docs" + SEP + "a b.txt", "C:" + SEP + "c.txt"]
    out = T.expand('--in {files} --one={file} "{dir}" {name}', files, "C:" + SEP + "work dir", "D:" + SEP + "other")
    assert out == ["--in", files[0], files[1], "--one=" + files[0], "C:" + SEP + "work dir", "a b.txt"]


def test_a_name_with_quotes_or_spaces_can_never_become_a_second_argument():
    nasty = "C:" + SEP + 'x" --evil "y.txt'
    out = T.expand("{files} {file}", [nasty], "", "")
    assert out == [nasty, nasty]


def test_nothing_selected_gives_empty_values_not_an_error():
    assert T.expand("{files} {file} {name} x", [], "C:" + SEP, "") == ["", "", "x"]       # {files} adds nothing; the others are empty
    assert T.expand("{files} x", [], "", "") == ["x"]


def test_bad_arguments_are_refused_with_a_reason():
    with pytest.raises(T.BadTool, match="stand alone"):
        T.check_args("--in={files}")
    with pytest.raises(T.BadTool, match="unknown placeholder"):
        T.check_args("{filez}")
    T.check_args('--in {files} "{dir}" {other} {name} {file}')


def test_launch_hands_the_program_the_expanded_arguments_and_the_folder():
    seen = []
    argv = T.launch(T.Tool("x", "prog.exe", "--f {files}"), ["a", "b"], "C:" + SEP, "D:" + SEP,
                    starter=lambda command, args, cwd: seen.append((command, args, cwd)))
    assert argv == ["--f", "a", "b"] and seen[0][0] == "prog.exe" and seen[0][1] == ["--f", "a", "b"]
    seen.clear()
    T.launch(T.Tool("x", "prog.exe", "", "E:" + SEP + "here"), [], "C:" + SEP, "", starter=lambda c, a, d: seen.append(d))
    assert seen == ["E:" + SEP + "here"]                                 # the tool's own start folder wins


# the list ------------------------------------------------------------------------------------------------------------
def sample():
    return [T.Tool("7-Zip", "C:/7z/7zFM.exe", ""), T.Separator(),
            T.Folder("Windows", [T.Tool("Locksmith", "C:/pt/lock.exe", "{files}"), T.Folder("Deep", [T.Tool("Calc", "calc.exe")])])]


def test_the_list_round_trips_through_json_and_damage_is_left_out_not_raised():
    back = T.loads(T.dumps(sample()))
    assert [type(i).__name__ for i in back] == ["Tool", "Separator", "Folder"]
    assert back[2].items[0].args == "{files}" and back[2].items[1].items[0].name == "Calc"
    assert T.loads("not json") == [] and T.loads("") == [] and T.loads('{"a": 1}') == []
    assert T.from_data([{"type": "tool", "name": "", "command": "x"}, {"type": "tool", "name": "ok"}, 5, {"type": "folder"}]) == []


def test_folders_nest_only_so_deep_and_only_so_many_items_are_read():
    deep = []
    cur = deep
    for i in range(10):
        f = {"type": "folder", "name": f"f{i}", "items": []}
        cur.append(f)
        cur = f["items"]
    depth = 0
    node = T.from_data(deep)
    while node and isinstance(node[0], T.Folder) and node[0].items:
        node = node[0].items
        depth += 1
    assert depth <= T.MAX_DEPTH
    many = [{"type": "separator"}] * (T.MAX_ITEMS + 50)
    assert len(T.from_data(many)) == T.MAX_ITEMS


def test_places_lists_the_bar_and_every_folder_for_choosing_where_a_new_tool_goes():
    labels = [label for label, _lst in T.places(sample())]
    assert labels == ["(the bar itself)", "Windows", "Windows / Deep"]


def test_suggestions_only_offer_what_is_installed():
    found = T.suggestions(exists=lambda p: p.endswith("notepad.exe") or "PowerToys" in p)
    names = [t.name for t in found]
    assert "Notepad" in names and any("Locksmith" in n for n in names) and "Calculator" not in names


# the bar in the window --------------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QMimeData, QPointF, QUrl, Qt  # noqa: E402
from PyQt6.QtGui import QDropEvent  # noqa: E402

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


@pytest.fixture
def started(world):
    win, d, left, right, tmp = world
    win.started = []
    win.tool_starter = lambda command, args, cwd: win.started.append((command, args, cwd))
    return win, d, left, right, tmp


def test_the_bar_sits_between_the_menu_bar_and_the_panels(world):
    win, *_ = world
    box = win.centralWidget().layout()
    assert box.itemAt(0).widget() is win.tools_bar and box.itemAt(1).widget() is win.split


def test_an_empty_bar_says_how_to_fill_it_and_a_full_one_shows_buttons_and_folder_menus(world):
    win, *_ = world
    assert "Your programs go here" in win.tools_bar.buttons[0].text() and win.tools_bar.add_button.text() == "+"
    win.set_tools(sample())
    names = [b.text() for b in win.tools_bar.buttons if hasattr(b, "text")]
    assert names[0] == "7-Zip" and "Windows" in names
    folder = win.tools_bar.buttons[2]
    assert [a.text() for a in folder.menu().actions() if not a.isSeparator()] == ["Locksmith", "Deep"]
    assert folder.menu().actions()[1].menu().actions()[0].text() == "Calc"


def test_a_tool_is_started_on_the_marked_items_or_the_one_under_the_cursor(started):
    win, d, left, *_ = started
    for n in ("a.txt", "b.txt"):
        (left / n).write_text(n)
    win.left.refresh()
    pump(win, lambda: win.left.model.entry_count() >= 3)
    win.set_tools([T.Tool("Lock", "lock.exe", "{files}")])
    win.selection.add([str(left / "a.txt"), str(left / "b.txt")])
    win.tools_bar.buttons[0].click()
    assert sorted(win.started[-1][1]) == sorted([str(left / "a.txt"), str(left / "b.txt")]) and win.started[-1][2] == str(left)
    win.selection.clear()
    win.left.table.setCurrentIndex(win.left.model.index(win.left.model.row_of("b.txt"), 0))
    win.tools_bar.buttons[0].click()
    assert win.started[-1][1] == [str(left / "b.txt")]
    assert "Started Lock" in win.status.text()


def test_a_tool_uses_the_other_panel_and_works_on_the_home_page_without_files(started):
    win, d, left, right, tmp = started
    win.set_tools([T.Tool("T", "t.exe", '{dir} {other} {files}')])
    win.tools_bar.buttons[0].click()
    assert win.started[-1][1][:2] == [str(left), str(right)]
    win.left.set_folder("home://")
    pump(win, lambda: win.left.is_home)
    win.tools_bar.buttons[0].click()
    assert win.started[-1][1] == ["", str(right)]


def test_a_program_that_cannot_start_is_explained(world):
    win, d, *_ = world
    def boom(command, args, cwd):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    win.tool_starter = boom
    win.set_tools([T.Tool("Ghost", "nowhere.exe")])
    win.tools_bar.buttons[0].click()
    assert d.infos and "Ghost" in d.infos[-1][0] and "nowhere.exe" in d.infos[-1][1]
    win.set_tools([T.Tool("Bad", "x.exe", "{files")])
    win.tools_bar.buttons[0].click()
    assert "cannot run" in d.infos[-1][1]


def test_the_list_is_kept_in_the_settings_and_comes_back_in_a_new_window(world):
    win, d, left, right, tmp = world
    win.set_tools(sample())
    from dossier.gui.main_window import MainWindow
    again = MainWindow(settings_path=str(tmp / "s.ini"), start=(str(left), str(right)), dialogs=d)
    try:
        assert [i.name for i in again.tools if hasattr(i, "name") and i.name] == ["7-Zip", "Windows"]
        assert again.tools[2].items[1].items[0].name == "Calc"
    finally:
        again.close()


def test_add_a_program_at_the_top_or_into_a_folder_with_the_dialog(world, monkeypatch):
    win, d, *_ = world
    win.set_tools([T.Folder("Windows")])

    def fake(self, dlg):
        dlg.name.setText("Locksmith")
        dlg.command.setText('"C:\\pt\\lock.exe"')
        dlg.args.setText("{files}")
        dlg.where.setCurrentIndex(1)                                       # the folder
        return True
    monkeypatch.setattr(type(win), "_ask_tool", fake)
    win._add_program_dialog(None, [])
    folder = win.tools[0]
    assert folder.items[0].name == "Locksmith" and folder.items[0].command == "C:\\pt\\lock.exe" and folder.items[0].args == "{files}"


def test_a_bad_entry_keeps_the_dialog_open_with_the_reason(world, app):
    from dossier.gui.tools_bar import ToolDialog
    win, *_ = world
    dlg = ToolDialog(win)
    dlg.name.setText("x")
    dlg._accept()
    assert "say which program" in dlg.problem.text() and dlg.result() == 0
    dlg.command.setText("p.exe")
    dlg.args.setText("--in={files}")
    dlg._accept()
    assert "stand alone" in dlg.problem.text() and dlg.result() == 0
    dlg.args.setText("--in {files}")
    dlg._accept()
    assert dlg.result() == 1 and dlg.tool().args == "--in {files}"


def test_edit_remove_and_move_from_the_bars_menu(world, monkeypatch):
    win, d, *_ = world
    win.set_tools([T.Tool("A", "a.exe"), T.Tool("B", "b.exe"), T.Folder("F", [T.Tool("C", "c.exe")])])

    def fake(self, dlg):
        dlg.name.setText("A2")
        return True
    monkeypatch.setattr(type(win), "_ask_tool", fake)
    win.edit_tool_at((0,))
    assert win.tools[0].name == "A2" and win.tools[0].command == "a.exe"
    win.move_tool(0, 1)
    assert [i.name for i in win.tools] == ["B", "A2", "F"]
    win.remove_tool_at((1,))
    assert [i.name for i in win.tools] == ["B", "F"]
    d.confirm_answer = False
    win.remove_tool_at((1,))
    assert [i.name for i in win.tools] == ["B", "F"]                       # a folder with things in it asks first
    d.confirm_answer = True
    win.remove_tool_at((1,))
    assert [i.name for i in win.tools] == ["B"]


def test_the_menu_of_the_bar_offers_what_fits_where_it_was_opened(world):
    win, *_ = world
    win.set_tools([T.Tool("A", "a.exe"), T.Tool("B", "b.exe")])
    on_empty = [a.text() for a in win.build_tools_menu(()).actions() if not a.isSeparator()]
    assert on_empty == ["Add Program...", "Add Folder...", "Add Separator", "Manage Tools...", "Hide the Tools Bar"]
    on_button = [a.text() for a in win.build_tools_menu((0,)).actions() if not a.isSeparator()]
    assert on_button[:4] == ["Edit...", "Remove", "Move Left", "Move Right"]
    assert not win.build_tools_menu((0,)).actions()[2].isEnabled() and win.build_tools_menu((0,)).actions()[3].isEnabled()


def test_manage_tools_reorders_and_moves_items_into_folders(world, monkeypatch):
    win, d, *_ = world
    win.set_tools([T.Tool("A", "a.exe"), T.Folder("F"), T.Tool("B", "b.exe")])

    def fake(self, dlg):
        tree = dlg.tree
        root = tree.invisibleRootItem()
        b = root.takeChild(2)
        root.child(1).addChild(b)                                          # B into the folder
        a = root.takeChild(0)
        root.insertChild(1, a)                                            # and A after the folder
        return True
    monkeypatch.setattr(type(win), "_ask_manage", fake)
    win.manage_tools()
    assert [i.name for i in win.tools] == ["F", "A"] and win.tools[0].items[0].name == "B"


def test_a_program_file_dropped_on_the_bar_offers_to_add_it_and_other_files_are_ignored(world, monkeypatch, tmp_path):
    win, d, *_ = world
    asked = []
    monkeypatch.setattr(type(win), "_ask_tool", lambda self, dlg: (asked.append((dlg.name.text(), dlg.command.text())), False)[1])
    prog, text = tmp_path / "Tool One.exe", tmp_path / "notes.txt"
    prog.write_bytes(b"x")
    text.write_text("x")

    def drop(path):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win.tools_bar.dropEvent(event)
        return event.isAccepted()
    assert drop(prog) and asked == [("Tool One", str(prog))]
    assert not drop(text) and len(asked) == 1


def test_the_bar_can_be_hidden_and_shown_again_and_it_is_remembered(world):
    win, *_ = world
    assert win.tools_bar.isVisibleTo(win) and win.act_tools_bar.isChecked()
    win.act_tools_bar.setChecked(False)
    assert not win.tools_bar.isVisibleTo(win) and str(win.settings.value("view/tools_bar")) == "false"
    win.act_tools_bar.setChecked(True)
    assert win.tools_bar.isVisibleTo(win)


def test_the_plus_button_opens_the_same_menu_as_a_right_click_and_the_bar_has_its_own_background(world, monkeypatch):
    win, *_ = world
    shown = []
    monkeypatch.setattr(type(win), "_popup_menu", lambda self, menu, pos: shown.append([a.text() for a in menu.actions() if not a.isSeparator()]))
    win.tools_bar.add_button.click()
    assert shown and shown[0][:2] == ["Add Program...", "Add Folder..."]
    sheet = win.tools_bar.styleSheet()
    assert "#toolsbar" in sheet and "border-bottom" in sheet and win.tools_bar.minimumHeight() >= 30
    win.set_tools([T.Tool("A", "a.exe")])
    assert win.tools_bar.add_button.text() == "+"                          # still there with programs on the bar
