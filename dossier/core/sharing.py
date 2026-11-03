"""Sharing a folder or a drive on the network (SMB), the way Explorer's Sharing tab does. Qt-free.

Reading needs no rights: which shares exist (``NetShareEnum``, a few milliseconds) and who may use one (``Get-SmbShareAccess``). Making,
changing and removing a share needs an administrator on Windows; Dossier never runs as one, so each change is one PowerShell script
started through the system's own elevation prompt (UAC), and the window waits for it on a thread. On Linux, Samba's *usershares*
(``net usershare``) need no root, when the system allows them.

A share's permissions say who may use it over the network; the folder's own file permissions still apply on top of them, as in
Explorer's Advanced Sharing. Only the "allow" entries are written: a "deny" entry made elsewhere is left as it is.

"Everyone" has another name on a Windows in another language (Alle, Jeder, Tout le monde), so it is written and read by its SID.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"
TIMEOUT = 30
EVERYONE = "Everyone"
EVERYONE_SID = "S-1-1-0"
READ, CHANGE, FULL = "read", "change", "full"
ACCESS = (READ, CHANGE, FULL)
ACCESS_LABELS = {READ: "Read only", CHANGE: "Read and change", FULL: "Full control"}
NAME_LIMIT = 80
BAD_NAME_CHARS = '"/\\[]:|<>+=;,?*'
TAILNET_RANGE = ((100, 64), (100, 127))          # 100.64.0.0/10, Tailscale's addresses (shown on their own line)


class ShareError(Exception):
    """A share could not be read, made, changed or removed. The text says why, in words for the owner."""


class Cancelled(ShareError):
    """The owner said no to the administrator prompt."""


@dataclass(frozen=True)
class Grant:
    account: str                 # EVERYONE, or a user or group name (DOMAIN\\name or name)
    access: str = READ           # READ, CHANGE or FULL
    denied: bool = False         # a deny entry made elsewhere: shown, never written


@dataclass
class Share:
    name: str
    path: str
    remark: str = ""
    grants: list = field(default_factory=list)


# the shares that exist --------------------------------------------------------------------------------------------------------
def path_key(path: str) -> str:
    """One form for a folder path, so ``D:\\Media\\`` and ``d:\\media`` are the same folder (case is ignored on Windows only)."""
    if not path:
        return ""
    key = os.path.normpath(path)
    key = key.lower() if IS_WINDOWS else key
    return key.rstrip("\\/") or key


def is_hidden_name(name: str) -> bool:
    """A name ending in $ is a hidden share; C$ and ADMIN$ are Windows' own and never shown."""
    return name.endswith("$")


def list_shares() -> list:
    """The visible folder shares of this computer (no grants: see ``read_grants``). Never raises: an empty list when they cannot be read."""
    try:
        return _windows_shares() if IS_WINDOWS else _usershares()
    except (OSError, ValueError, AttributeError):
        return []


def _windows_shares() -> list:
    import ctypes
    from ctypes import wintypes as w

    class SHARE_INFO_2(ctypes.Structure):
        _fields_ = [("netname", w.LPWSTR), ("type", w.DWORD), ("remark", w.LPWSTR), ("permissions", w.DWORD),
                    ("max_uses", w.DWORD), ("current_uses", w.DWORD), ("path", w.LPWSTR), ("passwd", w.LPWSTR)]

    netapi = ctypes.windll.netapi32
    buf, read, total = ctypes.c_void_p(), w.DWORD(), w.DWORD()
    rc = netapi.NetShareEnum(None, 2, ctypes.byref(buf), 0xFFFFFFFF, ctypes.byref(read), ctypes.byref(total), None)
    if rc != 0:
        return []
    try:
        if not read.value:
            return []
        rows = ctypes.cast(buf, ctypes.POINTER(SHARE_INFO_2 * read.value)).contents
        out = []
        for row in rows:
            if row.type & 0xFF != 0 or row.type & 0x80000000:       # only disk shares, not the special ones (C$, IPC$)
                continue
            if row.netname and row.path and not is_hidden_name(row.netname):
                out.append(Share(row.netname, row.path, row.remark or ""))
        return out
    finally:
        netapi.NetApiBufferFree(buf)


