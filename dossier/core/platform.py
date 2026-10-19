"""The only place that knows which operating system we run on (spec section 13).

The rest of the core calls these helpers and never tests ``sys.platform`` itself.
"""
from __future__ import annotations

import os
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

REPLACEMENT = "\ufffd"


def path_key(path: str) -> str:
    """Identity key for a path: equal keys mean the same file on this system.

    Windows compares paths without regard to case, Linux does not (O11), so this
    delegates to ``os.path.normcase``. The original spelling is kept elsewhere for display.
    """
    return os.path.normcase(os.path.normpath(path))


def decode_name(name: str | bytes) -> str:
    """Make a file name safe to show (O12).

    Linux names are arbitrary bytes. Bytes that are not valid text become U+FFFD, so a
    listing never fails on one odd file.
    """
    if isinstance(name, bytes):
        try:
            name = os.fsdecode(name)
        except UnicodeDecodeError:  # Windows: the file system encoding has no escape for bad bytes
            name = name.decode("utf-8", errors="replace")
    # Undecodable bytes (Linux) and unpaired UTF-16 halves (NTFS) are lone surrogates; they cannot be displayed.
    return "".join(REPLACEMENT if "\ud800" <= ch <= "\udfff" else ch for ch in name)


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def is_link_like(st_mode_is_link: bool, attributes: int | None = None) -> bool:
    """True for symlinks and, on Windows, junctions and other reparse points.

    Walking into these can loop forever (a junction pointing at its own parent), so callers
    treat them as leaves. ``attributes`` is ``st_file_attributes`` where the system has it.
    """
    if st_mode_is_link:
        return True
    return IS_WINDOWS and attributes is not None and bool(attributes & _REPARSE_POINT)


def is_hidden(name: str, attributes: int | None = None) -> bool:
    """Hidden by the dot on Linux; on Windows by the hidden attribute (O9)."""
    if IS_WINDOWS and attributes is not None:
        return bool(attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN
    return name.startswith(".")
