"""The commands of Dossier's command line. Each is a thin shell around the core functions the window uses; see ``dossier/cli/__init__.py``
for the rules they all follow (``--dry-run``, never overwrite, the recycle bin, ``--json``, exit codes)."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from redactor_common.cli import (EXIT_INTERRUPTED, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, CliError, Output, add_common_options,
                                 make_output)

from ..core import checksums, compare as cmp, duplicates as dup, sync, zipfs
from ..core.ops import ExecOptions, Kind, Resolution, default_trash, execute, plan_copy, plan_delete, plan_move
from ..core.progress import Cancelled
from ..core.search import BadCriteria, Criteria, search
from ..core.sizefmt import human_size
from ..core.version import APP_NAME, APP_VERSION, RELEASE
from . import COMMANDS
from .helpers import (date_text, entry_row, make_fs, need_paths, one_folder, op_line, parse_date, parse_size, path_arguments, sort_entries)

POLICIES = {"skip": Resolution.SKIP, "overwrite": Resolution.OVERWRITE, "keep-both": Resolution.KEEP_BOTH,
            "newer": Resolution.OVERWRITE_IF_NEWER}
STATUS_WORDS = {cmp.ONLY_LEFT: "only-left", cmp.ONLY_RIGHT: "only-right", cmp.LEFT_NEWER: "left-newer", cmp.RIGHT_NEWER: "right-newer",
                cmp.DIFFERENT: "different", cmp.TYPE: "type-differs", cmp.SAME: "same"}


# the parser -------------------------------------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dossier", description=f"{APP_NAME} on the command line. With no command (or with a folder) the window starts.",
        epilog="What changes files can be previewed with --dry-run. Nothing is overwritten unless --on-conflict overwrite says so; what is "
               "deleted or replaced goes to the recycle bin. --json prints one JSON document on stdout; progress and warnings go to stderr. "
               "Exit codes: 0 all went well, 1 some items failed, 2 a mistake in the command or a path that does not exist.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {RELEASE} (build {APP_VERSION})")
    sub = parser.add_subparsers(dest="command", metavar="command")

    def command(name: str, text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=text, description=text)
        add_common_options(p)
        return p

    p = command("ls", "list a folder, or what is inside an archive file")
    p.add_argument("path", nargs="?", default=".", help="the folder or archive (default: the current folder)")
    p.add_argument("-l", "--long", action="store_true", help="a line with size and date for each item")

    p = command("info", "everything Dossier knows about files and folders: size, times, tags, and what is inside (audio, comic, video, photo)")
    p.add_argument("paths", nargs="+", metavar="path")
    p.add_argument("--bytes", action="store_true", help="sizes in bytes, not in K, M, G")

    p = command("find", "search a folder tree by name, size, date and text; prints one path per line")
    p.add_argument("folder", help="where to look")
    p.add_argument("--name", default="", help="names to find: 'report', '*.jpg;*.png', or '!*.tmp' to leave out")
    p.add_argument("--text", default="", help="the file must contain this text")
    p.add_argument("--regex", action="store_true", help="--text is a regular expression")
    p.add_argument("--case", action="store_true", help="match upper and lower case exactly")
    p.add_argument("--kind", choices=("files", "folders", "both"), default="files", help="what to find (default files)")
    p.add_argument("--min-size", metavar="SIZE", help="at least this big (10K, 1.5M, 2G)")
    p.add_argument("--max-size", metavar="SIZE", help="at most this big")
    p.add_argument("--newer", metavar="DATE", help="changed on or after this day (2024-05-17 or 2024-05-17 10:30)")
    p.add_argument("--older", metavar="DATE", help="changed on or before this day")
    p.add_argument("--no-subfolders", action="store_true", help="only this folder")
    p.add_argument("--tag", action="append", default=[], help="the file carries this tag (repeat for several)")
    p.add_argument("--limit", type=int, default=100000, help="stop after this many results")

    p = command("checksum", "checksums of files (SHA-256 by default), in the format of sha256sum; or check files against such a list")
    p.add_argument("paths", nargs="*", metavar="path")
    p.add_argument("-a", "--algorithm", choices=checksums.ALGORITHMS, default="sha256")
    p.add_argument("--check", metavar="LISTFILE", help="verify the files named in a list of 'hash *name' lines (names are relative to the list)")

    for name, text in (("copy", "copy files and folders into a folder"), ("move", "move files and folders into a folder")):
        p = command(name, text)
        p.add_argument("paths", nargs="+", metavar="path", help="the sources, then the destination folder last")
        p.add_argument("--on-conflict", choices=sorted(POLICIES), default="skip", help="when the name is taken (default skip: nothing is overwritten)")
        p.add_argument("--create", action="store_true", help="make the destination folder if it does not exist")
        p.add_argument("--dry-run", action="store_true", help="show what would happen and do nothing")
        if name == "copy":
            p.add_argument("--verify", action="store_true", help="read every copy back and compare it with the original")

    p = command("delete", "delete files and folders to the recycle bin")
    p.add_argument("paths", nargs="+", metavar="path")
    p.add_argument("--permanent", action="store_true", help="delete for good instead (it cannot be brought back)")
    p.add_argument("--dry-run", action="store_true", help="show what would be deleted and do nothing")

    p = command("dups", "find files with exactly the same content (by size, then the ends, then the whole file)")
    p.add_argument("folders", nargs="+", metavar="folder", help="where to look (several folders find what is in both)")
    p.add_argument("--min-size", metavar="SIZE", default="1", help="ignore smaller files (default 1 byte: empty files are never duplicates)")
    p.add_argument("--name", default="", help="only files with these names ('*.jpg;*.png')")
    p.add_argument("--keep", choices=[k for k, _t in dup.KEEP_POLICIES], default="oldest", help="which copy of each group stays (default the oldest)")
    p.add_argument("--delete", action="store_true", help="delete the other copies of every group to the recycle bin (one copy always stays)")
    p.add_argument("--dry-run", action="store_true", help="with --delete: show what would be deleted and do nothing")

    p = command("compare", "compare two folders; with --sync also make them alike")
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("--by", choices=[k for k, _t in cmp.BY], default="size_time", help="how two files are told apart (default size_time)")
    p.add_argument("--no-subfolders", action="store_true", help="only the top level of each folder")
    p.add_argument("--tolerance", type=float, default=2.0, metavar="SECONDS", help="times this close are the same time (default 2)")
    p.add_argument("--exact-hour", action="store_true", help="a difference of exactly one hour is a difference (default: summer time is ignored)")
    p.add_argument("--same", action="store_true", help="also list the files that are alike")
    p.add_argument("--sync", choices=[k for k, _t in sync.MODES], help="make the folders alike: copy and delete in this direction")
    p.add_argument("--dry-run", action="store_true", help="with --sync: show what would be done and do nothing")
    p = command("check", "look for files that are not healthy: empty, junk, bad names, wrong extensions, damaged zips, empty folders")
    p.add_argument("folders", nargs="+", metavar="folder", help="where to look")
    p.add_argument("--deep", action="store_true", help="also read whole files (checks the inside of every zip, cbz, epub); slow on big libraries")
    p.add_argument("--only", action="append", default=[], metavar="RULE", help="run only this checker (repeat for several; --list shows them)")
    p.add_argument("--list", action="store_true", help="list the checkers and do nothing")
    p.add_argument("--fix", action="store_true", help="apply the obvious fixes (renames, or with --delete-junk the junk to the recycle bin)")
    p.add_argument("--delete-junk", action="store_true", help="with --fix: delete (to the recycle bin) instead of renaming")
    p.add_argument("--dry-run", action="store_true", help="with --fix: show what would be done and do nothing")
    sub.add_parser("mcp", help="run the MCP server for an AI assistant on standard input and output (see docs/assistant.md)",
                   description="Starts the MCP server. The assistant's program starts it and talks to it through the pipes; there is no network "
                               "listener. What an assistant may do is set in Dossier: Settings > Assistant Access.")
    return parser


# running ---------------------------------------------------------------------------------------------------------------------------------
def run_command(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["help"]:
        argv = argv[1:] + ["--help"] if argv[1:] else ["--help"]
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "mcp":
        from ..assistant.server import serve
        return serve()
    out = make_output(args)
    try:
        return int(COMMAND_FUNCTIONS[args.command](args, out, make_fs()) or EXIT_OK)
    except Cancelled:
        return EXIT_INTERRUPTED
    finally:
        out.close()


def _emit(out: Output, row: dict, text: str) -> None:
    out.record(row)
    out.line(text)


# ls, info, find, checksum ----------------------------------------------------------------------------------------------------------------
def cmd_ls(args, out, fs) -> int:
    path = args.path
    if "://" not in path:
        if os.path.isfile(path) and zipfs.is_archive(os.path.abspath(path)):
            path = zipfs.archive_root(os.path.abspath(path))       # an archive file is listed like a folder
        else:
            path = one_folder(path)
    try:
        entries = sort_entries(fs.list(path))
    except OSError as e:
        raise CliError(f"cannot list {args.path}: {getattr(e, 'strerror', None) or e}")
    for e in entries:
        row = entry_row(e, fs)
        if args.long:
            _emit(out, row, f"{'d' if e.is_dir else '-'}  {'' if e.is_dir else human_size(e.size):>8}  {date_text(e.mtime):<16}  {e.name}")
        else:
            _emit(out, row, e.name + ("/" if e.is_dir else ""))
    out.finish({"command": "ls", "path": path, "count": len(entries)})
    return EXIT_OK


def cmd_info(args, out, fs) -> int:
    from ..core import filetags, properties, viewmodes
    from ..core.exif import read_exif
    paths = need_paths(args.paths)
    failed = 0
    for path in paths:
        try:
            e = fs.stat(path)
        except OSError as err:
            out.error(f"{path}: {getattr(err, 'strerror', None) or err}")
            failed += 1
            continue
        size = f"{e.size:,} bytes" if args.bytes else human_size(e.size)
        row: dict = {"path": path, "name": e.name, "type": "folder" if e.is_dir else "file", "size": 0 if e.is_dir else e.size,
                     "modified": e.mtime, "created": e.ctime, "accessed": e.atime, "link": e.is_link}
        lines = [f"Path: {path}", f"Type: {'Folder' if e.is_dir else 'File'}"] + ([] if e.is_dir else [f"Size: {size}"]) + \
            [f"Modified: {date_text(e.mtime)}"] + ([f"Created: {date_text(e.ctime)}"] if e.ctime else [])
        if not e.is_dir and "://" not in path:
            tags = filetags.read_tags(path)
            if not tags.is_empty():
                row["tags"] = {"tags": list(tags.tags), "rating": tags.rating, "label": tags.label}
                lines.append("Tags: " + ", ".join(tags.tags) + (f"   Rating: {tags.rating}" if tags.rating else "") + (f"   Label: {tags.label}" if tags.label else ""))
            kind = properties.kind_of(path)
            if kind:
                result = properties.read_metadata(path, kind)
                row["metadata"] = [{"key": f.key, "label": f.label, "value": f.value, "group": f.group} for f in result.fields]
                lines += [f"{f.label}: {f.value}" for f in result.fields]
                if result.error:
                    out.warn(f"{path}: {result.error}")
            elif viewmodes.mode_for(path) == "image":
                ex = read_exif(path)
                row["exif"] = [{"group": g, "label": k, "value": v} for g, k, v in ex.fields]
                lines += [f"{k}: {v}" for _g, k, v in ex.fields]
        out.record(row)
        out.line("\n".join(lines) + ("\n" if len(paths) > 1 else ""))
    out.finish({"command": "info"})
    return EXIT_PARTIAL if failed else EXIT_OK


def cmd_find(args, out, fs) -> int:
    root = one_folder(args.folder, "the folder to search")
    criteria = Criteria(root=root, name=args.name, case_sensitive=args.case, kinds=args.kind, subfolders=not args.no_subfolders,
                        min_size=parse_size(args.min_size) if args.min_size else None, max_size=parse_size(args.max_size) if args.max_size else None,
                        newer_than=parse_date(args.newer) if args.newer else None, older_than=parse_date(args.older) if args.older else None,
                        text=args.text, text_regex=args.regex, text_case=args.case, tags=list(args.tag), max_results=args.limit)
    try:
        found = search(fs, criteria, None, lambda scanned, hits: out.info(f"{scanned:,} looked at, {hits:,} found") if scanned % 5000 < 200 else None)
    except BadCriteria as e:
        raise CliError(str(e))
    for e in found.entries:
        _emit(out, {"path": e.path, "is_dir": e.is_dir, "size": 0 if e.is_dir else e.size, "modified": e.mtime}, e.path)
    if found.truncated:
        out.warn(f"stopped at the limit of {args.limit:,} results")
    if found.unreadable:
        out.warn(f"{found.unreadable} folder{'s' if found.unreadable != 1 else ''} could not be read")
    out.finish({"command": "find", "root": root, "count": len(found.entries), "scanned": found.scanned, "truncated": found.truncated})
    return EXIT_OK


def cmd_checksum(args, out, fs) -> int:
    if args.check:
        return _check_list(args, out, fs)
    paths = need_paths(args.paths)
    files = [p for p in paths if os.path.isfile(p)]
    for p in paths:
        if p not in files:
            out.warn(f"{p}: a folder has no checksum (name its files, for example folder/*)")
    failed = 0
    hashes = checksums.hash_files(fs, files, (args.algorithm,), None, lambda done, total, name: out.progress(done, total, name) if name else None)
    for h in hashes:
        if h.error:
            failed += 1
            out.error(f"{h.path}: could not be read ({h.error})")
            out.record({"path": h.path, "error": h.error})
        else:
            _emit(out, {"path": h.path, "size": h.size, "algorithm": args.algorithm, "digest": h.digests[args.algorithm]},
                  f"{h.digests[args.algorithm]} *{h.path}")
    out.finish({"command": "checksum", "algorithm": args.algorithm})
    return EXIT_PARTIAL if failed else EXIT_OK


def _check_list(args, out, fs) -> int:
    list_path = os.path.abspath(args.check)
    if not os.path.isfile(list_path):
        raise CliError(f"the list does not exist: {args.check}")
    base = os.path.dirname(list_path)
    bad = 0
    with open(list_path, encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\r\n") for ln in f if ln.strip() and not ln.startswith("#")]
    for n, line in enumerate(lines, 1):
        digest, _sp, name = line.partition(" ")
        name = name.lstrip(" *")
        algorithm = checksums.algorithm_of(digest.lower())
        if not algorithm or not name:
            out.error(f"line {n} is not 'hash *name': {line[:60]}")
            bad += 1
            continue
        path = os.path.join(base, name)
        out.progress(n, len(lines), name)
        if not os.path.isfile(path):
            status = "missing"
        else:
            h = checksums.hash_file(fs, path, (algorithm,))
            status = "error" if h.error else ("ok" if h.digests[algorithm] == digest.lower() else "FAILED")
        bad += status != "ok"
        _emit(out, {"path": path, "status": status.lower(), "algorithm": algorithm}, f"{name}: {status}")
    out.finish({"command": "checksum", "check": list_path, "problems": bad})
    return EXIT_PARTIAL if bad else EXIT_OK


# copy, move, delete -------------------------------------------------------------------------------------------------------------------------
def _run_plan(plan, args, out, fs, verb: str) -> tuple:
    """Show or run a plan: ``(exit code, what to put in the summary)``. The caller finishes the output."""
    for w in plan.warnings:
        out.warn(w)
    for b in plan.blocking:
        out.error(b)
    if plan.blocking:
        return EXIT_USAGE, {"steps": 0}
    steps = [op for op in plan.ops]
    total = sum(op.size for op in steps if op.kind in (Kind.COPY, Kind.MOVE) and not op.is_dir)
    if args.dry_run:
        for op in steps:
            _emit(out, {"op": op.kind.value, "from": op.src, "to": op.dst, "size": op.size, "overwrite": op.overwrite}, op_line(op))
        out.line(f"{verb}: {len(steps):,} step{'s' if len(steps) != 1 else ''}, {human_size(total)} (nothing was done: --dry-run)")
        return EXIT_OK, {"dry_run": True, "steps": len(steps), "bytes": total, "skipped": list(plan.skipped)}
    if not steps:
        out.line("nothing to do")
        return EXIT_OK, {"steps": 0, "skipped": list(plan.skipped)}
    options = ExecOptions(verify=getattr(args, "verify", False), on_item=lambda op, n, count: out.progress(n, count, os.path.basename(op.src or op.dst)))
    result = execute(plan, fs, trasher=default_trash, options=options)
    for r in result.results:
        _emit(out, {"op": r.op.kind.value, "from": r.op.src, "to": r.op.dst, "status": r.status, "error": r.error}, op_line(r.op) + ("" if r.status == "done" else f"  [{r.status}: {r.error}]"))
    for r in result.failed:
        out.error(f"{r.op.src or r.op.dst}: {r.error}")
    out.line(f"{verb}: {len(result.done):,} done" + (f", {len(result.failed)} failed" if result.failed else "") + (f", {len(plan.skipped)} skipped" if plan.skipped else ""))
    return (EXIT_PARTIAL if result.failed or result.cancelled else EXIT_OK,
            {"done": len(result.done), "failed": len(result.failed), "skipped": list(plan.skipped)})


def cmd_transfer(args, out, fs) -> int:
    *sources_text, dest_text = args.paths
    if not sources_text:
        raise CliError(f"{args.command} needs at least one source and a destination folder")
    sources = need_paths(sources_text)
    dest = os.path.abspath(dest_text)
    if not os.path.isdir(dest):
        if os.path.exists(dest):
            raise CliError(f"the destination is a file, not a folder: {dest_text}")
        if not args.create:
            raise CliError(f"the destination folder does not exist: {dest_text} (--create makes it)")
        if not args.dry_run:
            os.makedirs(dest, exist_ok=True)
    plan = (plan_copy if args.command == "copy" else plan_move)(fs, sources, dest)
    if plan.conflicts:
        plan = plan.resolve(POLICIES[args.on_conflict], fs)
    if plan.conflicts:                                       # what a policy cannot settle (a folder where a file is): left alone
        for i in plan.conflicts:
            out.warn(f"left alone: {plan.ops[i].dst} ({plan.ops[i].conflict})")
        plan = plan.resolve(Resolution.SKIP, fs)
    code, info = _run_plan(plan, args, out, fs, "copied" if args.command == "copy" else "moved")
    out.finish({"command": args.command, **info})
    return code


def cmd_delete(args, out, fs) -> int:
    paths = need_paths(args.paths)
    plan = plan_delete(fs, paths, to_trash=not args.permanent)
    code, info = _run_plan(plan, args, out, fs, "deleted")
    out.finish({"command": "delete", **info})
    return code


# dups and compare -------------------------------------------------------------------------------------------------------------------------------
def cmd_dups(args, out, fs) -> int:
    roots = [one_folder(f) for f in args.folders]

    def report(stage: str, done: int, total: int) -> None:
        if total and done % 50 == 0 or done == total:
            out.info(f"{stage}: {done:,}" + (f" of {total:,}" if total else ""))
    result = dup.find_duplicates(fs, roots, min_size=parse_size(args.min_size), name=args.name, progress=report)
    keep_paths = set()
    for n, g in enumerate(result.groups, 1):
        keep = dup.keep_index(g, args.keep)
        keep_paths.add(g.files[keep].path)
        out.line(f"Group {n}: {len(g.files)} copies of {human_size(g.size)}, {human_size(g.wasted)} wasted")
        out.record({"size": g.size, "wasted": g.wasted, "digest": g.digest,
                    "files": [{"path": e.path, "modified": e.mtime, "keep": i == keep} for i, e in enumerate(g.files)]})
        for i, e in enumerate(g.files):
            out.line(f"  {'keep ' if i == keep else 'extra'} {e.path}")
    for w in ([f"{result.unreadable} file{'s' if result.unreadable != 1 else ''} could not be read and were left out"] if result.unreadable else []):
        out.warn(w)
    summary = {"command": "dups", "groups": len(result.groups), "copies": result.copies, "wasted": result.wasted, "scanned": result.scanned}
    out.line(f"{len(result.groups):,} group{'s' if len(result.groups) != 1 else ''}, {human_size(result.wasted)} taken by the extra copies, {result.scanned:,} files looked at")
    if not args.delete or not result.groups:
        out.finish(summary)
        return EXIT_OK
    extras = dup.extras(result.groups, args.keep)
    if dup.groups_left_empty(result.groups, extras):         # cannot happen with a keep rule; refused anyway
        raise CliError("refusing to delete every copy of a file")
    plan = plan_delete(fs, extras, to_trash=True)
    code, info = _run_plan(plan, args, out, fs, "deleted")
    out.finish({**summary, **info})
    return code


def cmd_compare(args, out, fs) -> int:
    left, right = one_folder(args.left, "the left folder"), one_folder(args.right, "the right folder")
    result = cmp.compare_trees(fs, left, right, recursive=not args.no_subfolders, by=args.by, tolerance=args.tolerance,
                               ignore_hour=not args.exact_hour, include_same=args.same,
                               progress=lambda stage, done, total: out.info(f"{stage}: {done:,}") if done % 2000 == 0 and done else None)
    for row in result.rows:
        _emit(out, {"path": row.rel, "status": STATUS_WORDS[row.status], "folder": row.is_dir,
                    "left": {"size": row.left.size, "modified": row.left.mtime} if row.left else None,
                    "right": {"size": row.right.size, "modified": row.right.mtime} if row.right else None},
              f"{STATUS_WORDS[row.status]:<13} {row.rel}{'/' if row.is_dir else ''}")
    if result.unreadable:
        out.warn(f"{result.unreadable} folder{'s' if result.unreadable != 1 else ''} could not be read")
    counts = {STATUS_WORDS[k]: result.count(k) for k in STATUS_WORDS if result.count(k)}
    out.line(f"{len(result.rows):,} difference{'s' if len(result.rows) != 1 else ''}, {result.same:,} files alike" + (f"  ({', '.join(f'{v} {k}' for k, v in counts.items())})" if counts else ""))
    if not args.sync:
        out.finish({"command": "compare", "differences": len(result.rows), "same": result.same, "counts": counts})
        return EXIT_OK
    actions = [a for a in sync.decide_all(result.rows, args.sync) if a.kind]
    summary = sync.summarise(actions)
    out.line(f"sync {args.sync}: {summary.text()}")
    plans = sync.build_plans(fs, left, right, actions)
    code, done, failed = EXIT_OK, 0, 0
    sub = argparse.Namespace(command="compare", dry_run=args.dry_run, verify=False)
    for plan in plans:
        step_code, info = _run_plan(plan, sub, out, fs, plan.title.lower())
        code = max(code, step_code)
        done, failed = done + info.get("done", 0), failed + info.get("failed", 0)
    out.finish({"command": "compare", "differences": len(result.rows), "sync": args.sync, "actions": len(actions), "dry_run": args.dry_run,
                "done": done, "failed": failed})
    return code


# check ------------------------------------------------------------------------------------------------------------------------------------
def cmd_check(args, out, fs) -> int:
    from ..core import health
    known = {c.id: c for c in health.checkers()}
    if args.list:
        for c in known.values():
            _emit(out, {"id": c.id, "name": c.name, "tier": c.tier, "scope": c.scope}, f"{c.id:<10} tier {c.tier}  {c.name}")
        out.finish({"command": "check", "checkers": len(known)})
        return EXIT_OK
    unknown = [o for o in args.only if o not in known]
    if unknown:
        raise CliError("no such checker: " + ", ".join(unknown) + " (--list shows them)")
    roots = [one_folder(f) for f in args.folders]
    report = health.run_checks(fs, roots, max_tier=health.T2 if args.deep else health.T1, only=args.only or None,
                               progress=lambda done, found: out.info(f"{done:,} files looked at, {found:,} findings"))
    for f in report.findings:
        _emit(out, {"path": f.path, "checker": f.checker, "rule": f.rule, "severity": f.severity, "message": f.message, "evidence": f.evidence,
                    "fix": f.fix.label if f.fix else None},
              f"{f.severity:<7} {f.rule:<22} {f.path}" + (f"  ({f.evidence})" if f.evidence else ""))
    if report.unreadable:
        out.warn(f"{report.unreadable} item{'s' if report.unreadable != 1 else ''} could not be read")
    counts = {s: report.count(s) for s in health.SEVERITIES}
    out.line(f"{len(report.findings):,} finding{'s' if len(report.findings) != 1 else ''} ({counts['error']} errors, {counts['warning']} warnings, "
             f"{counts['info']} notes) in {report.files:,} files and {report.folders:,} folders")
    summary = {"command": "check", "findings": len(report.findings), **counts, "files": report.files, "folders": report.folders}
    code = EXIT_PARTIAL if counts["error"] or counts["warning"] else EXIT_OK
    if args.fix:
        fixable = [f for f in report.findings if f.fix and (f.fix.kind == "rename") != args.delete_junk]
        plan = health.fix_plan(fs, fixable)
        if plan is None:
            out.line("nothing to fix")
        else:
            sub = argparse.Namespace(command="check", dry_run=args.dry_run, verify=False)
            step_code, info = _run_plan(plan, sub, out, fs, plan.title.lower())
            code = max(code if args.dry_run else EXIT_OK, step_code)
            summary.update(info)
    out.finish(summary)
    return code


COMMAND_FUNCTIONS = {"mcp": None, "check": cmd_check, "ls": cmd_ls, "info": cmd_info, "find": cmd_find, "checksum": cmd_checksum, "copy": cmd_transfer, "move": cmd_transfer,
                     "delete": cmd_delete, "dups": cmd_dups, "compare": cmd_compare}
assert set(COMMAND_FUNCTIONS) == set(COMMANDS)
