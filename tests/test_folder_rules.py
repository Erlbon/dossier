"""Folder rules (card 68A): matching a listing, destinations with <year> and <month>, the groups, and the JSON round trip."""
from __future__ import annotations

import json
import os
import time

from dossier.core import folder_rules as R
from dossier.core.vfs import Entry

DAY = 86400.0
NOW = time.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))


def _at(year, month, day=10):
    return time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))


def _file(folder, name, mtime, size=10, is_dir=False, is_link=False):
    return Entry(name, os.path.join(folder, name), is_dir, size, mtime, is_link)


def _folder(tmp_path):
    return str(tmp_path / "Downloads")


def test_a_pattern_alone_matches_by_name_and_proposes_a_move(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "a.pdf", NOW), _file(folder, "b.txt", NOW), _file(folder, "C.PDF", NOW)]
    found = R.proposals([R.FolderRule("*.pdf", "move", "Archive")], entries, folder, NOW)
    assert [p.name for p in found] == ["a.pdf", "C.PDF"]
    assert {p.dest for p in found} == {os.path.join(folder, "Archive")}


def test_older_than_days_uses_the_modification_time(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "old.pdf", NOW - 31 * DAY), _file(folder, "new.pdf", NOW - 29 * DAY), _file(folder, "edge.pdf", NOW - 30 * DAY)]
    found = R.proposals([R.FolderRule("*.pdf", "move", "Old", older_days=30)], entries, folder, NOW)
    assert [p.name for p in found] == ["old.pdf", "edge.pdf"]


def test_larger_than_needs_a_bigger_file_and_never_matches_a_folder(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "big.iso", NOW, size=5 << 20), _file(folder, "small.iso", NOW, size=1 << 20),
               _file(folder, "same.iso", NOW, size=2 << 20), _file(folder, "dir.iso", NOW, size=9 << 20, is_dir=True)]
    rule = R.FolderRule("*.iso;*.iso/", "delete", larger_than=2 << 20)
    assert [p.name for p in R.proposals([rule], entries, folder, NOW)] == ["big.iso"]


def test_the_destination_holds_the_year_and_month_of_each_file(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "a.pdf", _at(2024, 3)), _file(folder, "b.pdf", _at(2025, 12))]
    found = R.proposals([R.FolderRule("*.pdf", "move", "Archive/<year>/<month>")], entries, folder, NOW)
    assert [p.dest for p in found] == [os.path.join(folder, "Archive", "2024", "03"), os.path.join(folder, "Archive", "2025", "12")]


def test_a_complete_destination_is_not_put_below_the_folder(tmp_path):
    folder = _folder(tmp_path)
    elsewhere = str(tmp_path / "Elsewhere" / "<year>")
    found = R.proposals([R.FolderRule("*.pdf", "copy", elsewhere)], [_file(folder, "a.pdf", _at(2023, 1))], folder, NOW)
    assert found[0].dest == str(tmp_path / "Elsewhere" / "2023")


def test_the_first_matching_rule_wins_and_a_delete_has_no_destination(tmp_path):
    folder = _folder(tmp_path)
    rules = [R.FolderRule("*.tmp", "delete"), R.FolderRule("*", "move", "Rest")]
    found = R.proposals(rules, [_file(folder, "x.tmp", NOW), _file(folder, "y.txt", NOW)], folder, NOW)
    assert [(p.name, p.action, p.dest) for p in found] == [("x.tmp", "delete", ""), ("y.txt", "move", os.path.join(folder, "Rest"))]


def test_nothing_matching_gives_nothing(tmp_path):
    folder = _folder(tmp_path)
    assert R.proposals([R.FolderRule("*.pdf", "move", "A")], [_file(folder, "a.txt", NOW)], folder, NOW) == []
    assert R.proposals([], [_file(folder, "a.pdf", NOW)], folder, NOW) == []
    assert R.summary([]) == ""


