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
        name = os.fsdecode(name)
    # os.fsdecode keeps undecodable bytes as lone surrogates; those cannot be displayed.
    return "".join(REPLACEMENT if "\udc80" <= ch <= "\udcff" else ch for ch in name)


def is_hidden(name: str, attributes: int | None = None) -> bool:
    """Hidden by the dot on Linux; on Windows by the hidden attribute (O9)."""
    if IS_WINDOWS and attributes is not None:
        return bool(attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN
    return name.startswith(".")
