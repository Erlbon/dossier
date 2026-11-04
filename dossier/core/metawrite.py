"""Writing the metadata inside files: the tags of mp3, flac, ogg, opus and m4a files, and the ComicInfo of a cbz. Qt-free; step 2 of
docs/metadata-plan.md (reading is ``properties.py`` and the Redactor readers).

Like the dates, a change is a *plan* first: ``plan`` reads what the files carry now and says, per file, which fields would change and
from what to what; nothing is written until ``apply`` is given the plan. Only the fields you give are touched, and a field you leave out
stays as it is, so a tag Dossier knows nothing about (cover art, lyrics, a custom frame) is never lost. An empty new value removes a field.

A file is never changed in place. The new version is made beside the old one (a copy with the new tags, or for a cbz a rewritten zip),
read back and checked, and only then put in the old one's place; the old file goes to the recycle bin (to be deleted at once on a drive
that has none). Any failure or a cancel leaves the original exactly as it was. The tags Dossier keeps on the file itself (rating, label)
follow the file.

The writing is redactor_common's (since 2026-11-04 the one tag writer Dossier, cbzredactor and mp3redactor share): ``audio_write`` for
the tags (an ID3 v2.3 tag stays v2.3; the copy reads back before the swap) and ``comicinfo_write`` for ComicInfo.xml (schema order, the
xsi/xsd namespaces declared, empty elements dropped, PageCount refreshed from the pages, a nested ComicInfo.xml moved to the root, the new
XML checked before the swap). ``tests/test_shared_writers.py`` fails if tags, ComicInfo.xml or a zip are written anywhere else.
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from redactor_common.cli import CliError
from redactor_common.cli.values import check_text
from redactor_common.core import audio_write, comicinfo_write
from redactor_common.core.zip_rewrite import RewriteCancelled, RewriteError

from . import zipwrite
from .platform import has_scheme
from .progress import Cancelled, CancelToken, check

AUDIO, COMIC = "audio", "comic"
AUDIO_EXTENSIONS = audio_write.AUDIO_EXTENSIONS
COMIC_EXTENSIONS = (".cbz",)
TEMP_SUFFIX = ".dossier-part"
MAX_XML = comicinfo_write.MAX_COMICINFO_BYTES
MAX_VALUE = comicinfo_write.MAX_VALUE

# (key, label). An audio key is mutagen's "easy" name; a comic key is the ComicInfo element.
AUDIO_FIELDS = audio_write.AUDIO_FIELDS
AUDIO_LIST_FIELDS = ("artist", "albumartist", "genre", "composer")    # may hold several values, shown joined with AUDIO_SEPARATOR
AUDIO_SEPARATOR = "; "
# ComicInfo.xml keeps its elements in this order (schema 2.0 and the 2.1 draft); the shared writer puts every element in its place.
COMIC_ORDER = comicinfo_write.COMICINFO_ORDER
COMIC_FIELDS = (("Series", "Series"), ("Number", "Number"), ("Count", "Count"), ("Volume", "Volume"), ("Title", "Title"), ("Summary", "Summary"),
                ("Year", "Year"), ("Month", "Month"), ("Day", "Day"), ("Writer", "Writer"), ("Penciller", "Penciller"), ("Inker", "Inker"),
                ("Colorist", "Colorist"), ("Letterer", "Letterer"), ("CoverArtist", "Cover artist"), ("Editor", "Editor"),
                ("Publisher", "Publisher"), ("Imprint", "Imprint"), ("Genre", "Genre"), ("Tags", "Tags"), ("LanguageISO", "Language"),
                ("AgeRating", "Age rating"), ("Manga", "Manga"), ("Web", "Web"))
INTEGER_FIELDS = ("Count", "Volume", "Year", "Month", "Day")
MULTILINE_FIELDS = ("Summary", "Notes", "Review", "comment", "lyrics")    # may hold line breaks and tabs
MANGA_VALUES = comicinfo_write.MANGA_VALUES


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
    """Why ``value`` cannot be stored in ``key``, or an empty string (the shared writer's checks: control characters, whole numbers,
    month and day ranges, the fixed value lists)."""
    if kind == COMIC:
        return comicinfo_write.check_comicinfo_value(key, value)
    if len(value) > MAX_VALUE:
        return "too long"
    try:
        check_text(key, value, multiline=key in MULTILINE_FIELDS)
    except CliError as e:
        return str(e)[len(key):].strip()
    return ""


# reading ---------------------------------------------------------------------------------------------------------------------------------------
def _audio_values(path: str) -> dict:
    try:
        values = audio_write.read_audio_tags(path, [k for k, _label in AUDIO_FIELDS])
    except audio_write.AudioWriteError as e:
        raise MetaWriteError(str(e).replace("an audio file that can be read", "an audio file Dossier can read")) from e
    return {key: AUDIO_SEPARATOR.join(v) for key, v in values.items()}


def _comic_root(path: str) -> tuple:
    """``(member name or "", the parsed ComicInfo root or None)`` of the cbz at ``path``."""
    try:
        member, root, _names = comicinfo_write.read_comicinfo_from_cbz(path)
    except zipfile.BadZipFile as e:
        raise MetaWriteError("not a zip archive (only cbz comics can be changed; convert a cbr to zip first)") from e
    except comicinfo_write.ComicInfoError as e:
        if "too large" in str(e):
            raise MetaWriteError(str(e)) from e
        raise MetaWriteError(f"ComicInfo.xml is not valid XML ({e}); it was left alone") from e
    return member or "", root


def _comic_values(path: str) -> dict:
    _member, root = _comic_root(path)
    return comicinfo_write.comicinfo_values(root, [key for key, _label in COMIC_FIELDS])


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
    touched. A file whose value is already the new one has no change; a file that cannot be changed carries a ``problem``.
    Values are taken as they will read back: without spaces around them and with plain line breaks (XML keeps no other kind), so the
    check after writing never fails on what was only a space (the command line wrote " X", read back "X", and called that a failure)."""
    edits = {k: str(v).replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10)).strip() for k, v in edits.items()}
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
def _old_name(path: str) -> str:
    """Where the old file waits (and goes to the bin from): ``<name>.dossier-old``, as for every other file Dossier replaces."""
    return zipwrite.unique_path(path + ".dossier-old")


