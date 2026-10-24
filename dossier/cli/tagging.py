"""The ``tag`` command: show and change the tags inside files (mp3, flac, ogg, opus, m4a, and the ComicInfo of a cbz). A shell around
``core/metawrite.py``; the rules every command follows are in ``dossier/cli/__init__.py``."""
from __future__ import annotations

from redactor_common.cli import EXIT_OK, EXIT_PARTIAL, CliError

from ..core import metawrite as mw
from .helpers import need_paths

ALIASES = {"year": "date", "track": "tracknumber", "disc": "discnumber", "album-artist": "albumartist", "language": "LanguageISO",
           "cover-artist": "CoverArtist", "age-rating": "AgeRating"}


def resolve_key(kind: str, text: str) -> str:
    """The field a typed name means: its key or its label, in any case (``Series``, ``series``, ``Album artist``, ``year``), or a ``CliError``."""
    wanted = text.strip().lower().replace(" ", "-")
    for key, label in mw.fields_for(kind):
        if wanted in (key.lower(), label.lower().replace(" ", "-")):
            return key
    alias = ALIASES.get(wanted, "")
    if alias and any(alias == key for key, _l in mw.fields_for(kind)):
        return alias
    raise CliError(f"no field {text!r} for this kind of file; the fields are: " + ", ".join(k for k, _l in mw.fields_for(kind)))


def _edits(args, kind: str) -> dict:
    edits: dict = {}
    for text in args.set:
        key, eq, value = text.partition("=")
        if not eq:
            raise CliError(f"--set needs KEY=VALUE, not {text!r}")
        edits[resolve_key(kind, key)] = value
    for key in args.clear:
        edits[resolve_key(kind, key)] = ""
    return edits


def cmd_tag(args, out, fs) -> int:
    from . import commands
    if args.fields:
        for kind in (mw.AUDIO, mw.COMIC):
            for key, label in mw.fields_for(kind):
                out.record({"kind": kind, "key": key, "label": label})
                out.line(f"{kind:<6} {key:<14} {label}")
        out.finish({"command": "tag", "fields": len(mw.AUDIO_FIELDS) + len(mw.COMIC_FIELDS)})
        return EXIT_OK
    paths = need_paths(args.paths)
    kinds = {mw.kind_of(p) for p in paths}
    if len(kinds) != 1 or "" in kinds:
        raise CliError("give files of one kind that can be tagged: mp3, flac, ogg, opus, m4a files, or cbz comics (--fields lists the fields)")
    kind = next(iter(kinds))
    if not (args.set or args.clear):                                   # nothing to change: show what the files carry
        code = EXIT_OK
        for path in paths:
            try:
                values = mw.read_values(path)
            except OSError as e:
                out.error(f"{path}: {e}")
                code = EXIT_PARTIAL
                continue
            out.record({"path": path, "tags": values})
            out.line(path)
            out.line("\n".join(f"  {label}: {values.get(key, '')}" for key, label in mw.fields_for(kind) if values.get(key)) or "  (no tags)")
        out.finish({"command": "tag", "files": len(paths)})
        return code
    items = mw.plan(paths, _edits(args, kind))
    code = EXIT_OK
    for item in items:
        if item.problem:
            out.error(f"{item.path}: {item.problem}")
            code = EXIT_PARTIAL
        elif item.changes:
            out.record({"path": item.path, "changes": [{"key": c.key, "old": c.old, "new": c.new} for c in item.changes]})
            out.line(item.path)
            out.line("\n".join(f"  {c.label}: {c.old!r} -> {c.new!r}" if c.new else f"  {c.label}: {c.old!r} -> (removed)" for c in item.changes))
    todo = sum(1 for i in items if i.writable)
    if args.dry_run:
        out.line(f"{todo:,} file{'s' if todo != 1 else ''} would change (nothing was done: --dry-run)")
        out.finish({"command": "tag", "dry_run": True, "files": todo})
        return code
    result = mw.apply(items, trasher=commands.default_trash)
    for path, why in result.failed:
        out.error(f"{path}: {why}")
    out.line(f"changed {result.done:,} file{'s' if result.done != 1 else ''}" + (f", {len(result.failed)} failed" if result.failed else ""))
    out.finish({"command": "tag", "done": result.done, "failed": len(result.failed)})
    return EXIT_PARTIAL if result.failed else code
