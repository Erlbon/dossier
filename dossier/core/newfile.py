"""Making a file from something that is not a file: a picture or some text from the clipboard, or dropped on a panel. Qt-free.

The window turns the clipboard or the drop into bytes and a suggested name; this makes the file. It never replaces what is there: a name
that is taken gets ``(2)``, ``(3)``... and the file is created exclusively, so two of them at once cannot write into the same file.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from .ops import check_name
from .vfs import FileSystem

IMAGE, TEXT, LINK = "image", "text", "link"
EXTENSION = {IMAGE: ".png", TEXT: ".txt", LINK: ".url"}
WORDS = {IMAGE: "picture", TEXT: "text", LINK: "web link"}
MAX_TRIES = 200


def suggested_name(kind: str, now: Optional[datetime] = None, url: str = "") -> str:
    """``Pasted image 2026-10-24 10.30.12.png`` (colons are not allowed in a Windows name); a web link is named after its site."""
    if kind == LINK:
        host = urlsplit(url).hostname or "link"
        return f"{host}{EXTENSION[LINK]}"
    when = (now or datetime.now()).strftime("%Y-%m-%d %H.%M.%S")
    return f"Pasted {'image' if kind == IMAGE else 'text'} {when}{EXTENSION[kind]}"


def link_file(url: str) -> bytes:
    """The content of an Internet Shortcut (``.url``) file for ``url``: the format Windows, and most file managers, understand."""
    return f"[InternetShortcut]\r\nURL={url.strip()}\r\n".encode("utf-8")


def clean_name(name: str, kind: str) -> str:
    """The name as typed, with the extension the kind needs when it has none. Raises ``ValueError`` with the reason when it cannot be a name."""
    name = (name or "").strip()
    why = check_name(name)
    if why:
        raise ValueError(why)
    if kind == LINK:
        if not name.lower().endswith(EXTENSION[LINK]):             # "example.org" is a site, not an extension: a shortcut always ends in .url
            name += EXTENSION[LINK]
    elif not os.path.splitext(name)[1]:
        name += EXTENSION[kind]
    return name


def write_new_file(fs: FileSystem, folder: str, name: str, data: bytes) -> str:
    """Create ``name`` in ``folder`` with ``data``; a name that is taken becomes ``name (2).ext``. Returns the path made. The file is
    never opened for overwriting, and one that fails halfway is removed again."""
    stem, ext = os.path.splitext(name)
    for n in range(1, MAX_TRIES + 1):
        path = fs.join(folder, name if n == 1 else f"{stem} ({n}){ext}")
        try:
            handle = fs.open_write(path, exclusive=True)
        except FileExistsError:
            continue
        try:
            with handle:
                handle.write(data)
        except BaseException:
            try:
                fs.remove(path)
            except OSError:
                pass
            raise
        return path
    raise FileExistsError(f"too many files named like {name} in {folder}")
