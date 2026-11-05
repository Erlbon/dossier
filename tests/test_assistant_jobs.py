"""The assistant's long calls (jobs), pages, manifests and reports, and a commit that runs longer than any wait."""
import os
import threading
import time

import pytest

from dossier.assistant import bridge, paths, tools
from dossier.assistant.scope import Denied
from test_assistant import FakeWindow, ctx_for, home, put  # noqa: F401 -- the fixture is used by name


def test_compare_folders_comes_in_pages_filters_by_status_and_writes_a_report(home):
    tmp, allowed = home
    for i in range(7):
        put(allowed / "L" / f"f{i}.txt", b"x")
    put(allowed / "R" / "only-right.txt", b"r")
    put(allowed / "L" / "summer.txt", b"s", 1_700_000_000)
    put(allowed / "R" / "summer.txt", b"s", 1_700_000_000 + 3600)
    ctx = ctx_for(allowed)
    first = tools.call(ctx, "compare_folders", {"left": str(allowed / "L"), "right": str(allowed / "R"), "limit": 3})
    assert first["differences"] == 8 and first["shown"] == 3 and first["more"] is True and first["by_status"] == {"only_left": 7, "only_right": 1}
    assert first["same"] == 1                                                          # exactly one hour apart: summer time, the same file
    nxt = tools.call(ctx, "get_job", {"job_id": first["job_id"], "offset": 3, "limit": 3})
    assert [r["path"] for r in nxt["results"]] == ["f3.txt", "f4.txt", "f5.txt"]
    right = tools.call(ctx, "get_job", {"job_id": first["job_id"], "status": ["only_right"]})
    assert right["matching"] == 1 and right["results"][0]["path"] == "only-right.txt"
    strict = tools.call(ctx, "compare_folders", {"left": str(allowed / "L"), "right": str(allowed / "R"), "ignore_hour": False, "report": True})
    assert strict["by_status"].get("right_newer") == 1
    report = strict["report"]
    assert report.startswith(paths.reports_dir()) and "only-right.txt" in open(report, encoding="utf-8-sig").read()
    with pytest.raises(tools.ToolError, match="status"):
        tools.call(ctx, "compare_folders", {"left": str(allowed / "L"), "right": str(allowed / "R"), "status": "only_left"})


def test_a_manifest_is_written_to_dossiers_own_folder_and_compared_with_a_folder_or_a_manifest(home):
    tmp, allowed = home
    put(allowed / "D" / "Vrakkart" / "highlight-for-xml.pdf", b"same pdf")
    put(allowed / "D" / "new.doc", b"only on D")
    put(allowed / "D" / "both.txt", b"one")
    put(allowed / "E" / "Vrakkart" / "evening_star.pdf", b"same pdf")
    put(allowed / "E" / "both.txt", b"two")
    ctx = ctx_for(allowed)                                                             # read-only: a manifest is not a change to the owner's files
    made = tools.call(ctx, "write_manifest", {"folder": str(allowed / "D")})
    assert made["files"] == 3 and made["manifest"].startswith(paths.reports_dir()) and not list((allowed / "D").glob("*.csv"))
    out = tools.call(ctx, "compare_with_manifest", {"manifest": made["manifest"], "folder": str(allowed / "E")})
    by = {r["path"]: r for r in out["results"]}
    assert by["new.doc"]["status"] == "only_a" and by["both.txt"]["status"] == "different"
    assert by["Vrakkart/highlight-for-xml.pdf"]["status"] == "only_a_content_elsewhere"
    assert by["Vrakkart/evening_star.pdf"]["content_elsewhere"] == ["Vrakkart/highlight-for-xml.pdf"]
    other = tools.call(ctx, "write_manifest", {"folder": str(allowed / "E")})["manifest"]
    two = tools.call(ctx, "compare_with_manifest", {"manifest": made["manifest"], "other_manifest": other, "report": True})
    assert two["summary"] == out["summary"] and os.path.isfile(two["report"])
    with pytest.raises(tools.ToolError, match="either folder or other_manifest"):
        tools.call(ctx, "compare_with_manifest", {"manifest": made["manifest"]})
    with pytest.raises(Denied):
        tools.call(ctx, "compare_with_manifest", {"manifest": str(tmp / "elsewhere.csv"), "folder": str(allowed / "E")})
    with pytest.raises(Denied):
        tools.call(ctx, "write_manifest", {"folder": str(tmp)})


