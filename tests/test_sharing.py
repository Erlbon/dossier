"""Sharing folders and drives (SMB): names, addresses, the index the file list reads, the scripts and the elevated run."""
import base64
import subprocess
import sys

import pytest

from dossier.core import sharing
from dossier.core.sharing import CHANGE, EVERYONE, FULL, READ, Grant, Share, ShareError

B = chr(92)
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows shares")


def test_share_names_are_checked_like_windows_does():
    assert sharing.check_name("Comics") == ""
    assert "name" in sharing.check_name("  ")
    assert "cannot hold" in sharing.check_name("a/b") and "cannot hold" in sharing.check_name("a" + B + "b")
    assert "hidden" in sharing.check_name("Comics$")
    assert "already" in sharing.check_name("comics", taken=["Comics"])
    assert sharing.check_name("comics", taken=["Comics"], own="Comics") == ""          # the share being changed keeps its name
    assert "80" in sharing.check_name("x" * 81)


def test_a_new_name_comes_from_the_folder_or_the_drive_and_is_unique(tmp_path):
    folder = tmp_path / "Comics"
    assert sharing.suggest_name(str(folder)) == "Comics"
    assert sharing.suggest_name(str(folder), taken=["comics", "Comics-2"]) == "Comics-3"
    if sys.platform == "win32":
        assert sharing.suggest_name("D:" + B) == "D"
        assert sharing.suggest_name("D:" + B, label="Media") == "Media"
        assert sharing.is_drive_root("D:" + B) and not sharing.is_drive_root(str(folder))
    assert sharing.suggest_name(str(tmp_path / "a;b")) == "a_b"


def test_the_index_knows_shared_folders_by_path_whatever_the_case_or_slash(tmp_path):
    index = sharing.ShareIndex()
    folder = str(tmp_path / "Media")
    index.update([Share("Media", folder), Share("Media-rw", folder + B if sys.platform == "win32" else folder + "/"),
                  Share("Other", str(tmp_path / "x"))])
    assert index.names_for(folder) == ["Media", "Media-rw"]
    if sys.platform == "win32":
        assert index.names_for(folder.upper()) == ["Media", "Media-rw"]
    assert index.names_for(str(tmp_path)) == []
    assert index.all_names() == {"media", "media-rw", "other"}


def test_the_index_is_filled_on_a_thread():
    index = sharing.ShareIndex()
    done = []
    index.refresh_async(lambda: done.append(1), lister=lambda: [Share("S", "/somewhere")]).join(5)
    assert done == [1] and index.loaded and index.names_for("/somewhere") == ["S"]


def test_addresses_by_name_tailscale_and_each_local_ip():
    got = sharing.Addresses("PC", "100.101.7.12", ["192.168.1.20", "10.0.0.5"]).of("Comics")
    assert got == [("Name", B * 2 + "PC" + B + "Comics"), ("Tailscale", B * 2 + "100.101.7.12" + B + "Comics"),
                   ("Local network", B * 2 + "192.168.1.20" + B + "Comics"), ("Local network", B * 2 + "10.0.0.5" + B + "Comics")]
    assert sharing.Addresses("PC").of("C") == [("Name", B * 2 + "PC" + B + "C")]


def test_local_addresses_leave_out_loopback_link_local_and_tailscale(monkeypatch):
    monkeypatch.setattr(sharing, "IS_WINDOWS", False)
    found = [(2, 1, 6, "", (ip, 0)) for ip in ("127.0.1.1", "169.254.3.4", "100.80.1.2", "192.168.1.20", "192.168.1.20", "10.0.0.5")]
    assert sharing.local_ipv4s("pc", resolve=lambda *a: found) == ["192.168.1.20", "10.0.0.5"]


def test_local_addresses_on_windows_come_from_adapters_with_a_gateway(monkeypatch):
    monkeypatch.setattr(sharing, "IS_WINDOWS", True)
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "192.168.1.20\r\n100.90.1.1\r\n192.168.1.20\r\n", "")
    assert sharing.local_ipv4s("pc", run=run) == ["192.168.1.20"]
    assert "Gateway" in base64.b64decode(seen[0][-1]).decode("utf-16-le")


def test_this_computers_tailscale_address():
    class D:
        def __init__(self, address, is_self):
            self.address, self.is_self = address, is_self
    assert sharing.tailnet_ip(lambda: [D("100.1.1.1", False), D("100.2.2.2", True)]) == "100.2.2.2"
    assert sharing.tailnet_ip(lambda: None) == ""


def test_grants_read_from_windows_know_everyone_by_its_sid_in_any_language():
    text = ('[{"a":"Alle","r":2,"t":0,"s":"S-1-1-0"},{"a":"PC' + B * 2 + 'erlend","r":1,"t":0,"s":"S-1-5-21-1"},'
            '{"a":"PC' + B * 2 + 'guest","r":0,"t":1,"s":""}]')
    assert sharing.parse_grants_json(text) == [Grant(EVERYONE, READ), Grant("PC" + B + "erlend", CHANGE),
                                               Grant("PC" + B + "guest", FULL, denied=True)]
    assert sharing.parse_grants_json('{"a":"X","r":0,"t":0,"s":""}') == [Grant("X", FULL)]       # one entry comes as an object
    assert sharing.parse_grants_json("") == [] and sharing.parse_grants_json("rubbish") == []


def test_samba_usershares_are_read_with_their_grants():
    text = "[media]\npath=/srv/media\ncomment=films\nusershare_acl=Everyone:R,host" + B + "erlend:F,\nguest_ok=y\n\n[empty]\n"
    shares = sharing.parse_usershare_info(text)
    assert [(s.name, s.path, s.remark) for s in shares] == [("media", "/srv/media", "films")]
    assert shares[0].grants == [Grant(EVERYONE, READ), Grant("host" + B + "erlend", CHANGE)]


