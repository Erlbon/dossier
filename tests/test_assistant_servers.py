"""Copying a list of paths keeping their folders, server folders as roots, pages for listings, the tool list following the changes switch,
and the window saying when its plan differs from the assistant's preview."""
import json
import os

import pytest

from dossier.assistant import config as cfg, server, tools
from dossier.assistant.remote import Remotes, RemoteError, server_paths
from dossier.assistant.scope import Denied, Scope
from dossier.cli.helpers import make_fs
from dossier.core.ops import Kind, bad_relative, plan_copy_paths
from test_assistant import ctx_for, home, put, rpc  # noqa: F401 -- the fixture is used by name


# 4: copy what is missing, to the same places --------------------------------------------------------------------------------------------
def test_copying_paths_makes_the_missing_folders_and_copies_only_those_files(tmp_path):
    src, dst = tmp_path / "D", tmp_path / "HS3"
    put(src / "Vrakkart" / "NO_vrakliste" / "1910.doc", b"a")
    put(src / "Vrakkart" / "NO_vrakliste" / "1911.doc", b"bb")
    put(src / "Vrakkart" / "other.jpg", b"not asked for")
    put(src / "Seilskip" / "Bark" / "x.pdf", b"ccc")
    (dst / "Vrakkart").mkdir(parents=True)
    plan = plan_copy_paths(make_fs(), str(src), str(dst), ["Vrakkart/NO_vrakliste/1910.doc", "Vrakkart/NO_vrakliste/1911.doc", "Seilskip/Bark/x.pdf"])
    assert not plan.blocking and not plan.conflicts
    made = [os.path.relpath(op.dst, dst) for op in plan.ops if op.kind is Kind.MKDIR]
    copied = [os.path.relpath(op.dst, dst) for op in plan.ops if op.kind is Kind.COPY]
    assert made == [os.path.join("Vrakkart", "NO_vrakliste"), "Seilskip", os.path.join("Seilskip", "Bark")]       # Vrakkart is there already
    assert len(copied) == 3 and sum(op.size for op in plan.ops) == 6
    put(dst / "Seilskip" / "Bark" / "x.pdf", b"old")
    assert plan_copy_paths(make_fs(), str(src), str(dst), ["Seilskip/Bark/x.pdf"]).conflicts                      # a taken name is a conflict
    assert "no longer there" in plan_copy_paths(make_fs(), str(src), str(dst), ["gone.txt"]).warnings[0]
    for bad in ("../x", "/etc/passwd", "C:/x", "a//b", "a/./b", ""):
        assert bad_relative(bad), bad
        assert plan_copy_paths(make_fs(), str(src), str(dst), [bad]).blocking


def test_the_tool_takes_the_paths_from_a_report_and_the_statuses_wanted(home):
    tmp, allowed = home
    put(allowed / "D" / "a" / "only.txt", b"1")
    put(allowed / "D" / "same.txt", b"s")
    put(allowed / "HS3" / "same.txt", b"s")
    put(allowed / "HS3" / "extra.txt", b"e")
    ctx = ctx_for(allowed, changes=True)
    report = tools.call(ctx, "compare_with_manifest", {"manifest": tools.call(ctx, "write_manifest", {"folder": str(allowed / "D")})["manifest"],
                                                       "folder": str(allowed / "HS3"), "report": True})["report"]
    plan = tools.call(ctx, "plan_copy_paths", {"source_root": str(allowed / "D"), "destination_root": str(allowed / "HS3"), "from_report": report,
                                               "statuses": ["only_a"]})
    assert plan["steps"] == 2 and plan["bytes"] == 1 and not (allowed / "HS3" / "a").exists()                     # a folder and a file, nothing done
    request = ctx.plans[plan["plan_id"]]
    assert request["action"] == "copy_paths" and request["paths"] == ["a/only.txt"] and request["expected"] == {"steps": 2, "bytes": 1}
    with pytest.raises(tools.ToolError, match="either paths or from_report"):
        tools.call(ctx, "plan_copy_paths", {"source_root": str(allowed / "D"), "destination_root": str(allowed / "HS3")})
    with pytest.raises(tools.ToolError, match="not a path below"):
        tools.call(ctx, "plan_copy_paths", {"source_root": str(allowed / "D"), "destination_root": str(allowed / "HS3"), "paths": ["../../x"]})
    with pytest.raises(Denied):
        tools.call(ctx, "plan_copy_paths", {"source_root": str(tmp), "destination_root": str(allowed / "HS3"), "paths": ["x"]})


# 5: server folders ---------------------------------------------------------------------------------------------------------------------------
def test_a_server_root_allows_only_paths_below_it_by_their_text(tmp_path):
    s = Scope([str(tmp_path), "sftp://erlend@homeserver3:22/F:/Maritime/"])
    assert s.server_roots == ["sftp://erlend@homeserver3:22/F:/Maritime"]
    assert s.resolve("sftp://erlend@homeserver3:22/F:/Maritime/Vrakkart/a.pdf") == "sftp://erlend@homeserver3:22/F:/Maritime/Vrakkart/a.pdf"
    assert s.resolve(str(tmp_path))
    for outside in ("sftp://erlend@homeserver3:22/F:/Other", "sftp://erlend@homeserver3:22/F:/MaritimeX", "sftp://other@homeserver3:22/F:/Maritime",
                    "scp://erlend@homeserver3:22/F:/Maritime", "sftp://erlend@homeserver3:22/F:/Maritime/../Other"):
        with pytest.raises(Denied):
            s.resolve(outside)
    with pytest.raises(Denied, match="SFTP and SCP"):
        s.resolve("webdav://host/x")
    assert cfg.server_root("webdav://host/x") == "" and cfg.server_root("sftp:///x") == "" and cfg.server_root("sftp://h") == "sftp://h/"


