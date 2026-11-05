"""Turning an assistant's request into plans, the same way wherever it runs (Qt-free).

The window does it when the owner is asked to press Run; the server does it itself when the owner switched on "Let the assistant carry out
its own plans without asking" (card 33 of the review of 2026-11-05). Both check every path against the listed folders again, here, at the
moment of the change. For the server's own runs, ``unattended`` adds the guard rails: a conflict is never overwritten (that step is left
out and reported), a step that would replace a file is left out too, and a delete that cannot go to a recycle bin is refused as a whole
(it still needs the owner's Run).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..core import compare as cmp, sync as sync_core
from ..core.ops import Kind, Plan, Resolution, bad_relative, plan_copy, plan_copy_paths, plan_delete, plan_move, plan_rename
from .scope import Denied, Scope

ACTIONS = ("copy", "copy_paths", "move", "delete", "rename", "sync")
POLICIES = {"skip": Resolution.SKIP, "overwrite": Resolution.OVERWRITE, "keep-both": Resolution.KEEP_BOTH, "newer": Resolution.OVERWRITE_IF_NEWER}


class Refused(Exception):
    """The request cannot be carried out as asked; the text says why."""


@dataclass
class Prepared:
    plans: list
    left_out: list = field(default_factory=list)       # (path, why) of steps an unattended run leaves out


def checked_paths(payload: dict, roots: list) -> dict:
    """The request's paths, each checked against the listed folders (raises Denied)."""
    action = payload.get("action")
    full = ("source_root", "destination_root") if action == "copy_paths" else ("sources", "destination", "paths", "path", "left", "right")
    scope = Scope(roots)
    checked = {k: (scope.all(v) if isinstance(v, list) else scope.resolve(v)) for k, v in payload.items() if k in full}
    if action == "copy_paths":
        rels = payload.get("paths")
        bad = [w for w in (bad_relative(r) for r in rels) if w] if isinstance(rels, list) else ["paths must be a list"]
        if bad or not rels:
            raise Denied("; ".join(bad[:3]) or "there is nothing to copy")
    return checked


def build_plans(fs, payload: dict, roots: list, watch=None, unattended: bool = False) -> Prepared:
    """The plans for ``payload``. Raises Denied (a path outside the listed folders) or Refused."""
    action = payload.get("action")
    if action not in ACTIONS:
        raise Refused("unknown kind of change")
    checked = checked_paths(payload, roots)
    if action == "copy_paths":
        plans = [plan_copy_paths(fs, checked["source_root"], checked["destination_root"], payload["paths"], watch=watch)]
    elif action == "copy":
        plans = [plan_copy(fs, checked["sources"], checked["destination"], watch=watch)]
    elif action == "move":
        plans = [plan_move(fs, checked["sources"], checked["destination"], watch=watch)]
    elif action == "delete":
        plans = [plan_delete(fs, checked["paths"], to_trash=not payload.get("permanent"))]
    elif action == "rename":
        plans = [plan_rename(fs, checked["path"], str(payload.get("new_name", "")))]
    else:
        result = cmp.compare_trees(fs, checked["left"], checked["right"], by=payload.get("by") or "size_time")
        actions = [a for a in sync_core.decide_all(result.rows, payload.get("mode", "")) if a.kind]
        plans = sync_core.build_plans(fs, checked["left"], checked["right"], actions)
    policy = Resolution.SKIP if unattended else POLICIES.get(payload.get("on_conflict") or "skip", Resolution.SKIP)
    out, left_out = [], []
    for plan in plans:
        if plan.conflicts:
            left_out += [(plan.ops[i].dst, plan.ops[i].conflict) for i in plan.conflicts] if unattended else []
            if action in ("copy", "copy_paths", "move"):
                plan = plan.resolve(policy, fs)
            if plan.conflicts:
                plan = plan.resolve(Resolution.SKIP, fs)
        if unattended:
            plan, dropped = _without_replacing(plan)
            left_out += dropped
            permanent = [op.src for op in plan.ops if op.kind is Kind.DELETE and not op.to_trash]
            if permanent:
                raise Refused("a delete that cannot go to a recycle bin (a server, a network drive, a USB stick, or asked as permanent) "
                              f"always needs the owner's Run in the Dossier window: {permanent[0]}")
            _all_inside(plan, roots)
        out.append(plan)
    return Prepared(out, left_out)


def _without_replacing(plan: Plan) -> tuple:
    """The plan without the steps that would replace an existing file (an unattended run never overwrites)."""
    keep, dropped = [], []
    for op in plan.ops:
        if op.overwrite:
            dropped.append((op.dst, "would replace an existing file"))
        else:
            keep.append(op)
    return (replace(plan, ops=tuple(keep)), dropped) if dropped else (plan, [])


def _all_inside(plan: Plan, roots: list) -> None:
    """Every place an unattended run touches lies inside the listed folders (raises Denied)."""
    scope = Scope(roots)
    for op in plan.ops:
        for path in (op.src, op.dst):
            if path:
                scope.resolve(path)
