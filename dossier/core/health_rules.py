"""The first file health rules (docs/checkers-plan.md, group A and the zip part of B). Standard library only.

Each rule is a small function registered as a ``Checker``; ``health.run_checks`` calls it with the listing it already has. A rule
reports what it is sure of, with the evidence, and offers a fix only when the fix is obvious (strip, lower-case, delete junk).
"""
from __future__ import annotations

import os
import re
import unicodedata
import zipfile

from .health import (ERROR, FILE, FOLDER, INFO, T0, T1, T2, WARNING, Checker, Fix, finding, register)

JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini", "ehthumbs.db", "icon\r"}
JUNK_SUFFIXES = (".part", ".crdownload", ".dossier-part", ".tmp")
KEEP_EMPTY = {".gitkeep", ".keep", ".nomedia", ".placeholder", "__init__.py", ".gitignore"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
ILLEGAL = set('<>:"|?*') | {chr(i) for i in range(32)}
MOJIBAKE = re.compile("Ã[\u0080-¿]|â€|Â[ -¿]")
MAX_PATH = 259
ZIP_EXTENSIONS = (".zip", ".cbz", ".epub", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".jar")
MAGIC = ((b"PK\x03\x04", "zip"), (b"PK\x05\x06", "zip"), (b"Rar!\x1a\x07", "rar"), (b"7z\xbc\xaf\x27\x1c", "7z"),
         (b"%PDF-", "pdf"), (b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"))
EXPECTED = {".zip": "zip", ".cbz": "zip", ".epub": "zip", ".docx": "zip", ".xlsx": "zip", ".pptx": "zip", ".jar": "zip",
            ".cbr": "rar", ".rar": "rar", ".7z": "7z", ".cb7": "7z", ".pdf": "pdf", ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif"}
SIDECARS = (".srt", ".sub", ".nfo")
MEDIA = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".mpg", ".mpeg", ".ts")


def _splitext(name: str) -> tuple:
    stem, ext = os.path.splitext(name)
    return stem, ext


# tier 0, one file ------------------------------------------------------------------------------------------------------------
def zero_byte(ctx, entry):
    if entry.size == 0 and entry.name.lower() not in KEEP_EMPTY and not entry.is_link:
        yield finding(entry.path, "zero_byte", "empty-file", WARNING, "The file is empty (0 bytes)",
                      fix=Fix("quarantine", "Move to the quarantine folder"))


def junk(ctx, entry):
    low = entry.name.lower()
    if low in JUNK_NAMES or low.endswith(JUNK_SUFFIXES) or low.startswith("~$"):
        yield finding(entry.path, "junk", "junk-file", INFO, "A temporary or system leftover file", fix=Fix("delete", "Delete to the recycle bin"))


def odd_dates(ctx, entry):
    if entry.mtime > ctx.now + 86400:
        yield finding(entry.path, "odd_dates", "future-date", WARNING, "Changed in the future", evidence=f"modified {entry.mtime:.0f}")
    elif 0 < entry.mtime < 315532800:           # before 1980
        yield finding(entry.path, "odd_dates", "old-date", INFO, "Changed before 1980", evidence=f"modified {entry.mtime:.0f}")


def name_problems(ctx, entry):
    name = entry.name
    stem, ext = _splitext(name)
    cid = "names"
    if name != name.rstrip(" ."):
        yield finding(entry.path, cid, "trailing-space-or-dot", WARNING, "The name ends in a space or a dot (Windows cannot keep it)",
                      fix=Fix("rename", "Remove the trailing space or dot", name.rstrip(" .") or "_"))
    if stem.rstrip(" .").lower() in RESERVED:
        yield finding(entry.path, cid, "reserved-name", WARNING, "A name Windows reserves for a device")
    bad = sorted({c for c in name if c in ILLEGAL})
    if bad:
        yield finding(entry.path, cid, "illegal-characters", WARNING, "Characters Windows does not allow in a name",
                      evidence="".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in bad))
    if unicodedata.normalize("NFC", name) != name:
        yield finding(entry.path, cid, "not-nfc", INFO, "The accents are stored as separate characters (NFD); other systems may not match the name",
                      fix=Fix("rename", "Use the composed form (NFC)", unicodedata.normalize("NFC", name)))
    if MOJIBAKE.search(name):
        try:
            fixed = name.encode("cp1252").decode("utf-8")
        except (UnicodeError, ValueError):
            fixed = ""
        yield finding(entry.path, cid, "mojibake", WARNING, "The name looks like text read in the wrong encoding",
                      fix=Fix("rename", "Read it as UTF-8", fixed) if fixed and fixed != name else None)
    if ext and ext != ext.lower() and ext.lower() in EXPECTED:
        yield finding(entry.path, cid, "upper-case-extension", INFO, "The extension is in capitals",
                      fix=Fix("rename", "Lower-case the extension", stem + ext.lower()))
    if len(entry.path) > MAX_PATH:
        yield finding(entry.path, cid, "long-path", WARNING, f"The path is {len(entry.path)} characters long; some programs stop at {MAX_PATH}")


def broken_link(ctx, entry):
    if entry.is_link and not ctx.fs.scheme and not os.path.exists(entry.path):
        yield finding(entry.path, "links", "dead-link", WARNING, "A link that points to nothing", fix=Fix("delete", "Delete the link"))


# tier 1, a few bytes ------------------------------------------------------------------------------------------------------------
def extension_against_content(ctx, entry):
    ext = os.path.splitext(entry.name)[1].lower()
    wanted = EXPECTED.get(ext)
    if not wanted or entry.size < 8:
        return
    with ctx.fs.open_read(entry.path) as fh:
        head = fh.read(8)
    for magic, kind in MAGIC:
        if head.startswith(magic):
            if kind != wanted:
                yield finding(entry.path, "content", "wrong-extension", WARNING, f"The extension says {wanted} but the content is {kind}")
            return


# tier 2, the whole file -----------------------------------------------------------------------------------------------------------
def zip_integrity(ctx, entry):
    try:
        with ctx.fs.open_read(entry.path) as fh:
            head = fh.read(4)
            fh.seek(0)
            if head[:2] != b"PK":
                return                                       # not a zip: the content rule reports it
            with zipfile.ZipFile(fh) as z:
                names = z.namelist()
                bad = z.testzip()
    except zipfile.BadZipFile as e:
        yield finding(entry.path, "zip", "bad-zip", ERROR, "The archive cannot be read", evidence=str(e), fix=Fix("quarantine", "Move to the quarantine folder"))
        return
    if bad:
        yield finding(entry.path, "zip", "bad-crc", ERROR, "An entry is damaged (checksum mismatch)", evidence=bad,
                      fix=Fix("quarantine", "Move to the quarantine folder"))
    if len(set(names)) != len(names):
        yield finding(entry.path, "zip", "duplicate-entries", WARNING, "The same name is stored twice in the archive")
    escaping = [n for n in names if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/") or re.match(r"[A-Za-z]:", n)]
    if escaping:
        yield finding(entry.path, "zip", "path-escape", ERROR, "Entries with an absolute or parent-relative path", evidence=escaping[0])


# folders --------------------------------------------------------------------------------------------------------------------------
def case_twins(ctx, folder, entries):
    seen: dict = {}
    for e in entries:
        seen.setdefault(unicodedata.normalize("NFC", e.name).casefold(), []).append(e)
    for group in seen.values():
        if len(group) > 1:
            for e in group:
                yield finding(e.path, "twins", "case-twin", WARNING, "Another item here differs only in case or accents",
                              evidence=", ".join(x.name for x in group if x is not e))


def empty_folder(ctx, folder, entries):
    if ctx.fs.is_root(folder) or folder in ctx.roots:
        return
    if all((e.name.lower() in JUNK_NAMES) and not e.is_dir for e in entries):
        yield finding(folder, "empty", "empty-folder", INFO, "The folder is empty" if not entries else "The folder holds only junk files",
                      fix=Fix("delete", "Delete the folder to the recycle bin"))


def sidecar_orphans(ctx, folder, entries):
    stems = {os.path.splitext(e.name)[0].lower() for e in entries if not e.is_dir and e.name.lower().endswith(MEDIA)}
    for e in entries:
        if not e.is_dir and e.name.lower().endswith(SIDECARS):
            base = os.path.splitext(e.name)[0].lower()
            if base not in stems and base.rsplit(".", 1)[0] not in stems:          # "film.en.srt" belongs to "film"
                yield finding(e.path, "sidecars", "orphan-sidecar", INFO, "No video here carries this name")


for _c in (Checker("zero_byte", "Empty files", T0, FILE, zero_byte), Checker("junk", "Junk and temporary files", T0, FILE, junk),
           Checker("odd_dates", "Odd dates", T0, FILE, odd_dates), Checker("names", "Name problems", T0, FILE, name_problems),
           Checker("links", "Broken links", T0, FILE, broken_link), Checker("content", "Extension against content", T1, FILE, extension_against_content),
           Checker("zip", "Zip integrity", T2, FILE, zip_integrity, ZIP_EXTENSIONS),
           Checker("twins", "Names that differ only in case", T0, FOLDER, case_twins), Checker("empty", "Empty folders", T0, FOLDER, empty_folder),
           Checker("sidecars", "Sidecar files without a video", T0, FOLDER, sidecar_orphans)):
    register(_c)
