"""Opening and deleting the program's opt-in logs (the slowness log, the error log): one way for both."""
from __future__ import annotations

import os
from typing import Callable


def open_log(window, path: str, title: str, empty: str) -> None:
    """Open the log in Dossier's editor, or say why there is nothing yet."""
    if not os.path.isfile(path):
        window.dialogs.info(title, empty)
        return
    window.edit_file(path)


def delete_log(window, path: str, title: str, question: str, remove: Callable[[str], None] = os.remove) -> None:
    """Ask, close it in the editor if it is open there, and delete it."""
    if not os.path.isfile(path):
        window._say(f"There is no {title.lower()}")
        return
    if not window.dialogs.confirm(f"Delete the {title}", question, "Delete"):
        return
    for editor in list(window.editors):
        if os.path.normcase(editor.doc.path) == os.path.normcase(path):
            editor.close()
    try:
        remove(path)
        window._say(f"{title} deleted")
    except OSError as e:
        window.dialogs.info(title, f"Could not delete it: {e.strerror or e}")
