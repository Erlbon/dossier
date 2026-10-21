"""What the owner allows an assistant to do, in a small JSON file the window writes and the server reads. Everything is off by default."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import paths

MAX_ROOTS = 50
MIN_READ_KB, MAX_READ_KB = 4, 1024


@dataclass
class AssistantConfig:
    enabled: bool = False                         # the master switch: nothing works while it is off
    roots: list = field(default_factory=list)     # the only folders an assistant may look into (and below)
    allow_file_changes: bool = False              # may it propose copying, moving, renaming, deleting (each still needs the owner's OK)
    log_calls: bool = True                        # keep a log of every call (X5)
    max_read_kb: int = 256                        # the most of a file's text one call returns

    def cleaned(self) -> "AssistantConfig":
        roots = []
        for r in self.roots:
            if isinstance(r, str) and r.strip() and os.path.isabs(r) and r not in roots:
                roots.append(os.path.normpath(r))
        return AssistantConfig(bool(self.enabled), roots[:MAX_ROOTS], bool(self.allow_file_changes), bool(self.log_calls),
                               max(MIN_READ_KB, min(MAX_READ_KB, int(self.max_read_kb or 256))))


def load(path: str = "") -> AssistantConfig:
    """The saved choices; a missing, damaged or foreign file is everything off (never an error)."""
    try:
        with open(path or paths.config_file(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return AssistantConfig()
        return AssistantConfig(bool(data.get("enabled")), list(data.get("roots") or []), bool(data.get("allow_file_changes")),
                               bool(data.get("log_calls", True)), int(data.get("max_read_kb", 256))).cleaned()
    except (OSError, ValueError, TypeError):
        return AssistantConfig()


def save(config: AssistantConfig, path: str = "") -> None:
    target = path or paths.config_file()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config.cleaned().__dict__, f, indent=2, ensure_ascii=False)
    os.replace(tmp, target)
