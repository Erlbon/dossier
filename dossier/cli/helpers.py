"""Small things the commands share: sizes and dates the way people type them, the file system, path arguments, and text for a result."""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime
from typing import Iterable, Optional

from redactor_common.cli import CliError

from ..core.columns import when
from ..core.home import HomeFileSystem, HomeProvider, RouterFileSystem
from ..core.sizefmt import human_size
from ..core.vfs import LocalFileSystem, natural_key

UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "m": 1024 ** 2, "mb": 1024 ** 2, "g": 1024 ** 3, "gb": 1024 ** 3, "t": 1024 ** 4, "tb": 1024 ** 4}


def make_fs() -> RouterFileSystem:
    """The file system the window uses, without the window: the local disk and archives (a server needs a login that only the window asks for)."""
    return RouterFileSystem(LocalFileSystem(), HomeFileSystem(HomeProvider(pins=lambda: [], network=lambda: [])))


def parse_size(text: str) -> int:
    """``1500``, ``10K``, ``1.5M``, ``2GB`` as a number of bytes (K means 1024)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", text or "")
    if not m or m.group(2).lower() not in UNITS:
        raise CliError(f"not a size: {text!r} (use a number of bytes, or K, M, G: 10M)")
    return int(float(m.group(1)) * UNITS[m.group(2).lower()])


def parse_date(text: str) -> float:
    """``2024-05-17`` or ``2024-05-17 10:30`` (local time) as seconds since 1970."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).timestamp()
        except ValueError:
            continue
    raise CliError(f"not a date: {text!r} (use 2024-05-17 or 2024-05-17 10:30)")


def date_text(ts: float) -> str:
    return when(ts)


def size_text(n: int, exact: bool = False) -> str:
    return f"{n:,} bytes" if exact else human_size(n)


def path_arguments(arguments: Iterable[str]) -> tuple:
    """``(paths, missing)`` of the paths named on the command line. Wildcards are expanded here (the Windows command prompt does not do it);
    an argument that names something that exists is always taken as it is, so a ``[`` in a real name is not a pattern."""
    paths: list = []
    missing: list = []
    for argument in arguments:
        if os.path.lexists(argument) or "://" in argument:
            found = [argument]
        elif any(c in argument for c in "*?["):
            head, tail = os.path.split(argument)
            found = sorted(glob.glob(os.path.join(glob.escape(head), tail) if head else tail), key=natural_key) or []
        else:
            found = []
        if not found:
            missing.append(argument)
        paths.extend(os.path.abspath(p) if "://" not in p else p for p in found)
    unique = list(dict.fromkeys(paths))
    return unique, missing


def need_paths(arguments: Iterable[str]) -> list:
    """The paths named, or a ``CliError`` (exit code 2) that says which ones do not exist."""
    paths, missing = path_arguments(arguments)
    if missing:
        raise CliError("not found: " + ", ".join(missing))
    if not paths:
        raise CliError("no files or folders named")
    return paths


def one_folder(argument: str, what: str = "the folder") -> str:
    path = os.path.abspath(argument) if "://" not in argument else argument
    if "://" not in argument and not os.path.isdir(path):
        raise CliError(f"{what} does not exist: {argument}")
    return path


def entry_row(entry, fs) -> dict:
    return {"name": entry.name, "path": entry.path, "is_dir": entry.is_dir, "size": 0 if entry.is_dir else entry.size,
            "modified": entry.mtime, "link": entry.is_link}


def sort_entries(entries: list) -> list:
    return sorted(entries, key=lambda e: (not e.is_dir, natural_key(e.name)))


def op_line(op) -> str:
    """One line for a planned step: what it does and to what."""
    kind = op.kind.value
    if op.dst:
        return f"{kind:<6} {op.src}  ->  {op.dst}" if op.src else f"{kind:<6} {op.dst}"
    return f"{kind:<6} {op.src}"


def first_line(text: Optional[str]) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""
