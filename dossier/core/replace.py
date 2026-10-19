"""Find and replace for the notepad (Ctrl+H), with optional regular expressions.

Plain mode matches the text literally and replaces with the text literally. Regex mode uses Python's
``re``: groups are written ``\\1`` or ``\\g<name>`` in the replacement, and ``\\n`` and ``\\t`` mean a
line break and a tab. All functions work on a string, so the editor widget, the viewer and tests share
one engine and one set of rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .progress import CancelToken, check


class PatternError(ValueError):
    """The search or the replacement is not valid; the message is fit to show the user."""


@dataclass(frozen=True)
class FindSpec:
    pattern: str
    regex: bool = False
    case: bool = False
    whole_word: bool = False
    dot_all: bool = False         # regex only: '.' also matches a line break
    multiline: bool = True        # regex only: ^ and $ match at every line


def compile_spec(spec: FindSpec) -> "re.Pattern":
    if not spec.pattern:
        raise PatternError("Enter something to find.")
    body = spec.pattern if spec.regex else re.escape(spec.pattern)
    if spec.whole_word:
        body = rf"(?<!\w)(?:{body})(?!\w)"
    flags = 0 if spec.case else re.IGNORECASE
    if spec.regex:
        flags |= (re.DOTALL if spec.dot_all else 0) | (re.MULTILINE if spec.multiline else 0)
    try:
        return re.compile(body, flags)
    except re.error as e:
        where = f" at position {e.pos}" if getattr(e, "pos", None) is not None else ""
        raise PatternError(f"Not a valid regular expression{where}: {e.msg}") from None


def _template(spec: FindSpec, pattern: "re.Pattern", replacement: str):
    """A function giving the replacement text for one match."""
    if not spec.regex:
        return lambda m: replacement
    try:
        pattern.sub(replacement, "")       # parses the template now: a bad group or escape fails here, not midway
    except (re.error, IndexError) as e:
        raise PatternError(f"The replacement is not valid: {e}") from None
    return lambda m: m.expand(replacement)


def validate(spec: FindSpec, replacement: str = "") -> None:
    """Raise ``PatternError`` if the search or the replacement cannot be used; the find bar calls this while
    the user types, so a mistake shows at once."""
    pat = compile_spec(spec)
    _template(spec, pat, replacement)


def find_next(text: str, spec: FindSpec, start: int = 0, *, forward: bool = True, wrap: bool = True) -> Optional[tuple]:
    """``(begin, end)`` of the next match at or after ``start``, or of the previous one that begins before it."""
    pat = compile_spec(spec)
    if forward:
        m = pat.search(text, start)
        if m is None and wrap and start > 0:
            m = pat.search(text, 0)
        return (m.start(), m.end()) if m else None
    before = None
    last = None
    for m in pat.finditer(text):
        if m.end() == m.start():
            continue
        last = m
        if m.start() < start:
            before = m
    chosen = before if before is not None else (last if wrap else None)
    return (chosen.start(), chosen.end()) if chosen else None


def find_all(text: str, spec: FindSpec, limit: int = 100_000) -> list:
    """Every match as ``(begin, end)`` (empty matches skipped), at most ``limit``."""
    pat = compile_spec(spec)
    out: list = []
    for m in pat.finditer(text):
        if m.end() > m.start():
            out.append((m.start(), m.end()))
            if len(out) >= limit:
                break
    return out


def count(text: str, spec: FindSpec) -> int:
    return len(find_all(text, spec, limit=10**9))


def replacements(text: str, spec: FindSpec, replacement: str, *, region: Optional[tuple] = None,
                 cancel: Optional[CancelToken] = None) -> list:
    """What a replace-all would do, as ``(begin, end, new_text)`` for every non-empty match, so an editor
    can apply the changes one by one inside a single undo step. Empty matches are left alone (a pattern
    like ``x*`` never inserts text between every character)."""
    pat = compile_spec(spec)
    expand = _template(spec, pat, replacement)
    begin, end = region if region else (0, len(text))
    out: list = []
    for i, m in enumerate(pat.finditer(text, begin, end)):
        if i % 1000 == 0:
            check(cancel)
        if m.end() > m.start():
            out.append((m.start(), m.end(), expand(m)))
    return out


def replace_all(text: str, spec: FindSpec, replacement: str, *, region: Optional[tuple] = None,
                cancel: Optional[CancelToken] = None) -> tuple:
    """``(new_text, number_of_replacements)``. ``region=(begin, end)`` limits it to the selection."""
    changes = replacements(text, spec, replacement, region=region, cancel=cancel)
    if not changes:
        return text, 0
    pieces: list = []
    pos = 0
    for b, e, new in changes:
        pieces.append(text[pos:b])
        pieces.append(new)
        pos = e
    pieces.append(text[pos:])
    return "".join(pieces), len(changes)


def expand_at(text: str, spec: FindSpec, replacement: str, begin: int, end: int) -> Optional[str]:
    """The replacement for the text between ``begin`` and ``end`` if exactly that text is a match (the
    current selection in an editor), else None."""
    pat = compile_spec(spec)
    expand = _template(spec, pat, replacement)
    m = pat.fullmatch(text, begin, end)
    return expand(m) if m and m.end() > m.start() else None


def replace_one(text: str, spec: FindSpec, replacement: str, start: int = 0) -> Optional[tuple]:
    """Replace the first match at or after ``start``. Returns ``(new_text, begin, end_of_inserted_text)`` so
    the caller can put the cursor after it, or None when there is no match."""
    pat = compile_spec(spec)
    expand = _template(spec, pat, replacement)
    for m in pat.finditer(text, start):
        if m.end() == m.start():
            continue
        new = expand(m)
        return text[:m.start()] + new + text[m.end():], m.start(), m.start() + len(new)
    return None


def preview(text: str, spec: FindSpec, replacement: str, limit: int = 50) -> list:
    """The first matches as ``(line_number, before, after)``, for a preview list."""
    pat = compile_spec(spec)
    expand = _template(spec, pat, replacement)
    out: list = []
    for m in pat.finditer(text):
        if m.end() == m.start():
            continue
        line = text.count("\n", 0, m.start()) + 1
        out.append((line, m.group(0), expand(m)))
        if len(out) >= limit:
            break
    return out
