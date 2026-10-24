"""Writing the metadata inside files: the tags of mp3, flac, ogg, opus and m4a files, and the ComicInfo of a cbz. Qt-free; step 2 of
docs/metadata-plan.md (reading is ``properties.py`` and the Redactor readers).

Like the dates, a change is a *plan* first: ``plan`` reads what the files carry now and says, per file, which fields would change and
from what to what; nothing is written until ``apply`` is given the plan. Only the fields you give are touched, and a field you leave out
stays as it is, so a tag Dossier knows nothing about (cover art, lyrics, a custom frame) is never lost. An empty new value removes a field.

A file is never changed in place. The new version is made beside the old one (a copy with the new tags, or for a cbz a rewritten zip),
read back and checked, and only then put in the old one's place; the old file goes to the recycle bin (to be deleted at once on a drive
that has none). Any failure or a cancel leaves the original exactly as it was. The tags Dossier keeps on the file itself (rating, label)
follow the file.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from . import zipwrite
from .platform import has_scheme
from .progress import CancelToken, check

AUDIO, COMIC = "audio", "comic"
AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".mp4a")
COMIC_EXTENSIONS = (".cbz",)
TEMP_SUFFIX = ".dossier-part"
MAX_XML = 2 * 1024 * 1024
MAX_VALUE = 20_000
CHUNK = 1 << 20

# (key, label). An audio key is mutagen's "easy" name; a comic key is the ComicInfo element.
AUDIO_FIELDS = (("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("albumartist", "Album artist"), ("tracknumber", "Track"),
                ("discnumber", "Disc"), ("date", "Year or date"), ("genre", "Genre"), ("composer", "Composer"))
# ComicInfo.xml keeps its elements in this order (schema 2.0); a new element goes where it belongs.
COMIC_ORDER = ("Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber", "AlternateCount", "Summary", "Notes", "Year",
               "Month", "Day", "Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist", "Editor", "Translator", "Publisher", "Imprint",
               "Genre", "Tags", "Web", "PageCount", "LanguageISO", "Format", "BlackAndWhite", "Manga", "Characters", "Teams", "Locations",
               "ScanInformation", "StoryArc", "StoryArcNumber", "SeriesGroup", "AgeRating", "Pages", "CommunityRating", "MainCharacterOrTeam",
               "Review", "GTIN")
COMIC_FIELDS = (("Series", "Series"), ("Number", "Number"), ("Count", "Count"), ("Volume", "Volume"), ("Title", "Title"), ("Summary", "Summary"),
                ("Year", "Year"), ("Month", "Month"), ("Day", "Day"), ("Writer", "Writer"), ("Penciller", "Penciller"), ("Inker", "Inker"),
                ("Colorist", "Colorist"), ("Letterer", "Letterer"), ("CoverArtist", "Cover artist"), ("Editor", "Editor"),
                ("Publisher", "Publisher"), ("Imprint", "Imprint"), ("Genre", "Genre"), ("Tags", "Tags"), ("LanguageISO", "Language"),
                ("AgeRating", "Age rating"), ("Manga", "Manga"), ("Web", "Web"))
INTEGER_FIELDS = ("Count", "Volume", "Year", "Month", "Day")
MANGA_VALUES = ("Unknown", "No", "Yes", "YesAndRightToLeft")


class MetaWriteError(OSError):
    """A file's metadata could not be written; the file is as it was."""


@dataclass(frozen=True)
class FieldChange:
    key: str
    label: str
    old: str
    new: str                          # empty: the field is taken away


@dataclass
class Item:
    path: str
    kind: str = ""
    changes: list = field(default_factory=list)
    problem: str = ""                 # why this file is left out (the plan shows it, ``apply`` skips it)

    @property
    def writable(self) -> bool:
        return not self.problem and bool(self.changes)


@dataclass
class Applied:
    done: int = 0
    failed: list = field(default_factory=list)      # (path, reason)


def kind_of(path: str) -> str:
    low = path.lower()
    return AUDIO if low.endswith(AUDIO_EXTENSIONS) else COMIC if low.endswith(COMIC_EXTENSIONS) else ""


def fields_for(kind: str) -> tuple:
    return AUDIO_FIELDS if kind == AUDIO else COMIC_FIELDS if kind == COMIC else ()


def label_of(kind: str, key: str) -> str:
    return dict(fields_for(kind)).get(key, key)


def why_not_writable(path: str) -> str:
    """Empty when the metadata of ``path`` can be written, else the reason in plain words."""
    if has_scheme(path):
        return "only files on a drive of this computer can be changed (not inside an archive or on a server)"
    kind = kind_of(path)
    if not kind:
        return "the tags of this kind of file cannot be written yet (mp3, flac, ogg, opus and m4a files, and cbz comics can)"
    if not os.path.isfile(path):
        return "the file is not there"
    if not os.access(path, os.W_OK):
        return "the file is read-only: clear its read-only attribute first"
    if kind == AUDIO:
        try:
            import mutagen  # noqa: F401
        except ImportError:
            return "the tag library (mutagen) is not installed"
    return ""


