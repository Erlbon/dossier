"""The window's side of the assistant feature: the settings, what the window shows an assistant, and the confirmation of every change."""
import json
import os
import threading

import pytest

pytest.importorskip("PyQt6")

from dossier.assistant import bridge, config as cfg, paths, tools
from dossier.cli.helpers import make_fs
from dossier.gui.assistant import AssistantDialog, server_snippet
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401


def enable(win, allowed, **kw):
    cfg.save(cfg.AssistantConfig(True, [str(allowed)], kw.pop("changes", False), True, 256))
    win.assistant_tick()


def put(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def ask(win, kind, payload, wait=True):
    rid = bridge.post_request(kind, payload)
    win.assistant_tick()
    if not wait:
        return rid, None
    return rid, bridge.wait_response(rid, 0.5)


def settle(win, rid, timeout=8.0):
    """Run the window's events until the assistant's request has its answer (a plan runs on a thread)."""
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        data = bridge.wait_response(rid, 0.0)
        if data is not None:
            return data
        time.sleep(0.01)
    raise AssertionError("no answer")


# the settings --------------------------------------------------------------------------------------------------------------------------
def test_the_dialog_needs_a_folder_before_it_can_be_switched_on_and_keeps_the_choices(world, tmp_path):
    win, *_ = world
    dlg = AssistantDialog(win, cfg.AssistantConfig())
    assert not dlg.enabled.isChecked() and not dlg.changes.isChecked() and dlg.log.isChecked()
    dlg.enabled.setChecked(True)
    dlg._accept()
    assert "at least one folder" in dlg.problem.text() and dlg.result() == 0
    dlg.add_root(str(tmp_path))
    dlg.add_root(str(tmp_path))
    dlg.changes.setChecked(True)
    got = dlg.values()
    assert got.enabled and got.roots == [os.path.normpath(str(tmp_path))] and got.allow_file_changes
    assert "mcpServers" in server_snippet() and json.loads(server_snippet())["mcpServers"]["dossier"]["args"][-1] == "mcp"


def test_saving_the_settings_writes_the_file_and_switching_off_removes_what_the_window_showed(world, tmp_path, monkeypatch):
    win, d, left, right, tmp = world
    monkeypatch.setattr(type(win), "_ask_assistant_settings", lambda self, dlg: (dlg.enabled.setChecked(True), dlg.add_root(str(left)), True)[2])
    win.open_assistant_settings()
    assert cfg.load().enabled and cfg.load().roots == [os.path.normpath(str(left))]
    assert bridge.read_state()["window_running"] is True
    monkeypatch.setattr(type(win), "_ask_assistant_settings", lambda self, dlg: (dlg.enabled.setChecked(False), True)[1])
    win.open_assistant_settings()
    assert cfg.load().enabled is False and bridge.read_state()["age"] is None


# what the window shows --------------------------------------------------------------------------------------------------------------------
def test_nothing_is_published_while_the_feature_is_off(world):
    win, d, left, right, tmp = world
    win.assistant_tick()
    assert bridge.read_state()["age"] is None


def test_the_panels_the_cursor_and_the_selection_are_published_and_closing_removes_them(world):
    win, d, left, right, tmp = world
    put(left / "a.txt")
    win.left.refresh()
    pump(win, lambda: win.left.model.row_of("a.txt") >= 0)
    win.selection.add([str(left / "a.txt")])
    enable(win, tmp)
    state = bridge.read_state()
    assert state["window_running"] and state["active"] == "left" and state["selection"] == [str(left / "a.txt")]
    assert state["panels"][0]["path"] == str(left) and state["panels"][1]["path"] == str(right) and state["panels"][0]["side"] == "left"
    win.close()
    assert bridge.read_state()["age"] is None


# the selection ------------------------------------------------------------------------------------------------------------------------------
def test_an_assistant_can_change_the_shared_selection_inside_its_folders_only(world):
    win, d, left, right, tmp = world
    a, b = put(left / "a.txt"), put(left / "b.txt")
    enable(win, tmp)
    rid, answer = ask(win, "selection", {"op": "set", "paths": [a]})
    assert answer["status"] == "done" and answer["size"] == 1 and win.selection.paths() == [a]
    ask(win, "selection", {"op": "add", "paths": [b]})
    assert sorted(win.selection.paths()) == sorted([a, b])
    ask(win, "selection", {"op": "remove", "paths": [a]})
    assert win.selection.paths() == [b]
    _rid, answer = ask(win, "selection", {"op": "add", "paths": [str(tmp.parent / "outside.txt")]})
    assert answer["status"] == "failed" and "outside" in answer["message"] and win.selection.paths() == [b]
    _rid, answer = ask(win, "selection", {"op": "explode", "paths": []})
    assert answer["status"] == "failed"
    ask(win, "selection", {"op": "clear"})
    assert win.selection.paths() == []
    _rid, answer = ask(win, "nonsense", {})
    assert answer["status"] == "failed"


def test_requests_are_ignored_while_the_feature_is_off(world):
    win, d, left, right, tmp = world
    rid, answer = ask(win, "selection", {"op": "clear"})
    assert answer is None and bridge.pending_requests()[0]["id"] == rid


# changes to files ---------------------------------------------------------------------------------------------------------------------------
def test_a_change_is_refused_when_the_owner_has_not_allowed_changes(world):
    win, d, left, right, tmp = world
    put(left / "a.txt")
    (right / "dest").mkdir()
    enable(win, tmp, changes=False)
    _rid, answer = ask(win, "plan", {"action": "copy", "sources": [str(left / "a.txt")], "destination": str(right / "dest")})
    assert answer["status"] == "rejected" and "not allowed" in answer["message"] and not d.confirms
    assert not (right / "dest" / "a.txt").exists()


def test_the_owner_sees_the_change_in_words_and_it_runs_only_when_they_say_run(world):
    win, d, left, right, tmp = world
    put(left / "a.txt", b"alpha")
    (right / "dest").mkdir()
    enable(win, tmp, changes=True)
    d.confirm_answer = False
    rid, _ = ask(win, "plan", {"action": "copy", "sources": [str(left / "a.txt")], "destination": str(right / "dest"), "reason": "tidying\nthe photos"}, wait=False)
    answer = settle(win, rid)
    assert answer["status"] == "rejected" and not (right / "dest" / "a.txt").exists()
    title, text = d.confirms[-1]
    assert title == "An assistant asks to change files" and "copy" in text and str(left / "a.txt") in text and "tidying the photos" in text
    assert "not checked" in text and "Run it only if" in text
    d.confirm_answer = True
    rid, _ = ask(win, "plan", {"action": "copy", "sources": [str(left / "a.txt")], "destination": str(right / "dest")}, wait=False)
    answer = settle(win, rid)
    assert answer["status"] == "done" and answer["done"] >= 1 and (right / "dest" / "a.txt").read_bytes() == b"alpha"


def test_the_window_checks_the_folders_again_and_a_request_from_outside_them_never_gets_that_far(world):
    win, d, left, right, tmp = world
    outside = tmp.parent / "outside-folder"
    outside.mkdir(exist_ok=True)
    put(outside / "private.txt")
    enable(win, tmp, changes=True)
    rid, answer = ask(win, "plan", {"action": "delete", "paths": [str(outside / "private.txt")]})
    assert answer["status"] == "rejected" and "outside" in answer["message"] and not d.confirms and (outside / "private.txt").exists()


def test_delete_move_rename_and_sync_each_ask_first_and_then_do_it(world):
    win, d, left, right, tmp = world
    enable(win, tmp, changes=True)
    a, b, c = put(left / "del.txt"), put(left / "mv.txt"), put(left / "old-name.txt")
    (right / "target").mkdir()
    rid, _ = ask(win, "plan", {"action": "delete", "paths": [a]}, wait=False)
    assert settle(win, rid)["status"] == "done" and not os.path.exists(a)
    rid, _ = ask(win, "plan", {"action": "move", "sources": [b], "destination": str(right / "target")}, wait=False)
    assert settle(win, rid)["status"] == "done" and (right / "target" / "mv.txt").exists() and not os.path.exists(b)
    rid, _ = ask(win, "plan", {"action": "rename", "path": c, "new_name": "new-name.txt"}, wait=False)
    assert settle(win, rid)["status"] == "done" and (left / "new-name.txt").exists()
    put(left / "sync" / "one.txt", b"1")
    (right / "sync").mkdir()
    rid, _ = ask(win, "plan", {"action": "sync", "left": str(left / "sync"), "right": str(right / "sync"), "mode": "update_right"}, wait=False)
    assert settle(win, rid)["status"] == "done" and (right / "sync" / "one.txt").read_bytes() == b"1"
    assert len(d.confirms) == 4


def test_a_request_is_not_taken_twice_while_the_owner_is_still_deciding(world):
    win, d, left, right, tmp = world
    put(left / "a.txt")
    (right / "dest").mkdir()
    enable(win, tmp, changes=True)
    calls = []
    d.confirm = lambda title, text, ok="OK": (calls.append(1), False)[1]
    rid, _ = ask(win, "plan", {"action": "copy", "sources": [str(left / "a.txt")], "destination": str(right / "dest")}, wait=False)
    settle(win, rid)
    assert calls == [1]


# the whole way: the tools of the server and the window together ------------------------------------------------------------------------------------
def test_an_assistant_commits_a_plan_and_the_owner_confirms_in_the_window(world):
    win, d, left, right, tmp = world
    put(left / "report.txt", b"quarterly")
    (right / "archive").mkdir()
    enable(win, tmp, changes=True)
    ctx = tools.Context(cfg.load(), make_fs(), confirm_seconds=10)
    plan = tools.call(ctx, "plan_move", {"sources": [str(left / "report.txt")], "destination": str(right / "archive"), "reason": "archive the report"})
    assert (left / "report.txt").exists()                                            # a plan changes nothing
    outcome = {}

    def commit():
        outcome["result"] = tools.call(ctx, "commit_plan", {"plan_id": plan["plan_id"]})
    thread = threading.Thread(target=commit)
    thread.start()
    import time
    from PyQt6.QtWidgets import QApplication
    end = time.time() + 15
    while thread.is_alive() and time.time() < end:
        win.assistant_tick()
        QApplication.processEvents()
        time.sleep(0.02)
    thread.join(2)
    assert outcome["result"]["status"] == "done" and (right / "archive" / "report.txt").read_bytes() == b"quarterly" and not (left / "report.txt").exists()
    assert "archive the report" in d.confirms[-1][1]