def test_scripts_quote_names_and_write_everyone_by_sid():
    grants = [Grant(EVERYONE, READ), Grant("PC" + B + "o'brien", CHANGE), Grant("PC" + B + "x", FULL, denied=True)]
    script = sharing.create_script("It's", "D:" + B + "Media", grants)
    assert "-Name 'It''s'" in script and "-Path 'D:" + B + "Media'" in script
    assert "-ReadAccess @($everyone)" in script and "-ChangeAccess @('PC" + B + "o''brien')" in script
    assert "S-1-1-0" in script and "FullAccess" not in script                    # a deny entry is never written
    with pytest.raises(ShareError):
        sharing.create_script("A", "D:" + B, [])


def test_changing_keeps_the_share_or_makes_a_new_one_when_renamed():
    same = sharing.change_script("Media", "Media", "D:" + B, [Grant(EVERYONE, READ)])
    assert "Revoke-SmbShareAccess" in same and "Grant-SmbShareAccess -Name 'Media' -AccountName $everyone -AccessRight Read" in same
    assert "Remove-SmbShare" not in same and "'Allow'" in same                   # deny entries stay as they are
    renamed = sharing.change_script("Media", "Films", "D:" + B, [Grant(EVERYONE, READ)])
    assert renamed.index("New-SmbShare -Name 'Films'") < renamed.index("Remove-SmbShare -Name 'Media'")


@WINDOWS
@pytest.mark.parametrize("script", [
    sharing.create_script("A'b", "D:" + B + "x", [Grant(EVERYONE, READ), Grant("PC" + B + "u", FULL)], "a note"),
    sharing.change_script("A", "A", "D:" + B, [Grant(EVERYONE, CHANGE)]),
    sharing.change_script("A", "B", "D:" + B, [Grant(EVERYONE, CHANGE)]),
    sharing.remove_script("A"),
])
def test_every_script_is_valid_powershell(script, tmp_path):
    """The scripts run elevated, where no output can be read back: a syntax error must be caught here."""
    wrapped = sharing._wrapped(script, str(tmp_path / "result.txt"))
    check = ("$e=$null; [void][Management.Automation.Language.Parser]::ParseInput($env:DOSSIER_SCRIPT,[ref]$null,[ref]$e); "
             "if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }")
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, text=True,
                          env={**__import__("os").environ, "DOSSIER_SCRIPT": wrapped}, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_elevated_run_reports_a_refused_prompt_and_powershells_own_error(monkeypatch):
    seen = []

    def refused(argv):
        seen.append(argv)
        return None
    with pytest.raises(sharing.Cancelled):
        sharing.run_elevated("Remove-SmbShare -Name 'A' -Force", start=refused)
    script = base64.b64decode(seen[0][-1]).decode("utf-16-le")
    assert seen[0][0] == "powershell.exe" and "Remove-SmbShare" in script and "Out-File" in script

    def failing(argv):
        script = base64.b64decode(argv[-1]).decode("utf-16-le")
        result_file = script.split("-FilePath '")[1].split("'")[0]
        with open(result_file, "w", encoding="utf-8-sig") as f:
            f.write("The name has already been shared.")
        return 1
    with pytest.raises(ShareError, match="already been shared"):
        sharing.run_elevated("New-SmbShare", start=failing)
    sharing.run_elevated("New-SmbShare", start=lambda argv: 0)                   # no error: nothing raised


def test_create_change_remove_go_through_the_elevated_run_on_windows(monkeypatch):
    monkeypatch.setattr(sharing, "IS_WINDOWS", True)
    scripts = []

    def start(argv):
        scripts.append(base64.b64decode(argv[-1]).decode("utf-16-le"))
        return 0
    sharing.create("Media", "D:" + B + "Media", [Grant(EVERYONE, READ)], start=start)
    sharing.change("Media", "Media", "D:" + B + "Media", [Grant(EVERYONE, CHANGE)], start=start)
    sharing.remove("Media", start=start)
    assert "New-SmbShare" in scripts[0] and "Grant-SmbShareAccess" in scripts[1] and "Remove-SmbShare" in scripts[2]


def test_usershares_on_linux_need_no_prompt(monkeypatch):
    monkeypatch.setattr(sharing, "IS_WINDOWS", False)
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    sharing.create("media", "/srv/media", [Grant(EVERYONE, READ), Grant("erlend", CHANGE)], "films", run=run)
    assert calls[-1] == ["net", "usershare", "add", "media", "/srv/media", "films", "Everyone:R,erlend:F", "guest_ok=y"]
    sharing.change("media", "films", "/srv/media", [Grant("erlend", READ)], run=run)
    assert calls[-2] == ["net", "usershare", "delete", "media"] and calls[-1][-1] == "guest_ok=n"

    def refusing(argv, **kw):
        return subprocess.CompletedProcess(argv, 255, "", "usershares are currently disabled")
    with pytest.raises(ShareError, match="disabled"):
        sharing.remove("media", run=refusing)


@WINDOWS
def test_accounts_are_looked_up_before_the_prompt():
    assert sharing.resolve_account("everyone") == EVERYONE
    me = sharing.current_user()
    assert sharing.resolve_account(me).casefold().endswith(me.split(B)[-1].casefold())
    with pytest.raises(ShareError, match="no user or group"):
        sharing.resolve_account("no-such-person-" + "x" * 8)


@WINDOWS
def test_listing_this_computers_shares_needs_no_rights_and_hides_the_special_ones():
    names = [s.name for s in sharing.list_shares()]
    assert "C$" not in names and "IPC$" not in names and "ADMIN$" not in names
