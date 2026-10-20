"""The columns of a folder listing: which exist, which can be switched off, and how a value is written.

The model keeps one fixed set of columns (logical index = position in ``KEYS``); the header shows, hides and orders them.
The user's choice is stored by NAME (the common column dialog of redactor_common works on names), so adding a column later
never shifts what someone hid. Name and Type are always visible.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

BASIC_KEYS = ("name", "size", "modified", "type", "created", "accessed", "attributes", "location", "tags", "rating", "label")
# Columns read from inside the files (tags of audio, ComicInfo of comics, tracks of video). They are off everywhere until the owner
# switches them on, and a folder layout can switch them on for one folder only: a file has to be opened to fill them.
META_KEYS = ("m_title", "m_artist", "m_album", "m_track", "m_year", "m_genre", "m_length", "m_bitrate", "m_series", "m_number",
             "m_writer", "m_publisher", "m_pages", "m_resolution", "m_codec", "m_languages")
KEYS = BASIC_KEYS + META_KEYS
LEGACY_KEYS = BASIC_KEYS            # the columns that existed before the metadata ones (an old settings file knows only these)
LABELS = {"name": "Name", "size": "Size", "modified": "Date", "type": "Type", "created": "Created",
          "accessed": "Last opened", "attributes": "Attributes", "location": "Location", "tags": "Tags", "rating": "Rating",
          "label": "Label", "m_title": "Title (tag)", "m_artist": "Artist", "m_album": "Album", "m_track": "Track", "m_year": "Year",
          "m_genre": "Genre", "m_length": "Length", "m_bitrate": "Bitrate", "m_series": "Series", "m_number": "Issue",
          "m_writer": "Writer", "m_publisher": "Publisher", "m_pages": "Pages", "m_resolution": "Resolution",
          "m_codec": "Video codec", "m_languages": "Audio languages"}
PROTECTED = frozenset({"name", "type"})
DEFAULT_ORDER = ("name", "type", "size", "modified", "created", "accessed", "attributes", "location", "tags", "rating",
                 "label") + META_KEYS
DEFAULT_HIDDEN = frozenset({"created", "accessed", "attributes", "location", "tags", "rating", "label"}) | frozenset(META_KEYS)
DEFAULT_WIDTHS = {"name": 260, "size": 80, "modified": 130, "type": 90, "created": 130, "accessed": 130, "attributes": 80,
                  "location": 220, "tags": 200, "rating": 80, "label": 90, "m_title": 200, "m_artist": 160, "m_album": 160,
                  "m_track": 60, "m_year": 60, "m_genre": 110, "m_length": 70, "m_bitrate": 80, "m_series": 160, "m_number": 60,
                  "m_writer": 130, "m_publisher": 130, "m_pages": 60, "m_resolution": 90, "m_codec": 120, "m_languages": 110}
RIGHT_ALIGNED = frozenset({"size", "m_track", "m_year", "m_length", "m_bitrate", "m_number", "m_pages"})


def is_meta(key: str) -> bool:
    return key in META_KEYS


def newly_hidden(known) -> frozenset:
    """The columns that did not exist when a choice was saved (``known`` = the columns it knew) and start hidden: a new column must
    not appear by itself in a layout the owner made before it existed."""
    return frozenset(k for k in DEFAULT_HIDDEN if k not in set(known))
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


LABEL_COLORS = {"red": "#d64545", "orange": "#e08a20", "yellow": "#c9a800", "green": "#2e9e5b", "blue": "#3a7bd5",
                "purple": "#8a5cc8", "grey": "#8a8f98"}


def label_text(label: str) -> str:
    """A filled dot and the colour's name: the name tells it without the colour (and sorts)."""
    return f"{chr(0x25CF)} {label.capitalize()}" if label else ""


def rating_text(rating: int) -> str:
    return chr(0x2605) * rating if rating else ""


def location_text(path: str, sep_dirname) -> str:
    return sep_dirname(path) or ""
