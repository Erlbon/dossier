"""What git knows about a folder that already is (or is inside) a git repository: the branch, and which items are changed, new, staged,
ignored or in conflict. For the panel's bar and the Git column (git awareness plan, 2026-11-07, cards 1-4).

**Read-only, always.** Dossier never creates, commits, stages, syncs or restores: it runs the ``git`` that is installed (Git for Windows),
as it runs 7-Zip, and only commands that read. ``status`` normally refreshes git's index file as a side effect; ``--no-optional-locks``
(and ``GIT_OPTIONAL_LOCKS=0``) turn that off, so looking never changes a repository. When git is not installed nothing is shown and
nothing asks for it; a repository git refuses (a share owned by another user: ``safe.directory``) is reported in one plain line.

Calls run git and wait for it, so the window calls them on a thread. Answers are kept a few seconds per repository, so moving between
its folders asks git once. Qt-free.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .platform import IS_WINDOWS, has_scheme

TIMEOUT = 15.0              # seconds git may take to answer before the panel gives up on it
CACHE_SECONDS = 3.0
STATES = ("conflict", "changed", "staged", "new", "ignored")      # strongest first: a folder shows the strongest state below it
LABELS = {"conflict": "Conflict", "changed": "Changed", "staged": "Staged", "new": "New", "ignored": "Ignored", "": ""}
_RANK = {s: i for i, s in enumerate(STATES)}


class GitError(Exception):
    """git answered with an error; the message says it in plain words."""


@dataclass
class GitStatus:
    root: str
    branch: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    states: dict = field(default_factory=dict)      # path relative to the root, with "/" ("docs/a.md"; a whole folder ends in "/")
    _folders: Optional[dict] = None                  # folder (relative, no "/" at the end) -> strongest state below it

    def counts(self) -> dict:
        out = {s: 0 for s in STATES}
        for state in self.states.values():
            out[state] += 1
        return out


# finding git and the repository ---------------------------------------------------------------------------------------------------------
_program: dict = {}


def git_program(which: Callable = shutil.which) -> str:
    """The installed git ("" when there is none), found once: on PATH, else where Git for Windows installs itself."""
    if "path" not in _program:
        found = which("git") or ""
        if not found and IS_WINDOWS:
            for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramW6432", ""), os.environ.get("LOCALAPPDATA", "")):
                for candidate in (os.path.join(base, "Git", "cmd", "git.exe"), os.path.join(base, "Programs", "Git", "cmd", "git.exe")):
                    if base and os.path.isfile(candidate):
                        found = candidate
                        break
                if found:
                    break
        _program["path"] = found
    return _program["path"]


def find_root(path: str, exists: Callable[[str], bool] = os.path.exists) -> Optional[str]:
    """The repository ``path`` is in: the nearest folder at or above it holding ``.git`` (a folder, or a file in a worktree or a
    submodule). None for anything else, and for a server or an archive path."""
    if not path or has_scheme(path):
        return None
    here = os.path.abspath(path)
    while True:
        if exists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


# reading ---------------------------------------------------------------------------------------------------------------------------------
def status_command(git: str, root: str) -> list:
    return [git, "-C", root, "--no-optional-locks", "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal",
            "--ignored=traditional"]


def _run(argv: list) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    return subprocess.run(argv, capture_output=True, timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL, creationflags=flags)


def read_status(root: str, git: Optional[str] = None, runner: Callable = _run) -> GitStatus:
    """``git status`` of the repository at ``root``. GitError with a plain reason when git refuses or fails."""
    git = git if git is not None else git_program()
    if not git:
        raise GitError("git is not installed")
    try:
        done = runner(status_command(git, root))
    except subprocess.TimeoutExpired:
        raise GitError(f"git took longer than {TIMEOUT:.0f} seconds to answer") from None
    except OSError as e:
        raise GitError(f"git could not be started: {e.strerror or e}") from None
    if done.returncode != 0:
        raise GitError(_reason(done.stderr.decode("utf-8", "replace")))
    return parse_status(done.stdout.decode("utf-8", "replace"), root)


def _reason(stderr: str) -> str:
    if "dubious ownership" in stderr or "safe.directory" in stderr:
        return "git does not trust this folder (it belongs to another user); git config --global --add safe.directory lets it"
    first = next((line.strip() for line in stderr.splitlines() if line.strip()), "")
    return first.removeprefix("fatal: ") or "git could not read this repository"


def parse_status(raw: str, root: str) -> GitStatus:
    """``git status --porcelain=v2 --branch -z``: the branch headers, then one record per changed, new or ignored item."""
    st = GitStatus(root=root)
    records = raw.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        kind = rec[0]
        if kind == "#":
            _header(st, rec)
        elif kind == "1":                                  # 1 XY sub mH mI mW hH hI path
            parts = rec.split(" ", 8)
            if len(parts) == 9:
                st.states[parts[8]] = _xy_state(parts[1])
        elif kind == "2":                                  # 2 XY sub mH mI mW hH hI Xscore path, then the old path as the next record
            parts = rec.split(" ", 9)
            if len(parts) == 10:
                st.states[parts[9]] = _xy_state(parts[1])
            i += 1
        elif kind == "u":                                  # u XY sub m1 m2 m3 mW h1 h2 h3 path
            parts = rec.split(" ", 10)
            if len(parts) == 11:
                st.states[parts[10]] = "conflict"
        elif kind == "?":
            st.states[rec[2:]] = "new"
        elif kind == "!":
            st.states[rec[2:]] = "ignored"
    return st


def _header(st: GitStatus, rec: str) -> None:
    key, _sp, value = rec[2:].partition(" ")
    if key == "branch.head":
        st.branch = "" if value == "(detached)" else value
    elif key == "branch.upstream":
        st.upstream = value
    elif key == "branch.ab":
        for word in value.split():
            if word.startswith("+") and word[1:].isdigit():
                st.ahead = int(word[1:])
            elif word.startswith("-") and word[1:].isdigit():
                st.behind = int(word[1:])


def _xy_state(xy: str) -> str:
    """XY: the index's change, then the working tree's ("." = none). A change not yet staged is "changed"; only staged is "staged"."""
    index, tree = (xy + "..")[:2]
    return "changed" if tree != "." else "staged" if index != "." else ""


# per item --------------------------------------------------------------------------------------------------------------------------------
def relative(st: GitStatus, path: str) -> Optional[str]:
    """``path`` relative to the repository, with "/" ("" for the root); None when it is not inside it."""
    try:
        rel = os.path.relpath(path, st.root)
    except ValueError:                                     # another drive
        return None
    rel = rel.replace(os.sep, "/")
    if rel == ".":
        return ""
    return None if rel == ".." or rel.startswith("../") else rel


def _folders(st: GitStatus) -> dict:
    """Every folder with something inside it, and the strongest state below it (an ignored item does not colour its folder)."""
    if st._folders is None:
        out: dict = {}
        for rel, state in st.states.items():
            if state == "ignored" or not state:
                continue
            parts = rel.rstrip("/").split("/")[:-1]
            for n in range(len(parts) + 1):
                key = "/".join(parts[:n])
                if key not in out or _RANK[state] < _RANK[out[key]]:
                    out[key] = state
        st._folders = out
    return st._folders


def state_of(st: GitStatus, path: str, is_dir: bool) -> str:
    """The state shown for one item: "changed", "staged", "new", "conflict", "ignored", or "" (unchanged, or not in the repository)."""
    rel = relative(st, path)
    if rel is None or rel == ".git" or rel.startswith(".git/"):
        return ""
    if is_dir:
        own = st.states.get(rel + "/")                     # a whole new or ignored folder
        if own:
            return own
    elif rel in st.states:
        return st.states[rel]
    for whole, state in st.states.items():                 # inside a whole new or ignored folder
        if whole.endswith("/") and rel.startswith(whole):
            return state
    return _folders(st).get(rel, "") if is_dir else ""


def summary(st: GitStatus) -> str:
    """For the panel's bar: "main · 3 changed, 1 new · 2 ahead"; "main · clean" when nothing changed."""
    c = st.counts()
    parts = [f"{c['conflict']:,} in conflict" if c["conflict"] else "", f"{c['changed']:,} changed" if c["changed"] else "",
             f"{c['staged']:,} staged" if c["staged"] else "", f"{c['new']:,} new" if c["new"] else ""]
    what = ", ".join(p for p in parts if p) or "clean"
    text = f"{st.branch or 'detached'} · {what}"
    sync = ", ".join(p for p in (f"{st.ahead} ahead" if st.ahead else "", f"{st.behind} behind" if st.behind else "") if p)
    return f"{text} · {sync}" if sync else text


def details(st: GitStatus) -> str:
    """The tooltip: where the repository is and what the counts mean."""
    upstream = f" (tracking {st.upstream})" if st.upstream else " (no remote branch)"
    return f"Git repository {st.root}\nBranch {st.branch or 'none: a detached commit'}{upstream}\n{summary(st)}\nRead only: Dossier never changes the repository."


# kept for a few seconds per repository ---------------------------------------------------------------------------------------------------
class StatusCache:
    def __init__(self, seconds: float = CACHE_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds, self.clock = seconds, clock
        self._kept: dict = {}
        self._lock = threading.Lock()

    def get(self, root: str, read: Callable[[str], GitStatus] = read_status) -> GitStatus:
        key = os.path.normcase(root)
        with self._lock:
            kept = self._kept.get(key)
            if kept is not None and self.clock() - kept[0] < self.seconds:
                return kept[1]
        st = read(root)
        with self._lock:
            self._kept[key] = (self.clock(), st)
        return st

    def forget(self, root: str = "") -> None:
        with self._lock:
            if root:
                self._kept.pop(os.path.normcase(root), None)
            else:
                self._kept.clear()


SHARED_CACHE = StatusCache()