def test_a_slow_call_returns_a_job_that_can_be_followed_and_cancelled(home, monkeypatch):
    tmp, allowed = home
    put(allowed / "a.txt")
    gate = threading.Event()
    from dossier.core import manifest as mf
    real = mf.build

    def slow(fs, root, cancel=None, progress=lambda p: None):
        while not gate.is_set():
            cancel.check()
            time.sleep(0.02)
        return real(fs, root, cancel, progress)
    monkeypatch.setattr(mf, "build", slow)
    ctx = ctx_for(allowed)
    started = tools.call(ctx, "write_manifest", {"folder": str(allowed), "wait_seconds": 0})
    assert started["status"] == "running" and "get_job" in started["next"]
    assert tools.call(ctx, "get_job", {"job_id": started["job_id"]})["status"] == "running"
    assert [j["job_id"] for j in tools.call(ctx, "list_jobs", {})["jobs"]] == [started["job_id"]]
    gate.set()
    done = tools.call(ctx, "get_job", {"job_id": started["job_id"], "wait_seconds": 10})
    assert done["files"] == 1
    gate.clear()
    again = tools.call(ctx, "write_manifest", {"folder": str(allowed), "wait_seconds": 0})
    assert tools.call(ctx, "cancel_job", {"job_id": again["job_id"]})["status"] == "cancelled"
    with pytest.raises(tools.ToolError, match="no such job"):
        tools.call(ctx, "get_job", {"job_id": "nope"})


class ClaimingWindow(FakeWindow):
    """A window whose owner agrees: it claims the request, runs for a while, then answers."""

    def __init__(self, run_seconds):
        self.run_seconds = run_seconds
        super().__init__()

    def run(self):
        while not self.stop:
            for req in bridge.pending_requests():
                self.seen.append(req)
                if bridge.claim(req["id"], steps=1):
                    threading.Timer(self.run_seconds, bridge.answer, (req["id"], "done", "1 step done"), {"done": 1, "failed": 0}).start()
            bridge.publish_state({"panels": [], "selection": []})
            time.sleep(0.05)


def test_a_change_that_runs_longer_than_the_wait_is_reported_as_running_not_as_nothing_changed(home):
    tmp, allowed = home
    put(allowed / "a.txt")
    (allowed / "dest").mkdir()
    ctx = ctx_for(allowed, changes=True, confirm_seconds=0.5)                          # the owner's answer window is short ...
    pid = tools.call(ctx, "plan_copy", {"sources": [str(allowed / "a.txt")], "destination": str(allowed / "dest")})["plan_id"]
    window = ClaimingWindow(run_seconds=2.0)                                           # ... and the copy takes longer than it
    try:
        out = tools.call(ctx, "commit_plan", {"plan_id": pid, "wait_seconds": 1})
        assert out["status"] == "running" and "agreed" in out["progress"]["stage"]
        done = tools.call(ctx, "get_job", {"job_id": out["job_id"], "wait_seconds": 10})
        assert done["status"] == "done" and done["done"] == 1
    finally:
        window.close()


def test_a_request_the_server_gave_up_on_cannot_be_claimed_afterwards(home):
    rid = bridge.post_request("plan", {})
    assert bridge.withdraw_request(rid) is True
    assert bridge.claim(rid) is False and bridge.running(rid) is None
    rid = bridge.post_request("plan", {})
    assert bridge.claim(rid, steps=3) is True and bridge.running(rid)["steps"] == 3
    assert bridge.withdraw_request(rid) is False                                       # claimed: the server must keep waiting
    bridge.answer(rid, "done", "ok")
    assert bridge.running(rid) is None and bridge.wait_response(rid, 1)["status"] == "done"
