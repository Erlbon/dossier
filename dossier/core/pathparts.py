"""The parts of a path for a clickable address bar (Qt-free).

``segments`` walks up from a folder with the file system's own ``parent``, so it is right for every kind of path:
``C:\\Temp\\Export``, a network share, ``/home/me/docs``, the inside of an archive (``zip://...!/docs``, whose
way up leaves the archive into the folder that holds it) and the Home page. ``expand_typed`` turns what is typed or pasted
into the address into a path.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .home import is_home
from .platform import has_scheme

MAX_DEPTH = 128
SEPARATORS = chr(92) + "/"          # a backslash and a slash
_VARIABLE = re.compile(r"%([^%\\/:*?\"<>|]+)%")      # %APPDATA%: a name between percent signs, with no path characters in it


def expand_typed(text: str) -> str:
    """What is typed or pasted into the address, as a path: quotes around it (Explorer's "Copy as path") taken off, Windows
    variables such as ``%APPDATA%`` and a leading ``~`` replaced, and the separators tidied. A variable that is not set stays
    as typed; a server's or an archive's address is taken as it is. "" for nothing."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    if not text or has_scheme(text):
        return text
    text = _VARIABLE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), text)
    return os.path.normpath(os.path.expanduser(text))


def label_of(fs, path: str) -> str:
    """What a part is called on screen: its name, or for a root (a drive, a share, /) the root itself."""
    trimmed = path.rstrip(SEPARATORS)
    if has_scheme(path):
        return fs.basename(path) or trimmed
    if fs.is_root(path):
        if fs.parent(path):                         # a share of another computer, below the computer: just its name
            return trimmed.replace("/", chr(92)).rsplit(chr(92), 1)[-1] or trimmed
        return trimmed or path
    return fs.basename(trimmed) or trimmed


def segments(fs, path: str) -> list:
    """``[(label, path), ...]`` from the topmost folder down to ``path``."""
    if not path:
        return []
    if is_home(path):
        return [("Home", path)]
    out: list = []
    current: Optional[str] = path
    while current and len(out) < MAX_DEPTH:
        out.append((label_of(fs, current), current))
        above = fs.parent(current)
        if not above or above == current:
            break
        current = above
    out.reverse()
    return out
