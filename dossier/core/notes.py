"""Folder notes (spec section 8, N1 and N2): the Markdown text a folder shows under its listing.

Top note: ``about.md``, ``artist.md``, ``author.md``, ``series.md`` or ``album.md``. Bottom note:
``README.md`` or ``index.md``. Optional front matter between ``---`` lines is stripped and its
``title`` is read. The format is the one pluteus uses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .vfs import FileSystem

TOP_NAMES = ("about.md", "artist.md", "author.md", "series.md", "album.md")
BOTTOM_NAMES = ("README.md", "index.md")
MAX_BYTES = 256 * 1024   # V4: notes are capped; the rest is cut and reported


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    body: str
    truncated: bool = False


def split_front_matter(text: str) -> tuple:
    """``(fields, body)``. Only simple ``key: value`` lines are read; lists are ignored."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fields = {}
            for line in lines[1:i]:
                key, sep, value = line.partition(":")
                if sep and key.strip() and not key.startswith((" ", "-", "\t")):
                    fields[key.strip().lower()] = value.strip().strip("\"'")
            return fields, "\n".join(lines[i + 1:]).lstrip("\n")
    return {}, text   # no closing line: it is not front matter


def _read(fs: FileSystem, path: str) -> Optional[Note]:
    try:
        with fs.open_read(path) as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError:
        return None
    truncated = len(raw) > MAX_BYTES
    text = raw[:MAX_BYTES].decode("utf-8-sig", errors="replace")
    fields, body = split_front_matter(text)
    return Note(path=path, title=fields.get("title", ""), body=body, truncated=truncated)


def compose_markdown(notes: list) -> str:
    """One Markdown text for the notes of a folder, top note first. A front matter title becomes
    a heading unless the text already starts with one."""
    parts = []
    for n in notes:
        body = n.body.rstrip()
        if n.title and not body.lstrip().startswith("#"):
            body = f"## {n.title}\n\n{body}"
        if n.truncated:
            body += "\n\n*(the note is longer; the rest is not shown)*"
        parts.append(body)
    return "\n\n---\n\n".join(parts)


def find_notes(fs: FileSystem, folder: str) -> list:
    """The notes of ``folder``: the top note first, then the bottom note. Empty if there are none.
    Names match exactly first; on a case-insensitive match the exact spelling wins (O11)."""
    try:
        names = {fs.basename(e.path): e for e in fs.list(folder) if not e.is_dir}
    except OSError:
        return []
    by_fold: dict = {}
    for n in names:
        by_fold.setdefault(n.casefold(), []).append(n)
    found = []
    for group in (TOP_NAMES, BOTTOM_NAMES):
        for wanted in group:
            actual = wanted if wanted in names else next(iter(sorted(by_fold.get(wanted.casefold(), []))), None)
            if actual:
                note = _read(fs, fs.join(folder, actual))
                if note is not None:
                    found.append(note)
                break
    return found
