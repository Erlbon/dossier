"""Icons for the GUI, as swappable sets of SVG files painted in the colours of the current scheme.

A set is a folder with a ``manifest.json`` and one ``<name>.svg`` per icon. The names are the ones
``core/filetypes.py`` produces (``folder``, ``photo``, ``book`` ...). A set whose files are called
something else lists the difference in its manifest::

    {"title": "Lucide", "licence": "ISC, see LICENSE.txt", "map": {"music": "file-audio.svg"}}

An icon a set does not have falls back to the built-in Tabler set, so a partial set still works.
Built-in sets live in ``dossier/gui/icons``; the user can add sets under ``icon-sets`` in the
settings folder, no code change needed. One icon is one stroke colour, so a scheme change re-renders
the cache. Frozen builds must include ``dossier/gui/icons`` as data (PyInstaller ``datas``).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from . import painted_icons, theme

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
DEFAULT_SET = "tabler"
SIZES = (16, 20, 24, 32, 48, 64, 96, 128, 192, 256)      # the big ones are for the thumbnail view


@dataclass(frozen=True)
class IconSet:
    id: str
    title: str
    folder: str
    licence: str = ""
    mapping: dict = field(default_factory=dict)
    builtin: bool = False


_user_dir: Optional[str] = None
_active: str = DEFAULT_SET
_svg_text: dict = {}
_cache: dict = {}


def set_user_dir(path: Optional[str]) -> None:
    """Where the user's own sets live (a folder of set folders). Call before listing sets."""
    global _user_dir
    _user_dir = path
    _forget()


def _read_set(folder: str, builtin: bool) -> Optional[IconSet]:
    """The set in ``folder``, or None when it has no readable manifest. Mapping values must be plain
    ``.svg`` file names: a set can never point outside its own folder."""
    try:
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        mapping = {str(k): str(v) for k, v in dict(data.get("map", {})).items()
                   if str(v).lower().endswith(".svg") and os.path.basename(str(v)) == str(v)}
    except (OSError, ValueError, TypeError):
        return None
    set_id = os.path.basename(folder).lower()
    return IconSet(set_id, str(data.get("title") or set_id), folder, str(data.get("licence", "")), mapping, builtin)


def available_sets() -> list:
    """Built-in sets first, then the user's. A user set cannot take the id of a built-in one."""
    found: dict = {}
    for base, builtin in ((BUILTIN_DIR, True), (_user_dir, False)):
        if not base or not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            folder = os.path.join(base, entry)
            if os.path.isdir(folder):
                s = _read_set(folder, builtin)
                if s is not None and s.id not in found:
                    found[s.id] = s
    # the default first, the rest in the order found (built-in, then the user's)
    return sorted(found.values(), key=lambda s: s.id != DEFAULT_SET)


def active() -> str:
    return _active


def use(set_id: str) -> bool:
    """Switch to a set by id. Returns False (and changes nothing) when there is no such set."""
    global _active
    if set_id not in {s.id for s in available_sets()}:
        return False
    _active = set_id
    _forget()
    return True


def _by_id(set_id: str) -> Optional[IconSet]:
    return next((s for s in available_sets() if s.id == set_id), None)


def resolve(name: str) -> str:
    """The SVG file to draw for ``name``: the active set's file, else the built-in Tabler file, else ''."""
    for s in (_by_id(_active), _by_id(DEFAULT_SET)):
        if s is None:
            continue
        path = os.path.join(s.folder, s.mapping.get(name, name + ".svg"))
        if os.path.isfile(path):
            return path
    return ""


def _source(name: str) -> str:
    key = (_active, name)
    if key not in _svg_text:
        path = resolve(name)
        text = ""
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                text = ""
        _svg_text[key] = text
    return _svg_text[key]


def _render(svg: str, size: int, ratio: float) -> QPixmap:
    px = int(size * ratio)
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, px, px))
    painter.end()
    pix = QPixmap.fromImage(image)
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(name: str, color: Optional[str] = None) -> QIcon:
    """The icon ``name`` in ``color`` (a '#rrggbb' string; default: the scheme's secondary text colour).
    A missing icon is an empty QIcon, never an error."""
    color = color or theme.current()["dim"]
    key = (_active, name, color)
    if key in _cache:
        return _cache[key]
    svg = _source(name)
    result = QIcon()
    app = QGuiApplication.instance()
    ratio = max(1.0, app.devicePixelRatio()) if app else 1.0
    if svg:
        tinted = svg.replace("currentColor", color)
        for size in SIZES:
            result.addPixmap(_render(tinted, size, ratio))
    elif painted_icons.has(name):                 # the set has no file for it: a drawn one, never a blank
        result = painted_icons.icon(name, color, ratio)
    _cache[key] = result
    return result


def _forget() -> None:
    _cache.clear()
    _svg_text.clear()


def clear_cache() -> None:
    """Call when the colour scheme changes."""
    _cache.clear()
