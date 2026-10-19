"""The only place that knows which operating system we run on (spec section 13).

The rest of the core calls these helpers and never tests ``sys.platform`` itself.
"""
from __future__ import annotations

import os
import re
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

REPLACEMENT = "\ufffd"


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+)://")   # two or more letters: 'C://' is a drive
_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = "\\\\?\\UNC\\"
# Windows refuses ordinary paths near 260 characters (folders already at 248); stay safely below.
_LONGPATH_THRESHOLD = 240


def has_scheme(path: str) -> bool:
    """True for a path of a virtual file system (``zip://a.zip/x``), false for a local path."""
    return bool(_SCHEME.match(path))


def strip_longpath(path: str) -> str:
    """Remove the Windows extended-length prefix so one file has one spelling."""
    if not IS_WINDOWS:
        return path
    if path.startswith(_EXTENDED_UNC):
        return "\\\\" + path[len(_EXTENDED_UNC):]
    if path.startswith(_EXTENDED):
        return path[len(_EXTENDED):]
    return path


def longpath(path: str) -> str:
    """The form to hand to the operating system (O6, F12).

    On Windows a path of 240 characters or more becomes an extended-length path, which is
    absolute and not normalised by the system, so it is made absolute first. Shorter paths and
    every path on other systems are returned unchanged.
    """
    if not IS_WINDOWS or len(path) < _LONGPATH_THRESHOLD or path.startswith(_EXTENDED):
        return path
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return _EXTENDED_UNC + full[2:]
    return _EXTENDED + full


def path_key(path: str) -> str:
    """Identity key for a path: equal keys mean the same file on this system.

    Windows compares paths without regard to case, Linux does not (O11), so this
    delegates to ``os.path.normcase``. The original spelling is kept elsewhere for display.
    Paths of a virtual file system carry a scheme (``zip://a.zip/x``): they never equal a
    local path, the scheme is case-folded and the rest is compared exactly.
    """
    m = _SCHEME.match(path)
    if m:
        return m.group(1).lower() + "://" + path[m.end():]
    return os.path.normcase(os.path.normpath(strip_longpath(path)))


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
