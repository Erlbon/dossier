"""Colours of file names by type (comparison review 2026-11-05, card 9, option C; Qt-free).

Four groups, each with a colour for the light and one for the dark scheme: media (pictures, video, music), archives, documents and code,
and programs. The extensions are the ones the icons use (``core/filetypes.py``), so a name's colour and its icon never disagree. Hidden
and system items are dimmed; a marked item keeps the colour of marks over all of this (the list model decides that order). The owner
can switch it off or change a group's extensions and colours (Settings > Appearance > File Colours); the choice is kept as JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from .filetypes import GROUPS as ICON_GROUPS


def _exts(*icons: str) -> str:
    return " ".join(ICON_GROUPS[i] for i in icons)


@dataclass
class ColorGroup:
    key: str
    name: str
    extensions: str                 # without dots, separated by spaces
    light: str                      # #rrggbb on the light scheme
    dark: str                       # and on the dark one


DEFAULT_GROUPS = (
    ColorGroup("media", "Pictures, video and music", _exts("photo", "movie", "music"), "#0f6e56", "#5dcaa5"),
    ColorGroup("archives", "Archives", _exts("file-zip"), "#993c1d", "#f0997b"),
    ColorGroup("documents", "Documents and code", _exts("file-type-pdf", "file-type-doc", "file-spreadsheet", "book", "book-2", "file-code",
                                                         "file-text", "markdown", "file-database"), "#185fa5", "#85b7eb"),
    ColorGroup("programs", "Programs", _exts("file-settings") + " com scr appx msix", "#a32d2d", "#f09595"),
)


@dataclass
class FileColors:
    enabled: bool = True
    groups: list = field(default_factory=lambda: [ColorGroup(**asdict(g)) for g in DEFAULT_GROUPS])

    def __post_init__(self) -> None:
        self._by_ext: Optional[dict] = None

    def color_of(self, name: str, dark: bool) -> str:
        """The colour for a file called ``name`` ("" for none: the list's own text colour)."""
        if not self.enabled:
            return ""
        if self._by_ext is None:
            self._by_ext = {}
            for g in self.groups:
                for ext in g.extensions.lower().replace(",", " ").replace(".", " ").split():
                    self._by_ext.setdefault(ext, g)            # the first group that names an extension has it
        g = self._by_ext.get(os.path.splitext(name)[1].lstrip(".").lower())
        return (g.dark if dark else g.light) if g is not None else ""


def _hex(value, fallback: str) -> str:
    text = str(value or "").strip()
    return text if len(text) == 7 and text[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in text[1:]) else fallback


def loads(text) -> FileColors:
    """The saved choice; a missing or damaged one is the built-in groups (never an error)."""
    try:
        data = json.loads(text) if text else {}
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        return FileColors()
    defaults = {g.key: g for g in DEFAULT_GROUPS}
    groups = []
    for item in data.get("groups") or []:
        if isinstance(item, dict) and item.get("key") in defaults:
            base = defaults[item["key"]]
            groups.append(ColorGroup(base.key, base.name, str(item.get("extensions", base.extensions)),
                                     _hex(item.get("light"), base.light), _hex(item.get("dark"), base.dark)))
    named = {g.key for g in groups}
    groups += [ColorGroup(**asdict(g)) for g in DEFAULT_GROUPS if g.key not in named]   # a group added in a later version
    return FileColors(bool(data.get("enabled", True)), groups)


def dumps(colors: FileColors) -> str:
    return json.dumps({"enabled": colors.enabled, "groups": [asdict(g) for g in colors.groups]}, ensure_ascii=False)
