"""Folder rules in the window (card 68A): the hint when a folder is opened, Tools > Rules > Run Rules, the plan before anything moves, and
the rules dialog."""
from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog  # noqa: E402

from dossier.core.folder_rules import FolderRule  # noqa: E402
from dossier.gui.folder_rules import RULES_KEY  # noqa: E402
from dossier.gui.folder_rules_dialog import FolderRulesDialog, RuleForm  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

OLD = time.mktime((2024, 3, 10, 12, 0, 0, 0, 0, -1))


def _downloads(tmp_path):
    folder = tmp_path / "left" / "Downloads"
    folder.mkdir()
    for name, when in (("a.pdf", OLD), ("b.pdf", OLD), ("keep.txt", OLD), ("new.pdf", time.time())):
        (folder / name).write_text(name)
        os.utime(folder / name, (when, when))
    return folder


def _rules():
    return [FolderRule("*.pdf", "move", "Archive/<year>", older_days=30)]


def _accept(window):
    seen = []

    def show(dialog):
        seen.append(dialog)
        dialog.accept()

    window._show_rules_preview = show
    return seen


def test_opening_a_folder_with_matching_rules_shows_a_hint_and_moves_nothing(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.rule_store().set_rules(str(folder), _rules())
    win.left.set_folder(str(folder))
    pump(win, lambda: not win.rules_label.isHidden())
    assert "move 2 items" in win.rules_label.text() and "Show the Plan" in win.rules_label.text()
    assert sorted(os.listdir(folder)) == ["a.pdf", "b.pdf", "keep.txt", "new.pdf"]      # nothing moved
    assert not dialogs.infos and not dialogs.confirms                                      # and no box opened


def test_a_folder_without_rules_or_without_a_match_shows_no_hint(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.left.set_folder(str(folder))
    pump(win)
    assert win.rules_label.isHidden()
    win.rule_store().set_rules(str(folder), [FolderRule("*.zip", "move", "Z")])
    win.left.set_folder(str(tmp / "left"))
    win.left.set_folder(str(folder))
    pump(win)
    assert win.rules_label.isHidden()
    win.left.set_folder(str(tmp / "left"))
    win.rule_store().set_rules(str(folder), _rules())
    win.left.set_folder(str(folder))
    pump(win, lambda: not win.rules_label.isHidden())
    win.left.set_folder(str(tmp / "left"))                                                  # leaving the folder takes the hint away
    pump(win, lambda: win.rules_label.isHidden())


def test_run_rules_shows_the_plan_and_nothing_moves_until_run(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.rule_store().set_rules(str(folder), _rules())
    win.left.set_folder(str(folder))
    pump(win)
    seen = []

    def cancel(dialog):                                  # the preview is looked at and closed: Run is not pressed
        seen.append(dialog.text.toPlainText())
        dialog.reject()

    win._show_rules_preview = cancel
    win.run_folder_rules()
    pump(win, lambda: bool(seen))
    assert "a.pdf" in seen[0] and "b.pdf" in seen[0] and "keep.txt" not in seen[0] and "new.pdf" not in seen[0]
    assert os.path.join("Archive", "2024") in seen[0]
    assert sorted(os.listdir(folder)) == ["a.pdf", "b.pdf", "keep.txt", "new.pdf"]


def test_pressing_run_moves_the_files_into_the_year_folder(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.rule_store().set_rules(str(folder), _rules())
    win.left.set_folder(str(folder))
    pump(win)
    seen = _accept(win)
    win.run_folder_rules()
    pump(win, lambda: bool(seen))
    pump(win)
    assert sorted(os.listdir(folder)) == ["Archive", "keep.txt", "new.pdf"]
    assert sorted(os.listdir(folder / "Archive" / "2024")) == ["a.pdf", "b.pdf"]


def test_a_delete_rule_goes_to_the_recycle_bin_after_run(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.rule_store().set_rules(str(folder), [FolderRule("*.txt", "delete")])
    win.left.set_folder(str(folder))
    pump(win)
    seen = _accept(win)
    win.run_folder_rules()
    pump(win, lambda: bool(seen))
    pump(win)
    assert "keep.txt" not in os.listdir(folder)
    assert any(n.endswith("keep.txt") for n in os.listdir(tmp / "bin"))


def test_run_rules_says_when_there_are_no_rules_or_nothing_matches(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.left.set_folder(str(folder))
    pump(win)
    win.run_folder_rules()
    assert "No rules for this folder" in win.status.text()
    win.rule_store().set_rules(str(folder), [FolderRule("*.zip", "move", "Z")])
    win.run_folder_rules()
    pump(win, lambda: "matches" in win.status.text())
    assert "Nothing in this folder matches its rules" in win.status.text()
    assert not dialogs.infos


def test_the_hint_link_opens_the_plan(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.rule_store().set_rules(str(folder), _rules())
    win.left.set_folder(str(folder))
    pump(win, lambda: not win.rules_label.isHidden())
    seen = []
    win._show_rules_preview = lambda d: (seen.append(d), d.reject())
    win.rules_label.linkActivated.emit("plan")
    pump(win, lambda: bool(seen))
    assert sorted(os.listdir(folder)) == ["a.pdf", "b.pdf", "keep.txt", "new.pdf"]


def test_folder_rules_dialog_saves_the_rules_in_the_settings_not_in_the_folder(world):
    win, dialogs, left, right, tmp = world
    folder = _downloads(tmp)
    win.left.set_folder(str(folder))
    pump(win)
    asked = []

    def ask(path, rules):
        asked.append((path, list(rules)))
        return _rules()

    win._ask_folder_rules = ask
    win.edit_folder_rules()
    assert asked == [(str(folder), [])]
    assert win.rule_store().rules_for(str(folder)) == _rules()
    assert RULES_KEY == "folder-rules/rules" and "Archive" in str(win.settings.value(RULES_KEY))
    assert sorted(os.listdir(folder)) == ["a.pdf", "b.pdf", "keep.txt", "new.pdf"]          # no file was added to the folder
    pump(win, lambda: not win.rules_label.isHidden())                                       # the new rules are checked at once
    win._ask_folder_rules = lambda path, rules: []                                          # all removed: the folder is forgotten
    win.edit_folder_rules()
    assert len(win.rule_store()) == 0 and win.settings.value(RULES_KEY) is None
    pump(win, lambda: win.rules_label.isHidden())
    win._ask_folder_rules = lambda path, rules: None                                        # cancelled: nothing changes
    win.rule_store().set_rules(str(folder), _rules())
    win.edit_folder_rules()
    assert len(win.rule_store().rules_for(str(folder))) == 1


def test_rules_belong_to_a_real_folder_not_the_home_page(world):
    win, dialogs, left, right, tmp = world
    win.left.set_folder("home://")
    win._ask_folder_rules = lambda path, rules: pytest.fail("no box on the Home page")
    win.edit_folder_rules()
    assert "folder" in win.status.text().lower()


def test_tools_menu_has_the_rules_submenu(world):
    win = world[0]
    tools = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Tools")
    rules = next(a.menu() for a in tools.actions() if a.text() == "Rules")
    assert [a.text() for a in rules.actions()] == ["Run Rules", "Folder Rules..."]


def test_the_rule_form_gives_back_the_rule_and_refuses_a_bad_one(app, tmp_path):
    form = RuleForm(None, None, str(tmp_path))
    form.patterns.setText("*.pdf")
    form.older.setValue(30)
    form.larger.setValue(2)
    form.dest.setText("Archive/<year>")
    rule = form.rule()
    assert (rule.patterns, rule.action, rule.dest, rule.older_days, rule.larger_than) == ("*.pdf", "move", "Archive/<year>", 30, 2 << 20)
    form.dest.setText("")
    form._accept()
    assert form.result() != QDialog.DialogCode.Accepted and "where" in form.error.text()
    form.action.setCurrentIndex(form.action.findData("delete"))
    assert not form.dest.isEnabled()
    form._accept()
    assert form.result() == QDialog.DialogCode.Accepted


def test_the_rules_dialog_adds_edits_removes_and_orders(app, tmp_path):
    dialog = FolderRulesDialog(None, str(tmp_path), [FolderRule("*.pdf", "move", "A")])
    answers = [FolderRule("*.tmp", "delete"), FolderRule("*.pdf", "copy", "B")]
    dialog._ask = lambda rule: answers.pop(0)
    dialog.add()
    assert [r.patterns for r in dialog.rules] == ["*.pdf", "*.tmp"]
    dialog.list.setCurrentRow(0)
    dialog.edit()
    assert dialog.rules[0].action == "copy"
    dialog.move(1)
    assert [r.patterns for r in dialog.rules] == ["*.tmp", "*.pdf"]
    assert dialog.list.count() == 2 and "delete" in dialog.list.item(0).text()
    dialog.remove()                                   # the moved rule stays selected, so it is the one that goes
    assert [r.patterns for r in dialog.rules] == ["*.tmp"]
