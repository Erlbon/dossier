"""Folder rules: a folder's own rules that *propose* a plan (card 68A).

Hazel, on the Mac, files things by rules ("PDFs in Downloads older than 30 days go to Archive/<year>"). Dossier's rules never act alone:
when a folder with rules is opened, or on Tools > Rules > Run Rules, they make a plan, and the owner presses Run as for every plan.

A rule belongs to one folder (this folder only, not its subfolders). It has a *match* (name patterns as in Mark by Pattern, optionally
older than N days by modification time, optionally larger than a size) and an *action*: move or copy to a destination, or delete (to
the recycle bin, as Delete does). The destination may hold ``<year>`` and ``<month>`` (``2026`` and ``03``) of the file's modification
time; a relative destination is below the rule's folder. The first rule that matches a file wins, so a file is proposed once.

Matching works on a listing already read (names, times, sizes): no disk access here. The rules are kept in Dossier's settings, keyed by
folder like the folder layouts (``core/layouts.py``), never as a file in the folder. Qt-free.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .layouts import has_rules_for, key_of
from .patterns import parse
from .platform import is_full_path

ACTIONS = ("move", "copy", "delete")
ACTION_WORDS = {"move": "move", "copy": "copy", "delete": "delete to the recycle bin"}
MAX_FOLDERS = 500
MAX_RULES = 50
DAY = 86400.0
TOKENS = ("<year>", "<month>")


@dataclass(frozen=True)
class FolderRule:
    patterns: str                                # as Mark by Pattern: "*.pdf;*.docx", "*.tmp !keep*", "old*/" for folders
    action: str = "move"                         # move, copy or delete
    dest: str = ""                               # for move and copy; may hold <year> and <month>; relative = below the rule's folder
    older_days: int = 0                          # 0 = any age; else only items last changed more than this many days ago
    larger_than: int = 0                         # bytes; 0 = any size; else only files bigger than this
    id: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)

    def to_json(self) -> dict:
        return {"patterns": self.patterns, "action": self.action, "dest": self.dest, "older_days": self.older_days,
                "larger_than": self.larger_than, "id": self.id}


def problem(rule: FolderRule) -> str:
    """Why ``rule`` cannot be kept ("" when it can)."""
    parsed = parse(rule.patterns)
    if not parsed.include_files and not parsed.include_folders:
        return "Type at least one name pattern, for example *.pdf"
    if rule.action not in ACTIONS:
        return "Choose what to do: move, copy or delete"
    if rule.action != "delete" and not rule.dest.strip():
        return "Say where the files go"
    if rule.older_days < 0 or rule.larger_than < 0:
        return "The age and the size cannot be negative"
    return ""


def describe(rule: FolderRule) -> str:
    """One line for the list of rules: what it matches and what it does."""
    what = rule.patterns.strip()
    if rule.older_days:
        what += f", older than {rule.older_days} day{'s' if rule.older_days != 1 else ''}"
    if rule.larger_than:
        what += f", larger than {_size_text(rule.larger_than)}"
    do = ACTION_WORDS.get(rule.action, rule.action)
    return f"{what}: {do}" + (f" to {rule.dest.strip()}" if rule.action != "delete" else "")


def _size_text(n: int) -> str:
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= size and n % size == 0:
            return f"{n // size} {unit}"
    return f"{n} bytes"


@dataclass(frozen=True)
class Proposal:
    rule: FolderRule
    path: str
    name: str
    is_dir: bool
    size: int
    dest: str                                    # the destination folder, resolved ("" for a delete)

    @property
    def action(self) -> str:
        return self.rule.action


@dataclass(frozen=True)
class Group:
    """Items that one plan handles: the same action into the same folder."""
    action: str
    dest: str
    items: tuple                                 # Proposals

    @property
    def paths(self) -> list:
        return [p.path for p in self.items]


def resolve_dest(rule: FolderRule, folder: str, mtime: float, join: Callable = os.path.join) -> str:
    """The destination folder for an item last changed at ``mtime``: ``<year>`` and ``<month>`` filled in, a relative path put below ``folder``."""
    when = time.localtime(mtime)
    text = rule.dest.strip().replace("<year>", f"{when.tm_year:04d}").replace("<month>", f"{when.tm_mon:02d}")
    if is_full_path(text) or "://" in text or (len(text) > 1 and text[1] == ":"):
        return text
    parts = [p for p in text.replace(chr(92), "/").split("/") if p and p != "."]
    return join(folder, *parts) if parts else folder


def proposals(rules: Iterable, entries: Iterable, folder: str, now: float, *, join: Callable = os.path.join,
              case_sensitive: bool = False) -> list:
    """What ``rules`` would do with ``entries`` (the listing of ``folder``), as Proposals in the listing's order. The first rule that
    matches an item wins. Links are never touched. An item with no known date is left alone by a rule that needs the date (an age, or
    <year> or <month> in the destination)."""
    compiled = []
    for rule in rules:
        if problem(rule):
            continue
        needs_date = bool(rule.older_days) or (rule.action != "delete" and any(t in rule.dest for t in TOKENS))
        compiled.append((rule, parse(rule.patterns, case_sensitive=case_sensitive), needs_date))
    found: list = []
    if not compiled:
        return found
    for e in entries:
        if getattr(e, "is_link", False) or getattr(e, "kind", ""):
            continue
        for rule, patterns, needs_date in compiled:
            if not patterns.matches(e.name, bool(e.is_dir)):
                continue
            if needs_date and e.mtime <= 0:
                continue
            if rule.older_days and now - e.mtime < rule.older_days * DAY:
                continue
            if rule.larger_than and (e.is_dir or e.size <= rule.larger_than):
                continue
            dest = "" if rule.action == "delete" else resolve_dest(rule, folder, e.mtime, join)
            found.append(Proposal(rule, e.path, e.name, bool(e.is_dir), int(e.size or 0), dest))
            break
    return found


def groups(found: Iterable) -> list:
    """The proposals grouped per action and destination, in the order the first of each appeared."""
    order: dict = {}
    for p in found:
        order.setdefault((p.action, key_of(p.dest) if p.dest else ""), []).append(p)
    return [Group(key[0], items[0].dest, tuple(items)) for key, items in order.items()]


def summary(found: Iterable) -> str:
    """"move 3 items, copy 1 item and delete 2 items" for a hint, or "" when there is nothing."""
    counts: dict = {}
    for p in found:
        counts[p.action] = counts.get(p.action, 0) + 1
    parts = [f"{a} {counts[a]} item{'s' if counts[a] != 1 else ''}" for a in ACTIONS if a in counts]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# storage -----------------------------------------------------------------------------------------------------------------------
class RuleStore:
    """The rules of every folder that has any, keyed like the folder layouts. Plain data, JSON in the settings file."""

    def __init__(self) -> None:
        self._folders: dict = {}                 # key -> (path, [FolderRule])

    def __len__(self) -> int:
        return len(self._folders)

    def folders(self) -> list:
        return [path for path, _rules in self._folders.values()]

    def rules_for(self, folder: str) -> list:
        if not has_rules_for(folder):
            return []
        return list(self._folders.get(key_of(folder), ("", []))[1])

    def set_rules(self, folder: str, rules: Iterable) -> None:
        """Replace the rules of ``folder`` (none: forget the folder). Rules that cannot be kept are dropped."""
        if not has_rules_for(folder):
            return
        kept = [r for r in rules if not problem(r)][:MAX_RULES]
        key = key_of(folder)
        if not kept:
            self._folders.pop(key, None)
            return
        self._folders.pop(key, None)             # a changed folder goes to the end: the oldest go first
        self._folders[key] = (os.path.normpath(folder), kept)
        while len(self._folders) > MAX_FOLDERS:
            self._folders.pop(next(iter(self._folders)))

    def to_json(self) -> str:
        return json.dumps([{"path": path, "rules": [r.to_json() for r in rules]} for path, rules in self._folders.values()],
                          ensure_ascii=False)

    @classmethod
    def from_json(cls, text) -> "RuleStore":
        """A damaged or foreign text is an empty store, never an error."""
        store = cls()
        try:
            items = json.loads(text) if isinstance(text, str) and text.strip() else []
        except ValueError:
            return store
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            rules = [r for r in (rule_from_json(d) for d in item.get("rules") or []) if r is not None]
            store.set_rules(item["path"], rules)
        return store


def rule_from_json(data) -> Optional[FolderRule]:
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), str):
        return None
    try:
        return FolderRule(data["patterns"], str(data.get("action", "move")), str(data.get("dest", "")), int(data.get("older_days", 0)),
                          int(data.get("larger_than", 0)), str(data.get("id") or uuid.uuid4().hex))
    except (TypeError, ValueError):
        return None
