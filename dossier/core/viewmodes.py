"""Which viewer a file gets in F3, chosen by what is inside it and not only by its name.

``image``    a picture (judged by its first bytes, so a photo called ``.dat`` is still shown as a photo; an SVG by its first element
             and its name);
``document`` a document (Word, OpenDocument text, RTF, PowerPoint, EPUB; by name, confirmed by its first bytes): its text, read by
             ``core/officedoc.py`` and ``core/textdocs.py``;
``sheet``    a table (Excel, OpenDocument spreadsheet, CSV/TSV, a SQLite database by its first bytes, a torrent's listing): its
             values in a grid, read by ``core/officesheet.py``, ``core/datatables.py`` and ``core/torrent.py``; and the
             forensic listings of ``core/forensic.py`` (Windows shortcuts, Recycle Bin records, property lists);
``pdf``      a PDF (by its first bytes): its pages, drawn by Qt's PDF module;
``markdown`` a text file that is Markdown (by its extension: nothing in the content tells it from plain text);
``text``     any other text;
``hex``      a binary file (zero bytes in text that is not wide), where text would only be noise.

Every file can also be seen in the other modes that make sense for it (``modes_for``), so a Markdown file can be read as its source
and any file as hex. Qt-free; the window decides how each mode is drawn.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .officedoc import document_kind
from .officesheet import sheet_kind
from .textview import SAMPLE, detect_encoding, looks_binary
from .vfs import natural_key

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".svg", ".svgz")
SVG_EXTENSIONS = (".svg", ".svgz")
MARKDOWN_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd", ".mkdn")
HEAD = 8192
LABELS = {"image": "Image", "document": "Document", "sheet": "Spreadsheet", "pdf": "PDF", "markdown": "Markdown", "text": "Text", "hex": "Hex"}
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
    if name.lower().endswith(SVG_EXTENSIONS) and is_svg(head):
        return "svg"
    return ""


def is_svg(head: bytes) -> bool:
    """An SVG drawing: a gzip stream (.svgz), or text whose first element is ``<svg`` (after an XML declaration, comments or a
    DOCTYPE). Believed only with an .svg or .svgz name: plenty of XML files hold an svg element somewhere."""
    if head[:2] == b"\x1f\x8b":
        return True
    text = head.decode("utf-8", "ignore").lstrip(chr(0xFEFF))
    while True:
        text = text.lstrip()
        if text.startswith("<?") or text.startswith("<!--") or text.startswith("<!DOCTYPE") or text.startswith("<!doctype"):
            end = text.find("-->" if text.startswith("<!--") else ">")
            if end < 0:
                return False
            text = text[end + (3 if text.startswith("<!--") else 1):]
            continue
        return text.startswith("<svg") or text.startswith("<svg:svg")


# Containers that are never text, whatever their zero bytes suggest: a Word 97 .doc keeps its text as UTF-16, and when that text is near
# the start the zero-byte count reads as wide text, so the .doc went to the viewer (and showed as hex) instead of to Word.
BINARY_MAGIC = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",   # OLE2: .doc .xls .ppt .msg
                b"PK\x03\x04", b"PK\x05\x06",          # zip and everything built on it: .docx .xlsx .odt .epub .cbz
                b"%PDF-", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b", b"SQLite format 3\x00", b"\x1aE\xdf\xa3")


def is_binary(head: bytes) -> bool:
    if head.startswith(BINARY_MAGIC):
        return True
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
    if document_kind(head, path):
        return "document"
    if sheet_kind(head, path):
        return "sheet"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if is_binary(head):
        return "hex"
    if path.lower().endswith(MARKDOWN_EXTENSIONS):
        return "markdown"
    return "text"


def modes_for(path: str, head: Optional[bytes] = None) -> list:
    """The modes that make sense for ``path``, the one F3 opens first."""
    first = mode_for(path, head)
    others = {"image": ["hex"], "document": ["hex"], "sheet": ["hex"], "pdf": ["hex"], "markdown": ["text", "hex"], "text": ["hex"],
              "hex": ["text"]}[first]
    if first == "image" and path.lower().endswith(".svg"):
        others = ["text", "hex"]                    # an SVG is also its XML
    elif first in ("document", "sheet") and text_underneath(path, head):
        others = ["text", "hex"]
    return [first] + others


def text_underneath(path: str, head: Optional[bytes] = None) -> bool:
    """RTF and CSV are text files shown as a document or a table; every other document or table format is binary (a small torrent
    may happen to hold no zero byte, and must still not count as text)."""
    if head is None:
        head = read_head(path)
    return document_kind(head, path) == "rtf" or sheet_kind(head, path) == "csv" or (
        sheet_kind(head, path) == "plist" and not head.startswith(b"bplist"))     # an XML plist is text too


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
    binary file goes to the system program, so a program is not shown as hex by accident, and so do Office files, PDFs, databases
    and torrents: their programs show the layout or act on them, the viewer only the text and values (F3 or Ctrl+Enter shows those).
    A text file stays in the viewer, also when it is shown as a table (CSV) or a document (RTF).
    """
    if choice == "system":
        wanted = False
    elif choice == "all":
        wanted = True
    elif local:
        head = read_head(path)
        mode = mode_for(path, head)
        wanted = mode in ("image", "markdown", "text") or (mode in ("document", "sheet") and text_underneath(path, head))
    else:
        wanted = viewable_by_name(path)
    return wanted != alternate


def image_siblings(names: list) -> list:
    """The picture files among ``names`` (plain file names), in the order a person counts them: ``img2`` before ``img10``."""
    return sorted((n for n in names if n.lower().endswith(IMAGE_EXTENSIONS)), key=natural_key)


def pictures_around(path: str, list_names: Optional[Callable] = None) -> tuple:
    """The pictures in the folder of ``path`` in natural order, and the place of ``path`` among them (so next and previous step through
    the folder). ``list_names(folder)`` gives the file names there (``os.listdir`` when not given); ``[path], 0`` when the folder cannot be
    read or ``path`` is not among them. The name is matched as Windows does, without regard to case."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        names = image_siblings((list_names or os.listdir)(folder))
    except OSError:
        return [path], 0
    paths = [os.path.join(folder, n) for n in names]
    key = os.path.normcase(os.path.abspath(path))
    for i, p in enumerate(paths):
        if os.path.normcase(p) == key:
            return paths, i
    return [path], 0


def is_image_name(path: str) -> bool:
    return os.path.basename(path).lower().endswith(IMAGE_EXTENSIONS)
