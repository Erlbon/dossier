"""Which icon belongs to which item. Pure names: the GUI turns a name into a picture
(``dossier/gui/icons/<set>/<name>.svg``, see ``gui/icon_set.py``), so this stays Qt-free and testable."""
from __future__ import annotations

import os

GROUPS = {
    "photo": "jpg jpeg png gif webp bmp tif tiff svg ico heic heif avif jfif",
    "music": "mp3 flac ogg opus m4a aac wav wma m4b aiff ape mka",
    "movie": "mkv mp4 avi mov wmv m4v webm ts mpg mpeg flv vob m2ts",
    "book": "epub mobi azw azw3 fb2 kepub lit",
    "book-2": "cbz cbr cb7 cbt",
    "file-type-pdf": "pdf",
    "file-type-doc": "doc docx odt rtf",
    "file-spreadsheet": "xls xlsx ods csv tsv",
    "file-zip": "zip rar 7z tar gz tgz bz2 xz zst lha arj",
    "file-code": ("py pyw js mjs json xml yml yaml toml ini html htm css c cpp h hpp java cs go rs sh bat cmd "
                  "ps1 sql php rb lua"),
    "file-text": "txt log nfo cfg conf srt ass sub vtt lrc",
    "markdown": "md markdown",
    "file-database": "sqlite sqlite3 db mdb accdb",
    "file-settings": "exe msi dll sys",
}
BY_EXTENSION = {ext: icon for icon, exts in GROUPS.items() for ext in exts.split()}

FOLDER, UP, LINK, FALLBACK = "folder", "corner-left-up", "link", "file"
DRIVE_ICONS = {"fixed": "device-desktop", "removable": "usb", "network": "network", "optical": "disc",
               "other": "database", "home": "home"}


def icon_name(name: str, *, is_dir: bool = False, is_link: bool = False, is_up: bool = False) -> str:
    """The icon name for a folder entry."""
    if is_up:
        return UP
    if is_link:
        return LINK
    if is_dir:
        return FOLDER
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    return BY_EXTENSION.get(ext, FALLBACK)


def all_icon_names() -> set:
    """Every name this module can return, for the test that checks the files exist."""
    return set(GROUPS) | set(DRIVE_ICONS.values()) | {FOLDER, UP, LINK, FALLBACK}
