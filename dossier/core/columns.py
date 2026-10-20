"""The columns of a folder listing: which exist, which can be switched off, and how a value is written.

The model keeps one fixed set of columns (logical index = position in ``KEYS``); the header shows, hides and orders them.
The user's choice is stored by NAME (the common column dialog of redactor_common works on names), so adding a column later
never shifts what someone hid. Name and Type are always visible.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

KEYS = ("name", "size", "modified", "type", "created", "accessed", "attributes", "location")
LABELS = {"name": "Name", "size": "Size", "modified": "Date", "type": "Type", "created": "Created",
          "accessed": "Last opened", "attributes": "Attributes", "location": "Location"}
PROTECTED = frozenset({"name", "type"})
DEFAULT_ORDER = ("name", "type", "size", "modified", "created", "accessed", "attributes", "location")
DEFAULT_HIDDEN = frozenset({"created", "accessed", "attributes", "location"})
DEFAULT_WIDTHS = {"name": 260, "size": 80, "modified": 130, "type": 90, "created": 130, "accessed": 130, "attributes": 80,
                  "location": 220}
RIGHT_ALIGNED = frozenset({"size"})
WINDOWS_ATTRIBUTES = ((0x1, "R"), (0x2, "H"), (0x4, "S"), (0x20, "A"), (0x800, "C"), (0x4000, "E"))


def index_of(key: str) -> int:
    return KEYS.index(key)


def when(ts: float) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def type_text(name: str, is_dir: bool) -> str:
    """``Folder``, ``JPG file`` or ``File``: from the name only, so it costs nothing."""
    if is_dir:
        return "Folder"
    ext = os.path.splitext(name)[1]
    return f"{ext[1:].upper()} file" if len(ext) > 1 else "File"


def attributes_text(attrs: int) -> str:
    """Windows: the letters of ``attrib`` (R read-only, H hidden, S system, A archive, C compressed, E encrypted).
    Elsewhere ``attrs`` holds the file mode and shows as ``rwxr-xr-x``."""
    if not attrs:
        return ""
    if sys.platform == "win32":
        return "".join(letter for flag, letter in WINDOWS_ATTRIBUTES if attrs & flag)
    import stat
    return stat.filemode(attrs)[1:]


def location_text(path: str, sep_dirname) -> str:
    return sep_dirname(path) or ""