def check_value(kind: str, key: str, value: str) -> str:
    """Why ``value`` cannot be stored in ``key``, or an empty string."""
    if len(value) > MAX_VALUE:
        return "too long"
    if "\x00" in value:
        return "contains a null character"
    if kind == COMIC:
        if key in INTEGER_FIELDS and value and not value.strip().isdigit():
            return "must be a whole number"
        if key == "Month" and value and not 1 <= int(value) <= 12:
            return "must be 1 to 12"
        if key == "Day" and value and not 1 <= int(value) <= 31:
            return "must be 1 to 31"
        if key == "Manga" and value and value not in MANGA_VALUES:
            return "must be one of " + ", ".join(MANGA_VALUES)
    return ""


# reading ---------------------------------------------------------------------------------------------------------------------------------------
def _audio_values(path: str) -> dict:
    import mutagen
    try:
        easy = mutagen.File(path, easy=True)
    except Exception as e:   # noqa: BLE001 -- a damaged file is a per-file problem, not a crash
        raise MetaWriteError(f"the file could not be read: {e}") from e
    if easy is None:
        raise MetaWriteError("this is not an audio file Dossier can read")
    tags = easy.tags or {}
    out = {}
    for key, _label in AUDIO_FIELDS:
        try:
            values = tags.get(key)
        except (KeyError, ValueError):
            values = None
        out[key] = "; ".join(str(v) for v in values) if values else ""
    return out


def _comic_member(names: list) -> str:
    best, depth = "", 1 << 30
    for name in names:
        flat = name.replace(chr(92), "/")
        if flat.rsplit("/", 1)[-1].lower() == "comicinfo.xml" and flat.count("/") < depth:
            best, depth = name, flat.count("/")
    return best


def _comic_root(path: str) -> tuple:
    """``(member name or "", the parsed ComicInfo root or None)`` of the cbz at ``path``."""
    try:
        with zipfile.ZipFile(path) as z:
            member = _comic_member([i.filename for i in z.infolist()])
            if not member:
                return "", None
            info = z.getinfo(member)
            if info.file_size > MAX_XML:
                raise MetaWriteError(f"ComicInfo.xml is {info.file_size:,} bytes, too large to change safely")
            try:
                return member, ET.fromstring(z.read(member))
            except ET.ParseError as e:
                raise MetaWriteError(f"ComicInfo.xml is not valid XML ({e}); it was left alone") from e
    except zipfile.BadZipFile as e:
        raise MetaWriteError("not a zip archive (only cbz comics can be changed; convert a cbr to zip first)") from e


def _comic_values(path: str) -> dict:
    _member, root = _comic_root(path)
    out = {}
    for key, _label in COMIC_FIELDS:
        node = root.find(key) if root is not None else None
        out[key] = (node.text or "").strip() if node is not None else ""
    return out


def read_values(path: str) -> dict:
    """The current value of every editable field of the file at ``path`` (empty text where it has none). Raises ``MetaWriteError``."""
    kind = kind_of(path)
    if kind == AUDIO:
        return _audio_values(path)
    if kind == COMIC:
        return _comic_values(path)
    raise MetaWriteError("the tags of this kind of file cannot be read for editing")


def common_values(paths: Iterable[str]) -> tuple:
    """``(kind, values, problems)`` for a group of files of one kind: each field's value when every file has the same, ``None`` when they differ.
    ``kind`` is empty (and ``values`` empty) when the files are not all of one editable kind. ``problems`` maps a path to why it could not be read."""
    paths = list(paths)
    kinds = {kind_of(p) for p in paths}
    if len(kinds) != 1 or "" in kinds:
        return "", {}, {}
    kind = next(iter(kinds))
    merged: dict = {}
    problems: dict = {}
    first = True
    for path in paths:
        try:
            values = read_values(path)
        except OSError as e:
            problems[path] = str(e)
            continue
        if first:
            merged, first = dict(values), False
        else:
            for key, value in values.items():
                if merged.get(key) != value:
                    merged[key] = None
    return kind, merged, problems


# planning --------------------------------------------------------------------------------------------------------------------------------------
def plan(paths: Iterable[str], edits: dict, cancel: Optional[CancelToken] = None) -> list:
    """What each file's fields would become. ``edits`` maps a field key to its new text (``""`` takes the field away); a key not in it is not
    touched. A file whose value is already the new one has no change; a file that cannot be changed carries a ``problem``."""
    items: list = []
    for path in paths:
        check(cancel)
        kind = kind_of(path)
        item = Item(path, kind)
        items.append(item)
        item.problem = why_not_writable(path)
        if item.problem:
            continue
        known = dict(fields_for(kind))
        unknown = [k for k in edits if k not in known]
        if unknown:
            item.problem = "this kind of file has no field " + ", ".join(sorted(unknown))
            continue
        bad = [f"{known[k]} {why}" for k, v in edits.items() if (why := check_value(kind, k, v))]
        if bad:
            item.problem = "; ".join(bad)
            continue
        try:
            current = read_values(path)
        except OSError as e:
            item.problem = str(e)
            continue
        item.changes = [FieldChange(k, known[k], current.get(k, ""), v) for k, v in edits.items() if current.get(k, "") != v]
    return items


