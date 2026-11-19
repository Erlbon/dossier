"""``dossier edit``: the notepad on its own, with no file manager window behind it.

    dossier edit file [file...]

It is the same editor F4 opens (``gui/notepad.py``): the same encoding guess, line breaks and safe save. Each file gets its own window
for now. A file that does not exist opens as an empty text that is saved to that name (the file is made at the first Save, so closing
without saving leaves nothing behind); the folder it names must exist. Closing the last window ends the program. The theme is what was
chosen in Settings, as for ``dossier view``.

``open_notepads`` is the one place that starts the standalone notepad: a single-instance start (card 70) can replace it.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, Optional

USAGE = "dossier edit file [file...]"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dossier edit", description="Edit text files in Dossier's notepad, without the file manager.",
                                     epilog="A file that does not exist opens as an empty text and is made when you save.")
    parser.add_argument("paths", nargs="+", metavar="file", help="a text file; each one opens in its own window")
    return parser


def document_for(path: str):
    """``(Document, note)`` for a path: the file as F4 reads it, or for a missing file an empty text that will be saved there.
    Raises the errors ``load_document`` raises (OSError, FileTooLarge, BinaryFile, EncodingProblem); a missing folder is an OSError."""
    from ..core.textedit import Document, load_document
    if not os.path.exists(path):
        folder = os.path.dirname(path) or "."
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"The folder {folder} does not exist")
        return Document(path, "", "utf-8"), "New file: it is made when you save"
    if os.path.isdir(path):
        raise IsADirectoryError(f"{path} is a folder, not a file")
    return load_document(path), ""


def open_notepads(paths: list, settings, dialogs, problem: Callable[[str], None], windows: list) -> int:
    """Open one notepad window per path and append them to ``windows``. ``problem(text)`` says why a file was not opened.
    Returns how many windows were opened."""
    try:
        from .notepad import NotepadWindow
    except ImportError:
        problem("The editor needs the PyQt6-QScintilla package: pip install PyQt6-QScintilla")
        return 0
    from ..core.textedit import BinaryFile, EncodingProblem, FileTooLarge
    remembered = str(settings.value("editor/markdown_preview", "")).lower()
    syntax = str(settings.value("editor/syntax", "false")).lower() == "true"
    opened = 0
    for given in paths:
        path = os.path.abspath(given)
        try:
            doc, note = document_for(path)
        except FileTooLarge as e:
            problem(f"{path}: {e}. Use dossier view to read it.")
            continue
        except BinaryFile:
            problem(f"{path} looks like a binary file, not text.")
            continue
        except (OSError, EncodingProblem) as e:
            problem(f"{path} could not be opened: {getattr(e, 'strerror', None) or e}")
            continue
        win = NotepadWindow(doc, dialogs, preview={"true": True, "false": False}.get(remembered), syntax=syntax)
        win.syntax_toggled.connect(lambda on, s=settings: s.setValue("editor/syntax", "true" if on else "false"))
        win.preview_toggled.connect(lambda on, w=win, s=settings: s.setValue("editor/markdown_preview", "true" if on else "false")
                                    if w.is_markdown() else None)
        windows.append(win)
        win.closed.connect(lambda w: windows.remove(w) if w in windows else None)
        if note:
            win.message.setText(note)
        win.show()
        opened += 1
    return opened


def main(args: list, *, settings_path: Optional[str] = None, show: bool = True,
         problem: Optional[Callable[[str], None]] = None, windows: Optional[list] = None) -> int:
    ns = build_parser().parse_args(args)
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from ..core.platform import set_app_id
    from .app_settings import open_settings
    from .appicon import app_icon
    from .dialogs import Dialogs
    from .theme import ThemeManager

    set_app_id("Erlbon.Dossier.Notepad")
    app = QApplication.instance() or QApplication(["dossier"])
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())
    settings = open_settings(settings_path)
    manager = ThemeManager(app, str(settings.value("view/scheme", "auto")))
    if problem is None:
        def problem(text: str) -> None:
            QMessageBox.warning(None, "Dossier notepad", text)
    held = windows if windows is not None else []
    if not open_notepads(ns.paths, settings, Dialogs(None), problem, held):
        return 2
    held[0]._theme = manager                                              # kept alive as long as the first window
    if not show:
        return 0
    from .app import leave
    return leave(app.exec())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
