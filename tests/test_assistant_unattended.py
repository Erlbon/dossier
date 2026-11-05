"""Card 33 of the functionality review of 2026-11-05: with "Let it carry out its own plans without asking" on, commit_plan runs the plan in
the server itself (the window may be closed), inside the listed folders, never overwriting and never deleting for good."""
import json
import os

import pytest

from dossier.assistant import config as cfg, paths, tools
from tests.test_assistant import ctx_for, home, put  # noqa: F401

try:
    from tests.test_gui_commander import app, world  # noqa: F401  (the window test at the end)
except ImportError:                                  # no PyQt6: the server tests still run
    pass


def unattended(allowed, **kw):
    ctx = ctx_for(allowed, changes=True, **kw)
    ctx.config.act_unattended = True
    return ctx


def test_the_setting_needs_file_changes_and_is_kept(tmp_path):
    path = str(tmp_path / "a.json")
    cfg.save(cfg.AssistantConfig(enabled=True, roots=[str(tmp_path)], allow_file_changes=False, act_unattended=True), path)
    assert cfg.load(path).act_unattended is False                       # never without "allow file changes"
    cfg.save(cfg.AssistantConfig(enabled=True, roots=[str(tmp_path)], allow_file_changes=True, act_unattended=True), path)
    assert cfg.load(path).act_unattended is True


def test_a_copy_is_carried_out_with_no_window_and_listed_for_the_owner(home):
    tmp, allowed = home
    (allowed / "src").mkdir()
    for i in range(5):
        put(allowed / "src" / f"f{i}.txt", b"x" * 1000)
    (allowed / "dest").mkdir()
    ctx = unattended(allowed)
    pid = tools.call(ctx, "plan_copy", {"sources": [str(allowed / "src")], "destination": str(allowed / "dest"),
                                       "reason": "the Maritime copy"})["plan_id"]
    out = tools.call(ctx, "commit_plan", {"plan_id": pid, "wait_seconds": 20})
    assert out["status"] == "done" and out["done"] == 6, out             # the folder and five files
    assert sorted(os.listdir(allowed / "dest" / "src")) == [f"f{i}.txt" for i in range(5)]
    with open(paths.away_file(), encoding="utf-8") as f:
        record = json.loads(f.read().splitlines()[-1])
    assert record["action"] == "copy" and record["reason"] == "the Maritime copy" and record["done"] == 6


def test_a_file_in_the_way_is_never_overwritten(home):
    tmp, allowed = home
    put(allowed / "a.txt", b"new")
    (allowed / "dest").mkdir()
    put(allowed / "dest" / "a.txt", b"old")
    ctx = unattended(allowed)
    pid = tools.call(ctx, "plan_copy", {"sources": [str(allowed / "a.txt")], "destination": str(allowed / "dest"),
                                       "on_conflict": "overwrite"})["plan_id"]
    out = tools.call(ctx, "commit_plan", {"plan_id": pid, "wait_seconds": 20})
    assert (allowed / "dest" / "a.txt").read_bytes() == b"old"
    assert "left out" in out["message"] and any("a.txt" in line for line in out["left_out"])


def test_a_permanent_delete_still_needs_the_owners_run(home):
    tmp, allowed = home
    put(allowed / "a.txt")
    ctx = unattended(allowed)
    pid = tools.call(ctx, "plan_delete", {"paths": [str(allowed / "a.txt")], "permanent": True})["plan_id"]
    with pytest.raises(tools.ToolError, match="needs the owner's Run"):
        tools.call(ctx, "commit_plan", {"plan_id": pid})
    assert (allowed / "a.txt").exists() and pid in ctx.plans             # nothing done; the plan can still go to the window


def test_a_delete_to_the_recycle_bin_runs(home, monkeypatch):
    from dossier.core import ops
    tmp, allowed = home
    put(allowed / "a.txt")
    binned = []
    monkeypatch.setattr(ops, "default_trash", lambda path: (binned.append(path), os.remove(path)))
    monkeypatch.setattr(ops, "_no_bin", lambda path: False)
    ctx = unattended(allowed)
    pid = tools.call(ctx, "plan_delete", {"paths": [str(allowed / "a.txt")]})["plan_id"]
    out = tools.call(ctx, "commit_plan", {"plan_id": pid, "wait_seconds": 20})
    assert out["status"] == "done" and not (allowed / "a.txt").exists()


def test_a_folder_listed_no_more_is_refused_at_commit(home):
    tmp, allowed = home
    put(allowed / "a.txt")
    (allowed / "dest").mkdir()
    ctx = unattended(allowed)
    pid = tools.call(ctx, "plan_copy", {"sources": [str(allowed / "a.txt")], "destination": str(allowed / "dest")})["plan_id"]
    ctx.config.roots = [str(tmp / "elsewhere")]                         # the owner took the folder off the list meanwhile
    with pytest.raises(tools.ToolError, match="outside"):
        tools.call(ctx, "commit_plan", {"plan_id": pid})
    assert not (allowed / "dest" / "a.txt").exists()


def test_the_window_shows_what_was_done_once(home, world):
    win, dialogs, *_ = world
    os.makedirs(os.path.dirname(paths.away_file()), exist_ok=True)
    with open(paths.away_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": 0, "action": "copy", "message": "6 steps done without asking",
                            "what": {"destination": "D:/x"}}) + chr(10))
    win._show_done_while_away()
    win._show_done_while_away()
    assert len(dialogs.infos) == 1 and "6 steps done without asking" in dialogs.infos[0][1]


# the owner's job: a local folder copied to an SFTP root with the window closed, then checked with a manifest -------------------------------
def test_the_maritime_copy_to_a_server_with_no_window(home, monkeypatch):
    from dossier.core import sftp_proto as sp
    from dossier.core.sftpfs import Session, make_path
    from tests.sftp_server import LocalServer, find_sftp_server
    if find_sftp_server() is None:
        pytest.skip("no sftp-server on this computer")
    tmp, allowed = home
    for name in ("Vrakkart/1910.doc", "Vrakkart/1911.doc", "Seilskip/Bark/x.pdf", "readme.txt"):
        put(allowed / "maritime" / name, name.encode() * 500)
    remote_folder = tmp / "homeserver3"
    remote_folder.mkdir()
    auth = "erlend@homeserver3:22"
    server = LocalServer(find_sftp_server(), str(remote_folder))
    client = sp.SftpClient(server.reader, server.writer, server.stop)
    try:
        ctx = ctx_for(allowed, changes=True)
        ctx.fs.sftp.add_session(Session(auth, client, read_only=False, base=server.path("").rstrip("/")))
        root = make_path(auth, "/")
        ctx.config.roots = [str(allowed), root]
        ctx.config.act_unattended = True
        monkeypatch.setattr(ctx.remotes, "ensure", lambda fs, config, path: None)      # connected above; no login here
        pid = tools.call(ctx, "plan_copy", {"sources": [str(allowed / "maritime")], "destination": root})["plan_id"]
        out = tools.call(ctx, "commit_plan", {"plan_id": pid, "wait_seconds": 60})
        assert out["status"] == "done" and out["done"] == 8, out            # four folders, four files
        manifest = tools.call(ctx, "write_manifest", {"folder": str(allowed / "maritime")})["manifest"]
        check = tools.call(ctx, "compare_with_manifest", {"manifest": manifest, "folder": make_path(auth, "/maritime")})
        summary = check["summary"]
        assert summary["files_b"] == 4 and summary["same"] == 4 and not check["results"], summary   # every file there, the same checksum
    finally:
        client.close()