def _audio_edit(key: str, value: str) -> list:
    """The values a field's text stands for: a list field's text is split at AUDIO_SEPARATOR (lists in, lists out)."""
    if not value:
        return []
    if key in AUDIO_LIST_FIELDS:
        return [part.strip() for part in value.split(AUDIO_SEPARATOR.strip()) if part.strip()]
    return [value]


def _write_audio(path: str, changes: dict, cancel, trasher) -> None:
    audio_write.write_audio_tags(
        path, {key: _audio_edit(key, value) for key, value in changes.items()}, labels=dict(AUDIO_FIELDS),
        before_swap=_carry_tags, dispose_original=trasher, namer=_old_name, keep_new_if_dispose_fails=True,
        should_cancel=lambda: check(cancel) or False, temp_prefix=".dossier-")


def _carry_tags(src: str, dst: str) -> None:
    """The rating and label Dossier keeps on the file itself belong to the new file too (a copy does not carry them)."""
    try:
        from . import filetags
        filetags.copy_tags(src, dst)
    except Exception:   # noqa: BLE001 -- the metadata edit must not fail because a tag could not follow
        pass


def _write_comic(path: str, changes: dict, cancel, trasher) -> None:
    reason = zipwrite.why_not_editable(path)
    if reason:
        raise zipwrite.ZipWriteError(reason)
    try:
        comicinfo_write.write_comicinfo_into_cbz(
            path, changes, dispose_original=trasher, namer=_old_name, keep_new_if_dispose_fails=True,
            temp_suffix=TEMP_SUFFIX, error_prefix="could not change the comic", should_cancel=lambda: check(cancel) or False)
    except comicinfo_write.ComicInfoError as e:
        raise MetaWriteError(f"the new ComicInfo.xml would not be valid XML or would not say what was asked ({e}); "
                             "the comic was left as it was") from e
    except RewriteError as e:
        raise zipwrite._write_error(e) from e
    except RewriteCancelled as e:
        raise Cancelled() from e


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
        except Cancelled:
            raise
        except Exception as e:   # noqa: BLE001 -- mutagen's own errors, broken XML: this file failed (and is as it was), the rest goes on
            result.failed.append((item.path, f"{type(e).__name__}: {e}"))
        if progress:
            progress(n, len(todo))
    return result
