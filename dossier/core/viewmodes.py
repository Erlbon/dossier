"""Which viewer a file gets in F3, chosen by what is inside it and not only by its name.

``image``    a picture (judged by its first bytes, so a photo called ``.dat`` is still shown as a photo);
``markdown`` a text file that is Markdown (by its extension: nothing in the content tells it from plain text);
``text``     any other text;
``hex``      a binary file (zero bytes in text that is not wide), where text would only be noise.

Every file can also be seen in the other modes that make sense for it (``modes_for``), so a Markdown file can be read as its source
and any file as hex. Qt-free; the window decides how each mode is drawn.
"""
from __future__ import annotations

import os
from typing import Optional

from .textview import SAMPLE, detect_encoding, looks_binary
from .vfs import natural_key

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico")
MARKDOWN_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd", ".mkdn")
HEAD = 8192
LABELS = {"image": "Image", "markdown": "Markdown", "text": "Text", "hex": "Hex"}
MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"),
         (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"), (b"\x00\x00\x01\x00", "ico"))


def image_kind(head: bytes, name: str = "") -> str:
    """The picture format the first bytes show (png, jpeg, gif, tiff, ico, webp, bmp), or an empty string. A BMP header is only two
    letters, so it is believed only together with the ``.bmp`` name."""
    for magic, kind in MAGIC:
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:2] == b"BM" and name.lower().endswith(".bmp") and len(head) >= 14:
        return "bmp"
    return ""


def is_binary(head: bytes) -> bool:
    return bool(head) and looks_binary(head[:SAMPLE], detect_encoding(head[:SAMPLE]))


def read_head(path: str, size: int = HEAD) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(size)
    except OSError:
        return b""


def mode_for(path: str, head: Optional[bytes] = None) -> str:
    """The mode F3 opens ``path`` in."""
    if head is None:
        head = read_head(path)
    if image_kind(head, path):
        return "image"
    if is_binary(head):
        return "hex"
    if path.lower().endswith(MARKDOWN_EXTENSIONS):
        return "markdown"
    return "text"


def modes_for(path: str, head: Optional[bytes] = None) -> list:
    """The modes that make sense for ``path``, the one F3 opens first."""
    first = mode_for(path, head)
    others = {"image": ["hex"], "markdown": ["text", "hex"], "text": ["hex"], "hex": ["text"]}[first]
    return [first] + others


OPEN_CHOICES = (("viewer", "Pictures, text and Markdown in the viewer, the rest in the Windows program"),
                ("system", "Always in the Windows program"),
                ("all", "Everything in the viewer"))
TEXT_EXTENSIONS = (".txt", ".log", ".json", ".xml", ".csv", ".tsv", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".toml", ".py", ".js",
                   ".html", ".htm", ".css", ".c", ".h", ".cpp", ".cs", ".java", ".sh", ".bat", ".ps1", ".sql", ".nfo", ".srt")


def viewable_by_name(path: str) -> bool:
    """A file inside an archive is not read just to decide: its name says whether the viewer shows it well."""
    return path.lower().endswith(IMAGE_EXTENSIONS + MARKDOWN_EXTENSIONS + TEXT_EXTENSIONS)


def opens_in_viewer(path: str, choice: str, alternate: bool = False, local: bool = True) -> bool:
    """Whether Enter or a double-click on ``path`` shows it in the viewer (True) or hands it to the program Windows has for it (False).

    ``choice`` is the setting (``viewer``, ``system`` or ``all``); ``alternate`` (Ctrl+Enter) does the other thing. Under ``viewer`` a
    binary file goes to the system program, so a Word document or a program is not shown as hex by accident.
    """
    if choice == "system":
        wanted = False
    elif choice == "all":
        wanted = True
    else:
        wanted = mode_for(path) != "hex" if local else viewable_by_name(path)
    return wanted != alternate


def image_siblings(names: list) -> list:
    """The picture files among ``names`` (plain file names), in the order a person counts them: ``img2`` before ``img10``."""
    return sorted((n for n in names if n.lower().endswith(IMAGE_EXTENSIONS)), key=natural_key)


def is_image_name(path: str) -> bool:
    return os.path.basename(path).lower().endswith(IMAGE_EXTENSIONS)
