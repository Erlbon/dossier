"""Where the assistant's files live. Both the window and the server compute it the same way, without Qt, so they meet in the same folder."""
from __future__ import annotations

import os
import sys

ENV = "DOSSIER_ASSISTANT_DIR"                 # tests, and anyone who wants it elsewhere


def data_dir() -> str:
    override = os.environ.get(ENV)
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "Dossier", "assistant")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Dossier", "assistant")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "dossier", "assistant")


def config_file() -> str:
    return os.path.join(data_dir(), "config.json")


def state_file() -> str:
    return os.path.join(data_dir(), "state.json")


def requests_dir() -> str:
    return os.path.join(data_dir(), "requests")


def responses_dir() -> str:
    return os.path.join(data_dir(), "responses")


def log_file() -> str:
    return os.path.join(data_dir(), "calls.log")


def away_file() -> str:
    """What the assistant carried out on its own (Settings > Assistant Access > without asking): one JSON line per change, which the
    window shows the owner as "done while you were away"."""
    return os.path.join(data_dir(), "done-unattended.jsonl")


def reports_dir() -> str:
    """Manifests and comparison reports the assistant's tools write. They go here, never into the owner's folders, so writing one is not
    a change to files and needs no permission."""
    return os.path.join(data_dir(), "reports")
