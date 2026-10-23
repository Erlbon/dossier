"""The ``link`` and ``touch`` commands: links of three kinds, and the dates and attributes of many items. Shells around ``core/links.py`` and
``core/filetimes.py``; the rules every command follows are in ``dossier/cli/__init__.py``."""
from __future__ import annotations

import os
import re
from dataclasses import replace

from redactor_common.cli import EXIT_OK, EXIT_PARTIAL, CliError

from ..core import filetimes as ft, links
from .helpers import date_text, need_paths, parse_date

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def duration(text: str) -> float:
    """``+2h``, ``-1d``, ``1d2h30m15s`` as seconds."""
    m = re.fullmatch(r"\s*([+-]?)((?:\d+(?:\.\d+)?[dhms])+)\s*", text or "")
    if not m:
        raise CliError(f"not a time difference: {text!r} (use +2h, -1d, 1d2h30m)")
    total = sum(float(n) * _UNITS[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)([dhms])", m.group(2)))
    return -total if m.group(1) == "-" else total


def cmd_link(args, out, fs) -> int:
    target = os.path.abspath(args.target)
    link = os.path.abspath(args.link)
    if os.path.isdir(link):                                    # an existing folder: the link goes inside it, named after its target
        link = os.path.join(link, links.default_link_name(target, args.kind))
    try:
        links.create(args.kind, target, link, relative=args.relative)
    except links.LinkError as e:
        raise CliError(str(e)) from e
    out.record({"link": link, "target": target, "kind": args.kind, "stored": links.inspect(link).target})
    out.line(f"made {args.kind}: {link}  ->  {target}")
    out.finish({"command": "link", "kind": args.kind})
    return EXIT_OK


def _rule(args):
    if args.set:
        return ft.Rule(ft.SET, when=parse_date(args.set))
    if args.shift:
        return ft.Rule(ft.SHIFT, seconds=duration(args.shift))
    if args.from_file:
        source = os.path.abspath(args.from_file)
        if not os.path.exists(source):
            raise CliError(f"not found: {args.from_file}")
        return ft.Rule(ft.FROM_FILE, source=source)
    if args.from_exif:
        return ft.Rule(ft.FROM_EXIF)
    if args.copy_from:
        return ft.Rule(ft.COPY_FIELD, source_field=args.copy_from)
    return None


def cmd_touch(args, out, fs) -> int:
    paths = need_paths(args.paths)
    on = [f for f in ft.FLAGS if getattr(args, f) == "on"]
    off = [f for f in ft.FLAGS if getattr(args, f) == "off"]
    rule = _rule(args)
    if rule is None and not (on or off):
        raise CliError("nothing to change: give a date (--set, --shift, --from-file, --from-exif, --copy-from) or an attribute (--readonly on)")
    which = [f for f in ft.FIELDS if getattr(args, f)] or ["modified"]
    merged: dict = {}
    try:
        if rule is not None:
            for c in ft.plan_times(paths, rule, which, recursive=args.recursive, include_folders=not args.no_folders):
                merged[c.path] = c
        if on or off:
            for c in ft.plan_flags(paths, set_on=on, set_off=off, recursive=args.recursive, include_folders=not args.no_folders):
                base = merged.get(c.path)
                merged[c.path] = c if base is None else base if base.problem else replace(base, old_flags=c.old_flags, new_flags=c.new_flags)
    except ft.TimeError as e:
        raise CliError(str(e)) from e
    plan = list(merged.values())
    code = EXIT_OK
    for c in plan:
        if c.problem:
            out.error(f"{c.path}: {c.problem}")
            code = EXIT_PARTIAL
        elif c.changes:
            parts = [f"{n} {date_text(getattr(c.old, n))} -> {date_text(getattr(c.new, n))}" for n in ft.FIELDS if getattr(c.new, n) != getattr(c.old, n)]
            if c.flags_change:
                parts.append(f"attributes {', '.join(c.old_flags) or 'none'} -> {', '.join(c.new_flags) or 'none'}")
            out.record({"path": c.path, "old": c.old.__dict__, "new": c.new.__dict__, "old_flags": list(c.old_flags), "new_flags": list(c.new_flags)})
            out.line(f"{c.path}: " + "; ".join(parts))
    todo = sum(1 for c in plan if c.changes)
    if args.dry_run:
        out.line(f"{todo:,} item{'s' if todo != 1 else ''} would change (nothing was done: --dry-run)")
        out.finish({"command": "touch", "dry_run": True, "items": todo})
        return code
    result = ft.apply(plan)
    for path, why in result.failed:
        out.error(f"{path}: {why}")
    out.line(f"changed {result.done:,} item{'s' if result.done != 1 else ''}" + (f", {len(result.failed)} failed" if result.failed else ""))
    out.finish({"command": "touch", "done": result.done, "failed": len(result.failed)})
    return EXIT_PARTIAL if result.failed else code
