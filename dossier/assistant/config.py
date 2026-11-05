"""What the owner allows an assistant to do, in a small JSON file the window writes and the server reads. Everything is off by default."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import paths
from ..core.platform import is_full_path

MAX_ROOTS = 50
MIN_READ_KB, MAX_READ_KB = 4, 1024
SERVER_SCHEMES = ("sftp", "scp")                  # server folders an assistant may be given (over SSH, with a host key the owner approved)


def server_root(text: str) -> str:
    """``text`` as a server folder root (``sftp://user@host:22/F:/Maritime``, normalised), or "" when it is not one."""
    from posixpath import normpath
    if not isinstance(text, str) or "://" not in text:
        return ""
    scheme, rest = text.split("://", 1)
    if scheme not in SERVER_SCHEMES or not rest or rest.startswith("/"):
        return ""
    authority, _, remote = rest.partition("/")
    if not authority or any(c in authority for c in " \\") or ".." in remote.split("/"):
        return ""
    remote = normpath("/" + remote) if remote else "/"
    return f"{scheme}://{authority}{remote}"


@dataclass
class AssistantConfig:
    enabled: bool = False                         # the master switch: nothing works while it is off
    roots: list = field(default_factory=list)     # the only folders an assistant may look into (and below); local, or sftp:// and scp://
    allow_file_changes: bool = False              # may it propose copying, moving, renaming, deleting (each still needs the owner's OK)
    log_calls: bool = True                        # keep a log of every call (X5)
    max_read_kb: int = 256                        # the most of a file's text one call returns
    servers: list = field(default_factory=list)   # the saved connections (no secrets) of the server roots, as the window has them
    ssh_folder: str = ""                          # the window's SSH folder: its known_hosts holds the host keys the owner approved
    act_unattended: bool = False                  # carry out its own plans without the owner's Run (only with allow_file_changes; guard rails
                                                  # in assistant/planning.py: no overwrite, no permanent delete, inside the roots)

    def cleaned(self) -> "AssistantConfig":
        roots = []
        for r in self.roots:
            if not isinstance(r, str) or not r.strip():
                continue
            r = server_root(r) or (os.path.normpath(r) if is_full_path(r) and "://" not in r else "")
            if r and r not in roots:
                roots.append(r)
        servers = [s for s in (self.servers or []) if isinstance(s, dict)][:MAX_ROOTS]
        return AssistantConfig(bool(self.enabled), roots[:MAX_ROOTS], bool(self.allow_file_changes), bool(self.log_calls),
                               max(MIN_READ_KB, min(MAX_READ_KB, int(self.max_read_kb or 256))), servers,
                               self.ssh_folder if isinstance(self.ssh_folder, str) and self.ssh_folder and is_full_path(self.ssh_folder) else "",
                               bool(self.act_unattended and self.allow_file_changes))


def load(path: str = "") -> AssistantConfig:
    """The saved choices; a missing, damaged or foreign file is everything off (never an error)."""
    try:
        with open(path or paths.config_file(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return AssistantConfig()
        return AssistantConfig(bool(data.get("enabled")), list(data.get("roots") or []), bool(data.get("allow_file_changes")),
                               bool(data.get("log_calls", True)), int(data.get("max_read_kb", 256)), list(data.get("servers") or []),
                               str(data.get("ssh_folder") or ""), bool(data.get("act_unattended"))).cleaned()
    except (OSError, ValueError, TypeError):
        return AssistantConfig()


def save(config: AssistantConfig, path: str = "") -> None:
    target = path or paths.config_file()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config.cleaned().__dict__, f, indent=2, ensure_ascii=False)
    os.replace(tmp, target)
