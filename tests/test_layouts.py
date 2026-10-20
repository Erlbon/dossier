"""Folder layouts (core): which rule is in force for a folder, and how the store is kept."""
import json
import os

from dossier.core.layouts import Layout, LayoutStore, key_of

R = os.path.join(os.path.abspath(os.sep), "work")


def p(*parts):
    return os.path.join(R, *parts)


def lay(mode="details", sort="name"):
    return Layout(["size"], ["name", "type"], mode, 192, sort, True)


def test_a_folder_rule_is_found_for_that_folder_and_a_tree_rule_for_everything_below():
    s = LayoutStore()
    s.set(p("photos"), "tree", lay("icons", "modified"))
    s.set(p("music"), "only", lay())
    assert s.find(p("photos")).layout.mode == "icons"
    assert s.find(p("photos", "2024", "may")).path == os.path.normpath(p("photos"))
    assert s.find(p("music")) is not None and s.find(p("music", "album")) is None            # "only" stops at the folder
    assert s.find(p("other")) is None and s.find(p("photoshop")) is None                     # a sibling with a longer name is not below


def test_the_nearest_rule_wins_and_a_folders_own_rule_beats_a_parents_tree_rule():
    s = LayoutStore()
    s.set(p("a"), "tree", lay("icons"))
    s.set(p("a", "b"), "tree", lay("details"))
    s.set(p("a", "b", "c"), "only", lay("icons", "size"))
    assert s.find(p("a", "x")).layout.mode == "icons"
    assert s.find(p("a", "b", "x")).layout.mode == "details"
    assert s.find(p("a", "b", "c")).layout.sort == "size"
    assert s.find(p("a", "b", "c", "d")).layout.mode == "details"                          # the "only" rule did not reach down


def test_removing_a_rule_goes_back_to_the_parent_or_the_default():
    s = LayoutStore()
    s.set(p("a"), "tree", lay("icons"))
    s.set(p("a", "b"), "only", lay("details"))
    assert s.remove(p("a", "b")) and not s.remove(p("a", "b"))
    assert s.find(p("a", "b")).layout.mode == "icons"
    s.clear()
    assert s.find(p("a")) is None and len(s) == 0


def test_archives_search_results_the_home_page_and_relative_paths_have_no_rule():
    s = LayoutStore()
    assert s.set("zip://C:/x.zip/", "tree", lay()) is None and s.set("home://", "only", lay()) is None
    assert s.set("relative", "only", lay()) is None and s.set(p("a"), "sideways", lay()) is None
    assert s.find("zip://C:/x.zip/in") is None and s.find("") is None and s.exact("home://") is None


def test_names_differing_only_in_case_or_separators_are_the_same_folder_on_windows(monkeypatch):
    s = LayoutStore()
    s.set(p("Photos"), "only", lay())
    if os.name == "nt":
        assert s.exact(p("photos") + os.sep) is not None
        assert key_of(p("PHOTOS")) == key_of(p("photos"))


def test_a_layout_is_cleaned_name_and_type_stay_and_unknown_columns_go():
    c = Layout(["name", "type", "size", "nonsense"], ["size", "bogus", "size"], "tiles", 0, "weird", False).cleaned()
    assert c.hidden == ["size"] and c.order[0] == "size" and len(c.order) == len(set(c.order)) and "name" in c.order
    assert c.mode == "details" and c.size == 128 and c.sort == "name"


def test_the_store_round_trips_through_json_and_survives_junk():
    s = LayoutStore()
    s.set(p("a"), "tree", lay("icons", "modified"))
    s.set(p("b"), "only", lay())
    again = LayoutStore.from_json(s.to_json())
    assert [(r.path, r.scope, r.layout.mode, r.layout.sort, r.layout.desc, r.layout.size) for r in again.rules()] == \
           [(r.path, r.scope, r.layout.mode, r.layout.sort, r.layout.desc, r.layout.size) for r in s.rules()]
    for junk in ("", "not json", "{}", "[1, null, {}]", json.dumps([{"path": 5}]), json.dumps([{"path": p("a"), "size": "big"}])):
        assert len(LayoutStore.from_json(junk)) == 0
    assert len(LayoutStore.from_json(None)) == 0


def test_the_store_is_capped_and_the_oldest_rules_go_first(monkeypatch):
    import dossier.core.layouts as L
    monkeypatch.setattr(L, "MAX_RULES", 3)
    s = LayoutStore()
    for i in range(5):
        s.set(p(f"f{i}"), "only", lay())
    assert len(s) == 3 and s.exact(p("f0")) is None and s.exact(p("f4")) is not None
