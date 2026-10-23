"""Saved tab sets: the store, and opening, adding and forgetting them in a panel."""
import pytest

from dossier.core.tabsets import MAX_SETS, MAX_TABS, TabSetStore


def test_a_set_is_kept_found_replaced_and_forgotten():
    store = TabSetStore()
    assert store.save("work", ["C:/a", "C:/b"], 1).paths == ["C:/a", "C:/b"]
    assert store.get("work").active == 1 and store.names() == ["work"]
    store.save("Archive", ["D:/x"])
    assert store.names() == ["Archive", "work"]                       # sorted without regard to case
    store.save("work", ["C:/c"], 5)
    assert store.get("work").paths == ["C:/c"] and store.get("work").active == 0     # the old active tab does not exist any more
    assert store.forget("work") and not store.forget("work") and store.get("work") is None


def test_nothing_without_a_name_or_a_folder():
    store = TabSetStore()
    assert store.save("", ["C:/a"]) is None and store.save("  ", ["C:/a"]) is None
    assert store.save("empty", []) is None and store.save("blank", ["", ""]) is None
    assert len(store) == 0


def test_limits():
    store = TabSetStore()
    assert len(store.save("big", [f"C:/{i}" for i in range(MAX_TABS + 10)]).paths) == MAX_TABS
    for i in range(MAX_SETS + 5):
        store.save(f"s{i}", ["C:/a"])
    assert len(store) == MAX_SETS and store.get("s0") is None and store.get(f"s{MAX_SETS + 4}") is not None


def test_storage_round_trip_and_damaged_text():
    store = TabSetStore()
    store.save("work", ["C:/a", "D:/b"], 1)
    again = TabSetStore.from_json(store.to_json())
    assert again.get("work").paths == ["C:/a", "D:/b"] and again.get("work").active == 1
    for bad in ("", "not json", "{}", "[1, 2]", '[{"name": 3, "paths": []}]', '[{"name": "x"}]'):
        assert len(TabSetStore.from_json(bad)) == 0


pytest.importorskip("PyQt6")

from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def folders(tmp, *names):
    out = []
    for n in names:
        (tmp / n).mkdir(exist_ok=True)
        out.append(str(tmp / n))
    return out


def tab_folders(panel):
    return [p for p in panel.tab_paths()]


def test_saving_and_opening_a_set_replaces_the_tabs(world):
    win, d, left, right, tmp = world
    a, b = folders(tmp, "a", "b")
    win.left.restore_tabs([a, b, str(left)], 1)
    d.texts.append("my set")
    win.save_tab_set()
    assert win.tab_set_store().get("my set").paths == [a, b, str(left)] and win.tab_set_store().get("my set").active == 1
    assert "Saved 3 tabs as my set" in win.status.text()
    win.left.restore_tabs([str(left)], 0)
    assert win.left.tabs.count() == 1
    win.open_tab_set("my set")
    assert tab_folders(win.left) == [a, b, str(left)] and win.left.tabs.currentIndex() == 1
    assert "Opened the 3 tabs of my set" in win.status.text()


def test_adding_a_set_keeps_the_tabs_there_and_goes_to_its_active_one(world):
    win, d, left, right, tmp = world
    a, b = folders(tmp, "a", "b")
    win.tab_set_store().save("two", [a, b], 1)
    win.left.restore_tabs([str(left)], 0)
    win.open_tab_set("two", add=True)
    assert tab_folders(win.left) == [str(left), a, b] and win.left.tabs.currentIndex() == 2
    win.open_tab_set("nothing")
    assert "No saved tab set" in win.status.text()


def test_a_set_can_be_opened_into_the_other_panel_and_survives_a_new_window(world):
    win, d, left, right, tmp = world
    a, b = folders(tmp, "a", "b")
    win.tab_set_store().save("ab", [a, b])
    win._save_tab_sets()
    win.active = win.right if hasattr(win, "active") and win.active is win.left else win.left
    win.open_tab_set("ab")
    assert tab_folders(win.active) == [a, b]
    from dossier.core.tabsets import TabSetStore
    from dossier.gui.tab_sets import SETS_KEY
    assert TabSetStore.from_json(win.settings.value(SETS_KEY, "")).get("ab").paths == [a, b]


def test_forgetting_and_the_menus(world):
    win, d, left, right, tmp = world
    win.tab_set_store().save("one", [str(left)])
    win.tab_set_store().save("two", [str(right)])
    win.build_tab_set_menus(win._tab_open_menu, win._tab_add_menu, win._tab_forget_menu)
    assert [a.text() for a in win._tab_open_menu.actions()] == ["one", "two"]
    win._tab_forget_menu.actions()[0].trigger()
    assert win.tab_set_store().names() == ["two"] and "Forgot the tab set one" in win.status.text()
    win.forget_tab_set("two")
    win.build_tab_set_menus(win._tab_open_menu, win._tab_add_menu, win._tab_forget_menu)
    assert [a.text() for a in win._tab_open_menu.actions()] == ["Nothing saved yet"]
    assert win.settings.value("tabsets/sets") in (None, "")


def test_a_cancelled_name_saves_nothing(world):
    win, d, left, right, tmp = world
    win.save_tab_set()                                                  # the fake dialog answers None
    assert len(win.tab_set_store()) == 0