def _net(args: list, run: Callable = subprocess.run):
    return run(["net", "usershare", *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)


def _usershares(run: Callable = subprocess.run) -> list:
    try:
        done = _net(["info"], run)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_usershare_info(done.stdout) if done.returncode == 0 else []


def parse_usershare_info(text: str) -> list:
    """The shares in the output of ``net usershare info`` (an ini-like text), with their grants."""
    out, cur = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = Share(line[1:-1], "")
            out.append(cur)
        elif cur is not None and "=" in line:
            key, value = line.split("=", 1)
            if key == "path":
                cur.path = value
            elif key == "comment":
                cur.remark = value
            elif key == "usershare_acl":
                cur.grants = parse_usershare_acl(value)
    return [s for s in out if s.path]


def parse_usershare_acl(text: str) -> list:
    """``Everyone:R,host\\erlend:F,`` as grants (F is shown as Read and change: usershares have no finer rights)."""
    grants = []
    for part in (text or "").split(","):
        account, _, right = part.strip().rpartition(":")
        if not account:
            continue
        right = right.upper()
        if right == "D":
            grants.append(Grant(_plain_everyone(account), READ, denied=True))
        else:
            grants.append(Grant(_plain_everyone(account), CHANGE if right == "F" else READ))
    return grants


def _plain_everyone(account: str) -> str:
    return EVERYONE if account.split("\\")[-1].lower() == "everyone" else account


class ShareIndex:
    """Which folders are shared, by path: what the file list's mark, the Shared as column and the right-click menu read. Filled on a
    thread (``refresh_async``); reading it never touches anything."""

    def __init__(self) -> None:
        self._by_path: dict = {}
        self._lock = threading.Lock()
        self.loaded = False

    def update(self, shares: list) -> None:
        by_path: dict = {}
        for s in shares:
            by_path.setdefault(path_key(s.path), []).append(s.name)
        for names in by_path.values():
            names.sort(key=str.casefold)
        with self._lock:
            self._by_path = by_path
            self.loaded = True

    def names_for(self, path: str) -> list:
        with self._lock:
            return list(self._by_path.get(path_key(path), ()))

    def all_names(self) -> set:
        with self._lock:
            return {n.casefold() for names in self._by_path.values() for n in names}

    def refresh_async(self, on_done: Optional[Callable[[], None]] = None, lister: Callable = None) -> threading.Thread:
        """Read the shares again on a daemon thread; ``on_done`` is called on that thread when they are in."""
        def work() -> None:
            self.update((lister or list_shares)())
            if on_done is not None:
                on_done()

        t = threading.Thread(target=work, name="dossier-shares", daemon=True)
        t.start()
        return t


KNOWN = ShareIndex()


# the shares of another computer ------------------------------------------------------------------------------------------------
BACK = "\\"
UNREACHABLE = {53, 64, 67, 1231, 1722, 2114}       # no such computer, the connection dropped, no Server service or RPC: often the firewall
NEEDS_LOGIN = {5, 86, 1326, 1327, 1330, 1331, 1907, 1219}
FIREWALL_HINT = ("If that computer is on, its firewall may block file sharing. Windows often marks a Tailscale or new network as Public, "
                 "and blocks file sharing there: on that computer, allow File and Printer Sharing for that network, or mark it "
                 "Private.")


def _unc_parts(path: str) -> list:
    if not IS_WINDOWS:                               # a backslash is an ordinary character in a name elsewhere
        return []
    text = (path or "").replace("/", BACK)
    if not text.startswith(BACK * 2) or text.startswith((BACK * 2 + "?", BACK * 2 + ".")):
        return []
    return [p for p in text[2:].split(BACK) if p]


def machine_of(path: str) -> str:
    """The computer of ``\\\\machine`` (the list of its shares), or an empty string for any other path."""
    parts = _unc_parts(path)
    return parts[0] if len(parts) == 1 else ""


def is_share_root(path: str) -> bool:
    """``\\\\machine\\share`` itself: a share of another computer, as listed in its machine's list."""
    return len(_unc_parts(path)) == 2


def machine_root(path: str) -> str:
    """``\\\\machine`` of a network path, or an empty string."""
    parts = _unc_parts(path)
    return BACK * 2 + parts[0] if parts else ""


def list_remote(host: str, enum: Optional[Callable] = None) -> list:
    """The visible folder shares of the computer ``host`` (a name or an address), as Windows lists them to any user. Takes a moment
    and may wait for a computer that does not answer: call it on a thread. Raises OSError (with ``winerror``) saying why not."""
    if not IS_WINDOWS and enum is None:
        raise OSError(0, "Listing another computer's shares is only built for Windows. Open a share by its full address "
                         "(smb://machine/share in your system's file manager, or mount it), and it opens here as a folder.")
    rc, rows = (enum or _enum_remote)(host)
    if rc != 0:
        if rc in UNREACHABLE:
            why = f"{host} does not answer for file sharing (Windows error {rc}). {FIREWALL_HINT}"
        elif rc in NEEDS_LOGIN:
            why = f"{host} wants a user name and password before it shows its shares (Windows error {rc})."
        else:
            why = f"{host} did not list its shares (Windows error {rc})."
        raise OSError(0, why, BACK * 2 + host, rc)
    return [Share(name, BACK * 2 + host + BACK + name, remark) for name, kind, remark in rows
            if kind & 0xFF == 0 and not kind & 0x80000000 and not is_hidden_name(name)]


def _enum_remote(host: str) -> tuple:
    import ctypes
    from ctypes import wintypes as w

    class SHARE_INFO_1(ctypes.Structure):
        _fields_ = [("netname", w.LPWSTR), ("type", w.DWORD), ("remark", w.LPWSTR)]

    netapi = ctypes.windll.netapi32
    buf, read, total = ctypes.c_void_p(), w.DWORD(), w.DWORD()
    rc = netapi.NetShareEnum(BACK * 2 + host, 1, ctypes.byref(buf), 0xFFFFFFFF, ctypes.byref(read), ctypes.byref(total), None)
    try:
        if rc != 0 or not read.value:
            return rc, []
        rows = ctypes.cast(buf, ctypes.POINTER(SHARE_INFO_1 * read.value)).contents
        return 0, [(r.netname, r.type, r.remark or "") for r in rows if r.netname]
    finally:
        if buf:
            netapi.NetApiBufferFree(buf)


# who may use a share ----------------------------------------------------------------------------------------------------------
RIGHTS_FROM_WINDOWS = {0: FULL, 1: CHANGE, 2: READ}


def read_grants(name: str, run: Callable = subprocess.run) -> list:
    """Who may use the share ``name``. Takes a moment (it starts PowerShell on Windows): call it on a thread. Raises ShareError."""
    if not IS_WINDOWS:
        for s in _usershares(run):
            if s.name.casefold() == name.casefold():
                return s.grants
        raise ShareError(f"There is no share called {name}.")
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              f"@(Get-SmbShareAccess -Name {ps_quote(name)} | ForEach-Object {{ $sid=''; "
              "try { $sid=(New-Object Security.Principal.NTAccount $_.AccountName).Translate([Security.Principal.SecurityIdentifier]).Value } "
              "catch {}; [pscustomobject]@{a=$_.AccountName; r=[int]$_.AccessRight; t=[int]$_.AccessControlType; s=$sid} }) | "
              "ConvertTo-Json -Compress")
    try:
        done = run(_powershell(script), capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        raise ShareError(f"Could not read who may use {name}: {e}") from e
    if done.returncode != 0:
        raise ShareError(f"Could not read who may use {name}: {(done.stderr or '').strip()[:300]}")
    return parse_grants_json(done.stdout)


def parse_grants_json(text: str) -> list:
    """The grants in the JSON the PowerShell of ``read_grants`` writes (one object or a list; "Everyone" known by its SID)."""
    try:
        doc = json.loads(text) if (text or "").strip() else []
    except ValueError:
        return []
    rows = doc if isinstance(doc, list) else [doc]
    grants = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("a"):
            continue
        account = EVERYONE if row.get("s") == EVERYONE_SID else str(row["a"])
        access = RIGHTS_FROM_WINDOWS.get(row.get("r"), READ)
        grants.append(Grant(account, access, denied=row.get("t") == 1))
    return grants


def current_user() -> str:
    """This user as Windows names it (``PC\\erlend``, ``DOMAIN\\erlend``), or the plain login name elsewhere."""
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if not user:
        try:
            import getpass
            user = getpass.getuser()
        except (OSError, KeyError, ImportError):
            return ""
    domain = os.environ.get("USERDOMAIN", "") if IS_WINDOWS else ""
    return f"{domain}\\{user}" if domain else user


def local_accounts() -> list:
    """The ordinary, switched-on user accounts of this computer (for the Who list). Never raises."""
    try:
        return _windows_accounts() if IS_WINDOWS else _posix_accounts()
    except (OSError, ValueError, AttributeError, ImportError):
        return []


def _windows_accounts() -> list:
    import ctypes
    from ctypes import wintypes as w

    class USER_INFO_1(ctypes.Structure):
        _fields_ = [("name", w.LPWSTR), ("password", w.LPWSTR), ("password_age", w.DWORD), ("priv", w.DWORD),
                    ("home_dir", w.LPWSTR), ("comment", w.LPWSTR), ("flags", w.DWORD), ("script_path", w.LPWSTR)]

    netapi = ctypes.windll.netapi32
    buf, read, total = ctypes.c_void_p(), w.DWORD(), w.DWORD()
    rc = netapi.NetUserEnum(None, 1, 2, ctypes.byref(buf), 0xFFFFFFFF, ctypes.byref(read), ctypes.byref(total), None)   # 2: normal accounts
    if rc != 0:
        return []
    try:
        if not read.value:
            return []
        rows = ctypes.cast(buf, ctypes.POINTER(USER_INFO_1 * read.value)).contents
        return sorted((r.name for r in rows if r.name and not r.flags & 0x2), key=str.casefold)     # 0x2: switched off
    finally:
        netapi.NetApiBufferFree(buf)


def _posix_accounts() -> list:
    import pwd
    return sorted((p.pw_name for p in pwd.getpwall() if 1000 <= p.pw_uid < 60000), key=str.casefold)


def resolve_account(name: str) -> str:
    """The account ``name`` the way the system knows it, or ShareError when there is no such user or group (so a typing error is
    refused before the administrator prompt, not after)."""
    name = (name or "").strip()
    if not name:
        raise ShareError("Who may use the share? A name is empty.")
    if name.casefold() == EVERYONE.casefold():
        return EVERYONE
    if IS_WINDOWS:
        return _lookup_windows(name)
    import grp
    import pwd
    for look in (pwd.getpwnam, grp.getgrnam):
        try:
            look(name)
            return name
        except KeyError:
            continue
    raise ShareError(f"There is no user or group called {name} on this computer.")


def _lookup_windows(name: str) -> str:
    import ctypes
    from ctypes import wintypes as w
    advapi = ctypes.windll.advapi32
    sid = ctypes.create_string_buffer(256)
    sid_size, dom_size, use = w.DWORD(256), w.DWORD(256), w.DWORD()
    domain = ctypes.create_unicode_buffer(256)
    if not advapi.LookupAccountNameW(None, name, sid, ctypes.byref(sid_size), domain, ctypes.byref(dom_size), ctypes.byref(use)):
        raise ShareError(f"There is no user or group called {name}.")
    user = name.split("\\")[-1]
    return f"{domain.value}\\{user}" if domain.value else user


# names and addresses -----------------------------------------------------------------------------------------------------------
def check_name(name: str, taken=(), own: str = "") -> str:
    """Why ``name`` cannot be a share name (``taken``: the names in use, ``own``: the share being changed), or an empty string."""
    name = name.strip()
    if not name:
        return "The share needs a name."
    if len(name) > NAME_LIMIT:
        return f"A share name can be at most {NAME_LIMIT} characters long."
    bad = sorted({c for c in name if c in BAD_NAME_CHARS or ord(c) < 32})
    if bad:
        return "A share name cannot hold " + " ".join(bad) + "."
    if name.endswith("$"):
        return "A name ending in $ makes a hidden share; Dossier keeps those for Windows."
    if name.casefold() != own.casefold() and name.casefold() in {t.casefold() for t in taken}:
        return f"There is already a share called {name}."
    return ""


def suggest_name(path: str, label: str = "", taken=()) -> str:
    """A name for a new share of ``path``: the folder's name, or for a drive its label (else its letter), made unique."""
    base = os.path.basename(os.path.normpath(path).rstrip("\\/"))
    if not base:                                                     # a drive root
        base = label or os.path.splitdrive(path)[0].rstrip(":") or "Share"
    base = "".join("_" if c in BAD_NAME_CHARS else c for c in base).strip().rstrip("$")[:NAME_LIMIT] or "Share"
    lower = {t.casefold() for t in taken}
    name, n = base, 2
    while name.casefold() in lower:
        name, n = f"{base[:NAME_LIMIT - 4]}-{n}", n + 1
    return name


def is_drive_root(path: str) -> bool:
    p = os.path.abspath(path)
    return os.path.dirname(p) == p


def _in_tailnet(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4 or not all(x.isdigit() for x in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    return a == TAILNET_RANGE[0][0] and TAILNET_RANGE[0][1] <= b <= TAILNET_RANGE[1][1]


LAN_SCRIPT = ("Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | "
              "ForEach-Object { $_.IPv4Address.IPAddress }")


def local_ipv4s(host: str = "", resolve: Callable = socket.getaddrinfo, run: Callable = subprocess.run) -> list:
    """This computer's own IPv4 addresses on its local networks (wired and Wi-Fi), without loopback, link-local and Tailscale ones.
    On Windows only adapters with a gateway count, so the virtual ones of Hyper-V and WSL are left out."""
    if IS_WINDOWS:
        try:
            done = run(_powershell(LAN_SCRIPT), capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if done.returncode == 0:
                found = [ip.strip() for ip in done.stdout.split() if ip.strip()]
                return [ip for i, ip in enumerate(found) if ip not in found[:i] and not ip.startswith(("127.", "169.254."))
                        and not _in_tailnet(ip)]
        except (OSError, subprocess.SubprocessError):
            pass
    host = host or socket.gethostname()
    try:
        found = resolve(host, None, socket.AF_INET)
    except (OSError, UnicodeError):
        return []
    out = []
    for item in found:
        ip = item[4][0]
        if ip.startswith(("127.", "169.254.")) or _in_tailnet(ip) or ip in out:
            continue
        out.append(ip)
    return out


def tailnet_ip(read_devices: Optional[Callable] = None) -> str:
    """This computer's Tailscale address, or an empty string when it is not on a tailnet. Starts a program: call it on a thread."""
    from . import tailnet
    devices = (read_devices or tailnet.read_devices)()
    me = next((d for d in devices or () if d.is_self), None)
    return me.address if me else ""


def addresses(share_name: str, host: str, tailnet_address: str = "", lan: list = ()) -> list:
    """The addresses others type to reach the share, as (label, address): by the computer's name, by Tailscale, by local IP."""
    back = "\\"
    out = [("Name", f"{back * 2}{host}{back}{share_name}")] if host else []
    if tailnet_address:
        out.append(("Tailscale", f"{back * 2}{tailnet_address}{back}{share_name}"))
    out += [("Local network", f"{back * 2}{ip}{back}{share_name}") for ip in lan]
    return out


@dataclass
class Addresses:
    """The host parts of the addresses, read once on a thread (Tailscale and the network take a moment)."""
    host: str = ""
    tailnet: str = ""
    lan: list = field(default_factory=list)

    def of(self, share_name: str) -> list:
        return addresses(share_name, self.host, self.tailnet, self.lan)


def this_host() -> str:
    """This computer's name the way others type it (Windows shows it in capitals)."""
    host = socket.gethostname()
    return host.upper() if IS_WINDOWS else host


def read_addresses() -> Addresses:
    """Every address: takes a moment (Tailscale and the network adapters are asked), call it on a thread."""
    return Addresses(this_host(), tailnet_ip(), local_ipv4s(socket.gethostname()))


# making, changing, removing ------------------------------------------------------------------------------------------------------
def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string (a quote inside is doubled)."""
    return "'" + str(text).replace("'", "''") + "'"


def _account_expr(account: str) -> str:
    if account == EVERYONE:
        return "$everyone"
    return ps_quote(account)


def _grant_args(grants: list) -> str:
    by: dict = {READ: [], CHANGE: [], FULL: []}
    for g in grants:
        if not g.denied:
            by[g.access].append(_account_expr(g.account))
    flags = {READ: "-ReadAccess", CHANGE: "-ChangeAccess", FULL: "-FullAccess"}
    return " ".join(f"{flags[k]} @({','.join(v)})" for k, v in by.items() if v)


PS_HEAD = ("$ErrorActionPreference='Stop'; "
           "$everyone=(New-Object Security.Principal.SecurityIdentifier '" + EVERYONE_SID + "')"
           ".Translate([Security.Principal.NTAccount]).Value; ")
PS_RIGHT = {READ: "Read", CHANGE: "Change", FULL: "Full"}


def create_script(name: str, path: str, grants: list, remark: str = "") -> str:
    if not any(not g.denied for g in grants):
        raise ShareError("Say who may use the share.")
    return (PS_HEAD + f"New-SmbShare -Name {ps_quote(name)} -Path {ps_quote(path)} -Description {ps_quote(remark)} "
            f"{_grant_args(grants)} | Out-Null")


def change_script(old_name: str, name: str, path: str, grants: list, remark: str = "") -> str:
    """A new name is a new share (Windows cannot rename one); the same name keeps the share and replaces its allow entries."""
    if not any(not g.denied for g in grants):
        raise ShareError("Say who may use the share.")
    if name.casefold() != old_name.casefold():
        return (create_script(name, path, grants, remark) + "; "
                f"Remove-SmbShare -Name {ps_quote(old_name)} -Force")
    lines = [PS_HEAD.rstrip(),
             f"Set-SmbShare -Name {ps_quote(name)} -Description {ps_quote(remark)} -Force;",
             f"Get-SmbShareAccess -Name {ps_quote(name)} | Where-Object {{ $_.AccessControlType -eq 'Allow' }} | "
             f"ForEach-Object {{ Revoke-SmbShareAccess -Name {ps_quote(name)} -AccountName $_.AccountName -Force | Out-Null }};"]
    for g in grants:
        if not g.denied:
            lines.append(f"Grant-SmbShareAccess -Name {ps_quote(name)} -AccountName {_account_expr(g.account)} "
                         f"-AccessRight {PS_RIGHT[g.access]} -Force | Out-Null;")
    return " ".join(lines)


def remove_script(name: str) -> str:
    return f"$ErrorActionPreference='Stop'; Remove-SmbShare -Name {ps_quote(name)} -Force"


def _powershell(script: str) -> list:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def _wrapped(script: str, result_file: str) -> str:
    """The script with its error, if any, written to ``result_file`` (an elevated process has no output we could read)."""
    return ("try { " + script + "; exit 0 } catch { $_.Exception.Message | Out-File -Encoding utf8 -FilePath "
            + ps_quote(result_file) + "; exit 1 }")


def run_elevated(script: str, start: Optional[Callable] = None) -> None:
    """Run ``script`` in an administrator PowerShell (one UAC prompt) and wait for it. Raises Cancelled when the prompt is refused,
    ShareError with PowerShell's own message when the script fails. ``start`` is a seam for tests: it gets the argument list and
    returns the exit code, or None for a refused prompt."""
    fd, result_file = tempfile.mkstemp(prefix="dossier-share-", suffix=".txt")
    os.close(fd)
    try:
        argv = _powershell(_wrapped(script, result_file))
        code = (start or _start_elevated)(argv)
        if code is None:
            raise Cancelled("Nothing was changed: the administrator prompt was refused.")
        if code != 0:
            try:
                with open(result_file, encoding="utf-8-sig", errors="replace") as f:
                    why = f.read().strip()
            except OSError:
                why = ""
            raise ShareError(why or f"Windows did not make the change (code {code}).")
    finally:
        try:
            os.remove(result_file)
        except OSError:
            pass


def _start_elevated(argv: list) -> Optional[int]:
    import ctypes
    from ctypes import wintypes as w

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", w.HWND), ("lpVerb", w.LPCWSTR), ("lpFile", w.LPCWSTR),
                    ("lpParameters", w.LPCWSTR), ("lpDirectory", w.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", w.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", w.LPCWSTR), ("hkeyClass", w.HKEY), ("dwHotKey", w.DWORD),
                    ("hIconOrMonitor", w.HANDLE), ("hProcess", w.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x400                        # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI
    info.lpVerb = "runas"
    info.lpFile = argv[0]
    info.lpParameters = subprocess.list2cmdline(argv[1:])
    info.nShow = 0                                   # SW_HIDE: only the prompt shows
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.GetLastError() == 1223:            # ERROR_CANCELLED: the owner said no
            return None
        raise ShareError(f"Could not ask for administrator rights: {ctypes.FormatError()}")
    try:
        kernel32.WaitForSingleObject(info.hProcess, TIMEOUT * 1000 * 4)
        code = w.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def _usershare_acl(grants: list) -> str:
    def who(account: str) -> str:
        return "Everyone" if account == EVERYONE else account
    return ",".join(f"{who(g.account)}:{'R' if g.access == READ else 'F'}" for g in grants if not g.denied)


def _run_net(args: list, run: Callable) -> None:
    try:
        done = _net(args, run)
    except (OSError, subprocess.SubprocessError) as e:
        raise ShareError(f"Samba's net program could not be started: {e}") from e
    if done.returncode != 0:
        why = ((done.stderr or "") + (done.stdout or "")).strip()
        raise ShareError(why or "Samba refused the change. Usershares may be switched off on this computer.")


def create(name: str, path: str, grants: list, remark: str = "", start: Optional[Callable] = None,
           run: Callable = subprocess.run) -> None:
    """Share ``path`` as ``name``. Blocks until done (the administrator prompt on Windows): call it on a thread."""
    if IS_WINDOWS:
        run_elevated(create_script(name, path, grants, remark), start)
    else:
        guest = "y" if any(g.account == EVERYONE for g in grants) else "n"
        _run_net(["add", name, path, remark, _usershare_acl(grants), f"guest_ok={guest}"], run)


def change(old_name: str, name: str, path: str, grants: list, remark: str = "", start: Optional[Callable] = None,
           run: Callable = subprocess.run) -> None:
    if IS_WINDOWS:
        run_elevated(change_script(old_name, name, path, grants, remark), start)
        return
    if name != old_name:
        _run_net(["delete", old_name], run)
    create(name, path, grants, remark, run=run)                          # usershare add replaces a share of the same name


def remove(name: str, start: Optional[Callable] = None, run: Callable = subprocess.run) -> None:
    if IS_WINDOWS:
        run_elevated(remove_script(name), start)
    else:
        _run_net(["delete", name], run)
