"""Dossier's command line, inside the same program as the window: ``dossier <command> ...`` (or ``python -m dossier <command> ...``).

The first argument decides: a command name runs the command line and never starts the window; anything else (nothing, or a folder) starts
the window as before. Every command works on the same Qt-free core as the window (lists, searches, compares, plans), so nothing happens
here that the window cannot do, and nothing is done differently:

* what changes files can be previewed with ``--dry-run`` (the plan, and nothing else);
* a file is never overwritten unless ``--on-conflict overwrite`` says so, and what is deleted or replaced goes to the recycle bin;
* the results are text on stdout, or with ``--json`` one JSON document and nothing else there; progress and warnings go to stderr
  (silenced by ``-q``); ``--output FILE`` writes the result to a file that is complete when the program ends;
* the exit code is 0 (all went well), 1 (some items failed), 2 (a mistake in the command or a path that does not exist), 70 (a bug) or
  130 (Ctrl+C).

This file stays light: it only knows the names (``cli_requested`` is called on every start, window or not).
"""
from __future__ import annotations

COMMANDS = ("ls", "info", "find", "checksum", "copy", "move", "delete", "dups", "compare", "check", "mcp")


def cli_requested(argv) -> bool:
    """Whether the program was started as a command line: ``argv`` is the whole ``sys.argv`` and its first argument is a command name
    (or ``help``, ``--help``, ``--version``). A path or anything else means "start the window"."""
    return len(argv) > 1 and argv[1] in set(COMMANDS) | {"help", "-h", "--help", "--version"}


def main(argv=None) -> int:
    """Run a command; ``argv`` is the arguments after the program name. Returns the exit code."""
    from .commands import run_command
    return run_command(argv)