# writing ---------------------------------------------------------------------------------------------------------------------------------------
def _copy(src: str, dst: str, cancel: Optional[CancelToken]) -> None:
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            check(cancel)
            block = fin.read(CHUNK)
            if not block:
                break
            fout.write(block)
    shutil.copystat(src, dst)


def _write_audio(path: str, changes: dict, cancel, trasher) -> None:
    import mutagen
    part = path + TEMP_SUFFIX
    try:
        _copy(path, part, cancel)
        easy = mutagen.File(part, easy=True)
        if easy is None:
            raise MetaWriteError("this is not an audio file Dossier can write")
        if easy.tags is None:
            easy.add_tags()
        for key, value in changes.items():
            try:
                if value:
                    easy[key] = [value]
                elif key in easy:
                    del easy[key]
            except (ValueError, KeyError) as e:
                raise MetaWriteError(f"{label_of(AUDIO, key)}: {e}") from e
        easy.save()
        again = _audio_values(part)                                # the copy must read back with exactly what was asked for
        for key, value in changes.items():
            if again.get(key, "") != value and not (key in ("tracknumber", "discnumber", "date") and again.get(key, "").startswith(value)):
                raise MetaWriteError(f"{label_of(AUDIO, key)} did not read back as written; the file was left as it was")
        _carry_tags(path, part)
        check(cancel)
        zipwrite.swap_in(path, part, trasher)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def _carry_tags(src: str, dst: str) -> None:
    """The rating and label Dossier keeps on the file itself belong to the new file too (a copy does not carry them)."""
    try:
        from . import filetags
        filetags.copy_tags(src, dst)
    except Exception:   # noqa: BLE001 -- the metadata edit must not fail because a tag could not follow
        pass


def _comic_xml(root: ET.Element, changes: dict) -> bytes:
    for key, value in changes.items():
        node = root.find(key)
        if not value:
            if node is not None:
                root.remove(node)
            continue
        if node is None:
            node = ET.Element(key)
            position = len(root)
            wanted = COMIC_ORDER.index(key) if key in COMIC_ORDER else len(COMIC_ORDER)
            for i, child in enumerate(root):
                if child.tag in COMIC_ORDER and COMIC_ORDER.index(child.tag) > wanted:
                    position = i
                    break
            root.insert(position, node)
        node.text = value
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>' + b"\n" + ET.tostring(root, encoding="utf-8")


def _write_comic(path: str, changes: dict, cancel, trasher) -> None:
    member, root = _comic_root(path)
    if root is None:
        root = ET.Element("ComicInfo")
    xml = _comic_xml(root, changes)
    folder = tempfile.mkdtemp(prefix="dossier-comicinfo-")
    try:
        source = os.path.join(folder, "ComicInfo.xml")
        with open(source, "wb") as f:
            f.write(xml)
        zipwrite.rewrite(path, add=[(member or "ComicInfo.xml", source)], cancel=cancel, trasher=trasher)
        with zipfile.ZipFile(path) as z:                              # what is in the archive now must say what was asked for
            name = _comic_member([i.filename for i in z.infolist()])
            back = ET.fromstring(z.read(name))
        for key, value in changes.items():
            node = back.find(key)
            if ((node.text or "").strip() if node is not None else "") != value:
                raise MetaWriteError(f"{label_of(COMIC, key)} did not read back as written")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def apply(items: Iterable[Item], cancel: Optional[CancelToken] = None, progress: Optional[Callable[[int, int], None]] = None,
          trasher: Optional[Callable[[str], None]] = None) -> Applied:
    """Write a plan. A file that fails is listed and the rest goes on; a cancel stops between files and leaves the one it was on as it was.
    ``trasher`` takes the old file away once the new one is in place (the recycle bin; default: delete it)."""
    todo = [i for i in items if i.writable]
    result = Applied()
    for n, item in enumerate(todo, 1):
        check(cancel)
        changes = {c.key: c.new for c in item.changes}
        try:
            if not os.path.isfile(item.path):
                raise MetaWriteError("the file is gone")
            (_write_audio if item.kind == AUDIO else _write_comic)(item.path, changes, cancel, trasher)
            result.done += 1
        except zipwrite.ZipWriteError as e:
            result.failed.append((item.path, str(e)))
        except OSError as e:
            result.failed.append((item.path, str(getattr(e, "strerror", None) or e)))
        if progress:
            progress(n, len(todo))
    return result
