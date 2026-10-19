"""The parts of a path for a clickable address bar (Qt-free).

``segments`` walks up from a folder with the file system's own ``parent``, so it is right for every kind of path:
``C:\\Temp\\Export``, a network share, ``/home/me/docs``, the inside of an archive (``zip://...!/docs``, whose
way up leaves the archive into the folder that holds it) and the Home page.
"""
from __future__ import annotations

from typing import Optional

from .home import is_home
from .platform import has_scheme

MAX_DEPTH = 128
SEPARATORS = chr(92) + "/"          # a backslash and a slash


def label_of(fs, path: str) -> str:
    """What a part is called on screen: its name, or for a root (a drive, a share, /) the root itself."""
    trimmed = path.rstrip(SEPARATORS)
    if has_scheme(path):
        return fs.basename(path) or trimmed
    if fs.is_root(path):
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
