"""``dossier view``: the picture viewer on its own, with no file manager window behind it.

    dossier view [--glass frosted|dim|solid|0-100] [--scheme auto|light|dark] picture...

One picture opens it with the other pictures of its folder following (the arrow keys and the wheel step through them); several pictures
open just those; a folder opens its first picture. The look is what was chosen in Settings, unless a parameter says otherwise for this
run: ``--glass`` is a mode (``frosted``, the default, then ``dim`` or ``solid``), how much shows through (0 is solid, 100 almost clear), or
both as ``frosted:60``; ``--scheme`` is the colour scheme of the layer and the bar.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from ..core import glass, viewmodes

USAGE = "dossier view [--glass frosted|dim|solid|0-100] [--scheme auto|light|dark] picture..."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dossier view", description="Show pictures in the see-through glass viewer.")
    parser.add_argument("paths", nargs="*", metavar="picture", help="a picture (its folder's pictures follow), several pictures, or a folder")
    parser.add_argument("--glass", metavar="LOOK", help="frosted (default), dim, solid, a number 0-100 for how much shows through, or frosted:60")
    parser.add_argument("--scheme", choices=("auto", "light", "dark"), help="the colour scheme of the glass and the bar")
    return parser


def pictures_for(paths: list) -> tuple:
    """``(pictures, first index)`` for what was named on the command line; ``([], 0)`` when there is no picture in it."""
    from .glass_viewer import pictures_around
    named = [os.path.abspath(p) for p in paths]
    if len(named) == 1:
        path = named[0]
        if os.path.isdir(path):
            try:
                found = viewmodes.image_siblings(os.listdir(path))
            except OSError:
                return [], 0
            return [os.path.join(path, n) for n in found], 0
        return pictures_around(path) if os.path.isfile(path) and viewmodes.is_image_name(path) else ([], 0)
    return [p for p in named if os.path.isfile(p) and viewmodes.is_image_name(p)], 0


def main(args: list, *, settings_path: Optional[str] = None, show: bool = True) -> int:
    parser = build_parser()
    ns = parser.parse_args(args)
    try:
        asked_mode, asked_level = glass.parse(ns.glass) if ns.glass else (None, None)
    except ValueError as e:
        parser.error(str(e))
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from ..core.platform import set_app_id
    from .app_settings import open_settings
    from .appicon import app_icon
    from .glass_viewer import GlassViewer, saved_look
    from .theme import ThemeManager

    set_app_id("Erlbon.Dossier.Viewer")
    app = QApplication.instance() or QApplication(["dossier"])
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())
    settings = open_settings(settings_path)
    manager = ThemeManager(app, ns.scheme or str(settings.value("view/scheme", "auto")))
    pictures, first = pictures_for(ns.paths)
    if not pictures:
        QMessageBox.information(None, "Dossier picture viewer", ("There is no picture in " + ", ".join(ns.paths) + ".") if ns.paths
                                else "Name a picture to show:\n\n" + USAGE)
        return 2
    saved_mode, saved_level = saved_look(settings)
    mode = asked_mode or saved_mode
    level = asked_level if asked_level is not None else (None if asked_mode else saved_level)
    window = GlassViewer(pictures, first, mode, level)
    window._theme = manager                                              # kept alive as long as the window
    window.show()
    if not show:
        return 0
    from .app import leave
    return leave(app.exec())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