def test_links_and_items_without_a_date_are_left_alone(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "link.pdf", NOW - 99 * DAY, is_link=True), _file(folder, "nodate.pdf", 0.0),
               _file(folder, "ok.pdf", NOW - 99 * DAY)]
    found = R.proposals([R.FolderRule("*.pdf", "move", "A", older_days=30)], entries, folder, NOW)
    assert [p.name for p in found] == ["ok.pdf"]
    # no age and no token in the destination: the date does not matter
    assert [p.name for p in R.proposals([R.FolderRule("*.pdf", "move", "A")], [_file(folder, "nodate.pdf", 0.0)], folder, NOW)] == ["nodate.pdf"]


def test_groups_are_per_action_and_destination_and_the_summary_counts_them(tmp_path):
    folder = _folder(tmp_path)
    entries = [_file(folder, "a.pdf", _at(2024, 1)), _file(folder, "b.pdf", _at(2024, 5)), _file(folder, "c.pdf", _at(2025, 1)),
               _file(folder, "d.tmp", NOW)]
    rules = [R.FolderRule("*.pdf", "move", "Archive/<year>"), R.FolderRule("*.tmp", "delete")]
    found = R.proposals(rules, entries, folder, NOW)
    groups = R.groups(found)
    assert [(g.action, len(g.items)) for g in groups] == [("move", 2), ("move", 1), ("delete", 1)]
    assert groups[0].paths == [os.path.join(folder, "a.pdf"), os.path.join(folder, "b.pdf")]
    assert R.summary(found) == "move 3 items and delete 1 item"
    assert R.summary(found[:1]) == "move 1 item"


def test_a_rule_that_cannot_work_is_refused_and_never_proposes(tmp_path):
    assert R.problem(R.FolderRule("", "move", "A"))
    assert R.problem(R.FolderRule("!*.txt", "move", "A"))              # only an exclusion
    assert R.problem(R.FolderRule("*.pdf", "move", ""))
    assert R.problem(R.FolderRule("*.pdf", "shred", "A"))
    assert R.problem(R.FolderRule("*.pdf", "delete", "", older_days=-1))
    assert R.problem(R.FolderRule("*.pdf", "delete", "")) == ""
    folder = _folder(tmp_path)
    assert R.proposals([R.FolderRule("*.pdf", "move", "")], [_file(folder, "a.pdf", NOW)], folder, NOW) == []


def test_describe_says_what_a_rule_does():
    text = R.describe(R.FolderRule("*.pdf", "move", "Archive/<year>", older_days=30, larger_than=2 << 20))
    assert text == "*.pdf, older than 30 days, larger than 2 MB: move to Archive/<year>"
    assert R.describe(R.FolderRule("*.tmp", "delete")) == "*.tmp: delete to the recycle bin"


def test_the_store_round_trips_through_json(tmp_path):
    folder = str(tmp_path / "Downloads")
    store = R.RuleStore()
    rule = R.FolderRule("*.pdf", "move", "Archive/<year>", older_days=30, larger_than=1 << 20)
    store.set_rules(folder, [rule, R.FolderRule("*.tmp", "delete")])
    again = R.RuleStore.from_json(store.to_json())
    assert again.rules_for(folder) == store.rules_for(folder)
    assert again.rules_for(folder)[0] == rule and again.rules_for(folder)[0].id == rule.id
    assert again.folders() == [os.path.normpath(folder)]
    assert again.rules_for(str(tmp_path / "other")) == []


def test_the_store_forgets_a_folder_with_no_rules_and_survives_damage(tmp_path):
    folder = str(tmp_path / "Downloads")
    store = R.RuleStore()
    store.set_rules(folder, [R.FolderRule("*.pdf", "move", "A"), R.FolderRule("", "move", "bad")])
    assert len(store.rules_for(folder)) == 1                            # the rule that cannot work was dropped
    store.set_rules(folder, [])
    assert len(store) == 0
    for text in ("", "not json", "{}", "[1, 2]", json.dumps([{"path": folder, "rules": [{"nonsense": 1}, "x"]}])):
        assert len(R.RuleStore.from_json(text)) == 0
    assert len(R.RuleStore.from_json(None)) == 0
    store.set_rules("relative/path", [R.FolderRule("*.pdf", "move", "A")])  # not a real folder path: no rules
    store.set_rules("sftp://host/dir", [R.FolderRule("*.pdf", "move", "A")])
    assert len(store) == 0
