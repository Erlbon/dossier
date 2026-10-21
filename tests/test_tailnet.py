"""The Tailnet section of the Home page: reading the local Tailscale's device list, showing it, and turning a device into a saved server."""
import json
import subprocess
import types

from dossier.core import tailnet
from dossier.core.home import HomeProvider, TailnetItem, build_entries

STATUS = json.dumps({
    "Self": {"HostName": "laptop", "DNSName": "laptop.tail1234.ts.net.", "TailscaleIPs": ["100.64.0.1", "fd7a::1"], "OS": "windows", "Online": True},
    "Peer": {
        "k1": {"HostName": "homeserver3", "DNSName": "homeserver3.tail1234.ts.net.", "TailscaleIPs": ["100.118.213.22"], "OS": "linux", "Online": True},
        "k2": {"HostName": "zeta-phone", "DNSName": "zeta-phone.tail1234.ts.net.", "TailscaleIPs": ["100.64.0.9"], "OS": "android", "Online": False},
        "k3": {"HostName": "alpha-nas", "DNSName": "alpha-nas.tail1234.ts.net.", "TailscaleIPs": ["100.64.0.5"], "OS": "linux", "Online": False},
        "bad": "not a node", "empty": {},
    }})


def test_the_status_becomes_devices_this_computer_first_then_online_then_by_name():
    devices = tailnet.parse_status(STATUS)
    assert [d.name for d in devices] == ["laptop", "homeserver3", "alpha-nas", "zeta-phone"]
    me, server = devices[0], devices[1]
    assert me.is_self and me.online and me.address == "100.64.0.1" and me.dns == "laptop.tail1234.ts.net"
    assert server.host == "100.118.213.22" and server.detail() == "100.118.213.22" and server.type_text() == "Linux, online"
    assert devices[2].type_text() == "Linux, offline" and me.type_text() == "Windows, this computer" and devices[3].type_text() == "Android, offline"


def test_damaged_or_foreign_status_text_is_no_devices_and_never_an_error():
    for text in ("", "not json", "[]", "null", '{"Self": 5, "Peer": [1]}', '{"Peer": {"a": {"HostName": ""}}}'):
        assert tailnet.parse_status(text) == []


def fake_run(stdout="", code=0, error=None):
    def run(cmd, **kw):
        assert cmd[1:] == ["status", "--json"] and kw["timeout"] > 0 and kw["stdin"] == subprocess.DEVNULL
        if error:
            raise error
        return types.SimpleNamespace(returncode=code, stdout=stdout)
    return run


def test_reading_the_devices_is_none_when_tailscale_is_missing_stopped_or_slow(monkeypatch):
    monkeypatch.setattr(tailnet, "find_tailscale", lambda: "")
    assert tailnet.read_devices() is None
    assert tailnet.read_devices("tailscale", fake_run(STATUS, code=1)) is None            # not running or not logged in
    assert tailnet.read_devices("tailscale", fake_run(error=FileNotFoundError())) is None
    assert tailnet.read_devices("tailscale", fake_run(error=subprocess.TimeoutExpired("tailscale", 5))) is None
    assert tailnet.read_devices("tailscale", fake_run("{}")) is None                       # nothing to show
    assert len(tailnet.read_devices("tailscale", fake_run(STATUS))) == 4


def test_the_home_page_has_a_tailnet_section_only_when_there_are_devices():
    quiet = HomeProvider(volumes=lambda: [], exists=lambda p: False)
    assert "Tailnet" not in [e.name for e in build_entries(quiet)]
    items = [TailnetItem("laptop", "100.64.0.1", "100.64.0.1", True, "Windows, this computer"), TailnetItem("phone", "100.64.0.9", "100.64.0.9", False, "Android, offline")]
    entries = build_entries(HomeProvider(volumes=lambda: [], exists=lambda p: False, tailnet=lambda: items))
    names = [e.name for e in entries]
    section = entries[names.index("Tailnet") + 1:]
    assert [e.name for e in section] == ["laptop", "phone"] and all(e.kind == "tailnet" and not e.is_dir for e in section)
    assert [e.detail for e in section] == ["100.64.0.1", "100.64.0.9"] and [e.label for e in section] == ["Windows, this computer", "Android, offline"]
    assert section[0].status == "ok" and section[1].status != "ok" and section[0].path.startswith("home://#tailnet/")
