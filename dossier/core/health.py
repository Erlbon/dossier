"""File health checks, the framework (docs/checkers-plan.md, waves 0 and 1). Qt-free; the window and the command line call the same code.

A checker only reports: it never changes a file. A finding may carry a ``Fix``, which is data (a rename, a delete to the bin) and
becomes an ordinary plan through ``fix_plan``, so it is previewed, runs with progress and cancel, and goes through the same
conflict and undo rules as everything else.

Checkers are cheap first. Tier 0 reads only the listing, tier 1 a few bytes of a file, tier 2 the whole file. ``run_checks`` runs
the tiers up to ``max_tier`` (default 1); a whole-file check is chosen on purpose. A folder is listed once and every checker gets
that listing, so nothing is read twice. It runs on a thread: ``progress(done, found)`` is called now and then and the
``CancelToken`` stops it between folders and files. Links are not followed; a folder that cannot be read is counted and skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Optional, Sequence

from .progress import Cancelled, CancelToken, check
from .vfs import Entry, FileSystem

ERROR, WARNING, INFO = "error", "warning", "info"
SEVERITIES = (ERROR, WARNING, INFO)
T0, T1, T2 = 0, 1, 2
FILE, FOLDER = "file", "folder"


@dataclass(frozen=True)
class Fix:
    """What would put a finding right, as data. ``kind`` is ``rename`` (to ``new_name``), ``delete`` (to the recycle bin) or ``quarantine``
    (into the quarantine folder, from where it can be put back)."""
    kind: str
    label: str
    new_name: str = ""


@dataclass(frozen=True)
class Finding:
    path: str
    checker: str
    rule: str
    severity: str
    message: str
    evidence: str = ""
    fix: Optional[Fix] = None


@dataclass(frozen=True)
class Checker:
    id: str
    name: str
    tier: int
    scope: str                 # FILE: check(ctx, entry); FOLDER: check(ctx, folder, entries)
    check: Callable
    extensions: tuple = ()     # FILE only: lower-case, with the dot; empty means any file


@dataclass
class Context:
    fs: FileSystem
    now: float = 0.0
    cancel: Optional[CancelToken] = None
    roots: tuple = ()          # the folders the run was started on: never reported as empty


_REGISTRY: dict = {}


def register(checker: Checker) -> Checker:
    _REGISTRY[checker.id] = checker
    return checker


def checkers() -> list:
    from . import health_rules  # noqa: F401  (registers the rules on import)
    return list(_REGISTRY.values())


def finding(path: str, checker: str, rule: str, severity: str, message: str, evidence: str = "", fix: Optional[Fix] = None) -> Finding:
    return Finding(path, checker, rule, severity, message, evidence, fix)


@dataclass
class Report:
    findings: list = field(default_factory=list)
    folders: int = 0
    files: int = 0
    unreadable: int = 0        # folders that could not be listed and files that could not be read
    cancelled: bool = False    # the run was stopped (only with ``partial_on_cancel``): what was found until then is here

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


def _walk(fs: FileSystem, root: str, report: Report, cancel: Optional[CancelToken]) -> Iterator[tuple]:
    """``(folder, entries)`` for the root and every folder below it. Links are listed but never entered."""
    stack = [root]
    while stack:
        check(cancel)
        folder = stack.pop()
        try:
            entries = fs.list(folder)
        except OSError:
            report.unreadable += 1
            continue
        report.folders += 1
        yield folder, entries
        stack.extend(e.path for e in reversed(entries) if e.is_dir and not e.is_link)


def run_checks(fs: FileSystem, roots: Sequence[str], *, max_tier: int = T1, only: Optional[Iterable[str]] = None, now: float = 0.0,
               cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int, int], None]] = None,
               partial_on_cancel: bool = False) -> Report:
    """Check the trees under ``roots`` with the registered checkers up to ``max_tier`` (``only``: those ids). A cancel raises ``Cancelled``,
    or with ``partial_on_cancel`` ends the run and returns what was found so far (``report.cancelled``)."""
    import time
    wanted = set(only) if only is not None else None
    active = [c for c in checkers() if c.tier <= max_tier and (wanted is None or c.id in wanted)]
    ctx = Context(fs, now or time.time(), cancel, tuple(roots))
    report = Report()
    file_checkers = [c for c in active if c.scope == FILE]
    folder_checkers = [c for c in active if c.scope == FOLDER]
    try:
        for root in roots:
            for folder, entries in _walk(fs, root, report, cancel):
                for c in folder_checkers:
                    report.findings.extend(c.check(ctx, folder, entries))
                for entry in entries:
                    if entry.is_dir:
                        continue
                    report.files += 1
                    check(cancel)
                    for c in file_checkers:
                        if c.extensions and not entry.name.lower().endswith(c.extensions):
                            continue
                        try:
                            report.findings.extend(c.check(ctx, entry))
                        except OSError:
                            report.unreadable += 1
                    if progress and report.files % 200 == 0:
                        progress(report.files, len(report.findings))
    except Cancelled:
        if not partial_on_cancel:
            raise
        report.cancelled = True
    if progress:
        progress(report.files, len(report.findings))
    report.findings.sort(key=lambda f: (SEVERITIES.index(f.severity), f.path.lower(), f.rule))
    return report


def fix_plan(fs: FileSystem, findings: Sequence[Finding], quarantine=None):
    """One plan that applies the fixes of ``findings`` (those without a fix are left out), or None when nothing can be fixed.
    A rename is a plan step like any other, so it can be undone; a delete goes to the recycle bin; a quarantine moves the file into the
    quarantine folder (``quarantine``: the ``core.quarantine.Settings``, the default when None) and keeps its place in the tree.
    A plan holds one kind of fix: ask once for each kind."""
    from .ops import plan_delete, plan_rename_many
    from . import quarantine as q
    renames = [(f.path, f.fix.new_name) for f in findings if f.fix and f.fix.kind == "rename"]
    deletes = [f.path for f in findings if f.fix and f.fix.kind == "delete"]
    isolate = [f.path for f in findings if f.fix and f.fix.kind == "quarantine"]
    if sum(1 for kind in (renames, deletes, isolate) if kind) > 1:
        raise ValueError("a plan renames, deletes or quarantines, not several: make one plan for each")
    if renames:
        return plan_rename_many(fs, renames)
    if deletes:
        return plan_delete(fs, deletes, to_trash=True)
    if isolate:
        return q.plan_quarantine(fs, isolate, quarantine or q.Settings())
    return None


# what the Health window shows --------------------------------------------------------------------------------------------------------------
@dataclass
class Group:
    rule: str
    severity: str
    findings: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.findings)

    @property
    def fixable(self) -> int:
        return sum(1 for f in self.findings if f.fix)


def group_by_rule(findings: Iterable[Finding]) -> list:
    """The findings grouped by rule: the worst severity first, then the biggest group, then the name. A rule that reports two severities
    is listed under the worse one."""
    groups: dict = {}
    for f in findings:
        g = groups.get(f.rule)
        if g is None:
            g = groups[f.rule] = Group(f.rule, f.severity)
        elif SEVERITIES.index(f.severity) < SEVERITIES.index(g.severity):
            g.severity = f.severity
        g.findings.append(f)
    return sorted(groups.values(), key=lambda g: (SEVERITIES.index(g.severity), -g.count, g.rule))


class IgnoreList:
    """Rules the owner chose to hide below a folder (``Ignore this rule here``). Kept in memory for the session: it names folders, which is user
    data, so nothing is written to disk."""

    def __init__(self) -> None:
        self._rules: set = set()

    def __len__(self) -> int:
        return len(self._rules)

    @staticmethod
    def _key(folder: str) -> str:
        from .platform import path_key
        return path_key(folder).rstrip("/" + chr(92))

    def add(self, folder: str, rule: str) -> None:
        self._rules.add((self._key(folder), rule))

    def clear(self) -> None:
        self._rules.clear()

    def hides(self, finding: Finding) -> bool:
        if not self._rules:
            return False
        here = self._key(finding.path)
        return any(finding.rule == rule and (here == root or here.startswith(root + "/") or here.startswith(root + chr(92)))
                   for root, rule in self._rules)

    def visible(self, findings: Iterable[Finding]) -> list:
        return [f for f in findings if not self.hides(f)]