def test_server_roots_and_their_connections_are_kept_in_the_settings(home):
    tmp, allowed = home
    conn = {"name": "HS3", "host": "homeserver3", "user": "erlend", "port": 22, "protocol": "sftp", "read_only": True}
    cfg.save(cfg.AssistantConfig(True, [str(allowed), "sftp://erlend@homeserver3:22/F:/Maritime", "ftp://x/y"], servers=[conn],
                                 ssh_folder=str(tmp / "ssh")))
    got = cfg.load()
    assert got.roots == [os.path.normpath(str(allowed)), "sftp://erlend@homeserver3:22/F:/Maritime"] and got.servers == [conn]
    assert got.ssh_folder == str(tmp / "ssh")
    assert server_paths({"a": "sftp://h/x", "b": [str(allowed), "scp://h/y"], "c": "zip://q"}) == ["sftp://h/x", "scp://h/y"]


def test_a_server_is_connected_only_when_saved_and_its_host_key_approved_and_never_asks(home, monkeypatch):
    tmp, allowed = home
    root = "sftp://erlend@homeserver3/F:/Maritime"                                  # as Connection.url() writes it (port 22 left out)
    ctx = ctx_for(allowed)
    ctx.config.roots = [str(allowed), root]
    calls = []
    monkeypatch.setattr("dossier.core.sshlink.connect", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("must not connect")))
    with pytest.raises(tools.ToolError, match="not a saved server"):
        tools.call(ctx, "list_folder", {"path": root})
    ctx.config.servers = [{"name": "HS3", "host": "homeserver3", "user": "erlend", "port": 22, "protocol": "sftp"}]
    with pytest.raises(tools.ToolError, match="press Save once"):
        tools.call(ctx, "list_folder", {"path": root})
    ctx.config.ssh_folder = str(tmp / "ssh")
    os.makedirs(ctx.config.ssh_folder)
    with pytest.raises(tools.ToolError, match="host key of homeserver3 is not approved"):
        tools.call(ctx, "list_folder", {"path": root})
    assert calls == []
    with pytest.raises(Denied):
        tools.call(ctx, "list_folder", {"path": "sftp://erlend@homeserver3/C:/Users"})
    with pytest.raises(tools.ToolError, match="this computer's files only"):
        tools.call(ctx, "read_text", {"path": root + "/a.txt"})


# 6: pages, the tool list, the preview check ------------------------------------------------------------------------------------------------
def test_list_folder_and_search_have_pages(home):
    tmp, allowed = home
    for i in range(5):
        put(allowed / f"f{i}.txt", b"needle")
    ctx = ctx_for(allowed)
    page = tools.call(ctx, "list_folder", {"path": str(allowed), "offset": 3, "limit": 1})
    assert [e["name"] for e in page["entries"]] == ["f3.txt"] and page["truncated"] is True and page["count"] == 5
    assert tools.call(ctx, "list_folder", {"path": str(allowed), "offset": 4})["truncated"] is False
    found = tools.call(ctx, "search", {"folder": str(allowed), "name": "*.txt", "offset": 2, "limit": 2})
    assert found["count"] == 2 and found["offset"] == 2 and found["truncated"] is True


def test_the_plan_tools_are_listed_only_while_changes_are_allowed_and_a_switch_is_announced(home):
    tmp, allowed = home
    cfg.save(cfg.AssistantConfig(True, [str(allowed)], allow_file_changes=False))
    srv = server.Server()
    names = {t["name"] for t in rpc(srv, "tools/list")["result"]["tools"]}
    assert "list_folder" in names and "write_manifest" in names and not {n for n in names if n.startswith("plan_")} and "commit_plan" not in names
    assert "discard_plan" not in names
    rpc(srv, "tools/call", {"name": "list_roots", "arguments": {}})
    assert srv.take_notifications() == []
    cfg.save(cfg.AssistantConfig(True, [str(allowed)], allow_file_changes=True))
    rpc(srv, "tools/call", {"name": "list_roots", "arguments": {}})
    assert srv.take_notifications() == [{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}]
    assert "commit_plan" in {t["name"] for t in rpc(srv, "tools/list")["result"]["tools"]}


def test_the_window_says_so_when_its_plan_differs_from_the_preview():
    from dossier.core.ops import Op, Plan
    from dossier.gui.assistant import AssistantMixin
    plans = [Plan("Copy", (Op(Kind.COPY, "a", "b", size=10),))]
    same = AssistantMixin._assistant_summary(None, "copy", {"expected": {"steps": 1, "bytes": 10}}, plans)
    differs = AssistantMixin._assistant_summary(None, "copy_paths", {"expected": {"steps": 3, "bytes": 99}}, plans)
    assert "was shown" not in same and "was shown 3 steps" in differs and "files to the same places" in differs
