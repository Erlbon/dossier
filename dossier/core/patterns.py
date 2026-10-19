"""Wildcard patterns for marking files (Ctrl+F in the window).

A pattern text holds one or more patterns separated by ``;``, ``,`` or spaces:

    *.jpg                 every .jpg file
    *.jpg;*.png           either
    report?.txt           ? stands for one character
    *.log !debug*         everything matching the first, except what matches a pattern starting with !
    backup*/              a pattern ending in / (or a backslash) is for folders only; the others are for files

Matching is on the name only, not the path, and ignores case on systems whose file names ignore case.
Brackets work as in ``fnmatch``: ``[abc]`` is one of those characters, ``[!abc]`` anything else.
A pattern without any wildcard is an exact name; a bare word is NOT a "contains" search.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

SEPARATORS = re.compile(r"[;,\s]+")


@dataclass
class PatternSet:
    include_files: list = field(default_factory=list)
    include_folders: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    text: str = ""

    def matches(self, name: str, is_dir: bool) -> bool:
        included = self.include_folders if is_dir else self.include_files
        if not included or not any(rx.fullmatch(name) for rx in included):
            return False
        return not any(rx.fullmatch(name) for rx in self.exclude)


def _compile(pattern: str, case_sensitive: bool):
    return re.compile(fnmatch.translate(pattern), 0 if case_sensitive else re.IGNORECASE)


def parse(text: str, *, case_sensitive: bool = False) -> PatternSet:
    """Turn the text typed by the user into patterns. An empty text, or one with only exclusions, matches
    nothing (an exclusion needs something to exclude from)."""
    result = PatternSet(text=text)
    for part in (p for p in SEPARATORS.split(text.strip()) if p):
        negative = part[0] == "!" and len(part) > 1
        body = part[1:] if negative else part
        folders = body[-1] in "/\\"
        body = body.rstrip("/\\")
        if not body:
            continue
        rx = _compile(body, case_sensitive)
        if negative:
            result.exclude.append(rx)
        elif folders:
            result.include_folders.append(rx)
        else:
            result.include_files.append(rx)
    return result


def select(entries: Iterable, patterns: PatternSet, *, name_of=lambda e: e.name) -> list:
    """The entries (anything with ``is_dir``) whose name the patterns match."""
    return [e for e in entries if patterns.matches(name_of(e), bool(e.is_dir))]


def describe(text: str) -> Optional[str]:
    """A reason the text cannot be used as patterns, or None."""
    parsed = parse(text)
    if not parsed.include_files and not parsed.include_folders:
        return "Type at least one pattern, for example *.jpg"
    return None
