"""What the Properties dialog shows, gathered without Qt: the facts of the file system and, for known types, the
metadata inside the file.

Everything here touches the disk, so the window calls ``gather`` on a thread. Nothing is ever written: the metadata
readers are the read-only ones of redactor_common (docs/metadata-plan.md, step 1).
"""
from __future__ import annotations

import os
import stat as stat_module
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .foldersize import folder_sizes, tree_size
from .platform import has_scheme
from .progress import CancelToken
from .sizefmt import human_size

AUDIO = (".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".mp4a", ".aac", ".wav", ".wma", ".aiff", ".aif", ".ape",
         ".wv", ".mpc")
COMIC = (".cbz",)
VIDEO = (".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts", ".flv", ".ogv", ".3gp")
WIN_ATTRIBUTES = ((0x1, "read-only"), (0x2, "hidden"), (0x4, "system"), (0x20, "archive"), (0x800, "compressed"),
                  (0x4000, "encrypted"), (0x400, "link or junction"))


@dataclass(frozen=True)
class Fact:
    label: str
    value: str


@dataclass
class Gathered:
    title: str
    facts: list = field(default_factory=list)       # General tab
    meta: Optional[object] = None                   # a redactor_common MetaResult, or None for a type without a reader
    meta_kind: str = ""                             # audio | comic | video
    paths: list = field(default_factory=list)       # the items these facts are about
    tags: dict = field(default_factory=dict)        # path -> Tags (empty when the items cannot hold tags)
    tags_reason: str = ""                           # why there is no Tags tab, or why it is read only
    tags_can_write: bool = False
    edit_kind: str = ""                             # "audio" or "comic" when the files' own tags can be edited here (all of one kind)
    edit_values: dict = field(default_factory=dict)   # field key -> the value every item has, or None where they differ
    edit_paths: list = field(default_factory=list)  # the items an edit would be written to
    edit_problems: dict = field(default_factory=dict)  # path -> why it cannot be read or changed (the rest can)
    edit_reason: str = ""                           # why nothing can be edited, when that is so


def kind_of(path: str) -> str:
    """Which metadata reader a file name calls for, or an empty string."""
    ext = os.path.splitext(path)[1].lower()
    return "audio" if ext in AUDIO else "comic" if ext in COMIC else "video" if ext in VIDEO else ""


def read_metadata(path: str, kind: str):
    """The read-only metadata of the file at ``path`` (a redactor_common MetaResult). Never raises."""
    from redactor_common.core.meta_fields import MetaResult
    try:
        if kind == "audio":
            from redactor_common.core.meta_audio import read_audio
            return read_audio(path)
        if kind == "comic":
            from redactor_common.core.meta_comic import read_comic
            return read_comic(path)
        if kind == "video":
            from redactor_common.core.meta_video import read_video
            return read_video(path)
    except ImportError as e:
        return MetaResult(kind, error=f"the reader is not installed ({e})")
    return MetaResult(kind, error="no reader for this type")


def _when(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _size_line(n: int) -> str:
    return f"{human_size(n, long=True)}  ({n:,} bytes)" if n >= 1024 else f"{n:,} bytes"


def _attributes(st) -> str:
    bits = getattr(st, "st_file_attributes", None)
    if bits is None:
        return stat_module.filemode(st.st_mode)
    return ", ".join(name for flag, name in WIN_ATTRIBUTES if bits & flag) or "none"


def one_item(fs, path: str, cancel: Optional[CancelToken] = None) -> Gathered:
    entry = fs.stat(path)
    name = fs.basename(path) or path
    out = Gathered(title=f"Properties of {name}")
    f = out.facts
    f.append(Fact("Name", name))
    f.append(Fact("Location", fs.dirname(path) or ""))
    ext = os.path.splitext(name)[1]
    f.append(Fact("Type", "Folder" if entry.is_dir else (f"{ext[1:].upper()} file" if ext else "File")))
    local = not has_scheme(path)
    st = None
    if local:
        try:
            st = os.lstat(path)
        except OSError:
            st = None
    if entry.is_dir:
        total = tree_size(fs, path, cancel)
        f.append(Fact("Size", f"{_size_line(total.size)} in {total.files:,} files and {total.folders:,} folders"
                      + (f"; {total.unreadable} folder(s) could not be read" if total.unreadable else "")))
    else:
        f.append(Fact("Size", _size_line(entry.size)))
    if st is not None:
        f.append(Fact("Modified", _when(st.st_mtime)))
        f.append(Fact("Created" if sys.platform == "win32" else "Status changed", _when(st.st_ctime)))
        f.append(Fact("Last opened", _when(st.st_atime)))
        f.append(Fact("Attributes", _attributes(st)))
        if stat_module.S_ISLNK(st.st_mode):
            try:
                f.append(Fact("Link to", os.readlink(path)))
            except OSError:
                pass
    elif entry.mtime:
        f.append(Fact("Modified", _when(entry.mtime)))
    if not entry.is_dir and local:
        kind = kind_of(path)
        if kind:
            out.meta_kind = kind
            out.meta = read_metadata(path, kind)
    return out


def many_items(fs, paths: list, cancel: Optional[CancelToken] = None) -> Gathered:
    """Totals for a group of items: files by their size, folders by the size of everything below them."""
    entries = []
    for p in paths:
        try:
            entries.append(fs.stat(p))
        except OSError:
            continue
    files = [e for e in entries if not e.is_dir]
    folders = [e for e in entries if e.is_dir]
    total = sum(e.size for e in files)
    inner_files = 0
    if folders:
        results = folder_sizes(fs, [e.path for e in folders], cancel)
        total += sum(r.size for r in results.values())
        inner_files = sum(r.files for r in results.values())
    out = Gathered(title=f"Properties of {len(entries)} items")
    out.facts = [Fact("Items", f"{len(entries):,}: {len(files):,} files, {len(folders):,} folders"),
                 Fact("Total size", _size_line(total)),
                 Fact("Files inside the folders", f"{inner_files:,}" if folders else "")]
    out.facts = [x for x in out.facts if x.value]
    return out


MAX_TAGGED = 2000


def _read_tags(out: Gathered, paths: list) -> None:
    """Fill in the tags of local items: each one's record, and whether every item's drive can hold tags."""
    from . import filetags
    if any(has_scheme(p) for p in paths):
        out.tags_reason = "Tags are kept on files and folders on a drive of this computer, not inside archives or lists."
        return
    if filetags.default_backend() is None:
        out.tags_reason = "This system has no place to keep tags."
        return
    if len(paths) > MAX_TAGGED:
        out.tags_reason = f"Too many items at once for tags ({len(paths):,}); select fewer than {MAX_TAGGED:,}."
        return
    out.paths = list(paths)
    cannot = [p for p in paths if not filetags.can_hold_tags(p)]
    out.tags = {p: filetags.read_tags(p) for p in paths}
    out.tags_can_write = not cannot
    if cannot:
        out.tags_reason = ("This drive cannot store tags (FAT, exFAT and most memory sticks have no place for them)."
                           if len(paths) == 1 else f"{len(cannot)} of these items are on a drive that cannot store tags.")


MAX_EDITED = 2000


def _read_edit(out: Gathered, paths: list) -> None:
    """Fill in what the editable Metadata tab needs: for a group of files of one kind whose tags Dossier can write (mp3, flac, ogg, opus, m4a;
    cbz), the value each field has in common and why a file cannot be changed."""
    from . import metawrite
    if any(has_scheme(p) for p in paths) or len(paths) > MAX_EDITED or not paths:
        return
    kinds = {metawrite.kind_of(p) for p in paths}
    if len(kinds) != 1 or "" in kinds:
        return
    kind, values, problems = metawrite.common_values(paths)
    for p in paths:
        why = metawrite.why_not_writable(p)
        if why:
            problems.setdefault(p, why)
    unusable = [p for p in paths if p in problems]
    out.edit_kind, out.edit_values, out.edit_paths, out.edit_problems = kind, values, [p for p in paths if p not in problems], problems
    if len(unusable) == len(paths):
        out.edit_reason = next(iter(problems.values()))
        out.edit_values = {}


def gather(fs, paths: list, cancel: Optional[CancelToken] = None) -> Gathered:
    out = one_item(fs, paths[0], cancel) if len(paths) == 1 else many_items(fs, paths, cancel)
    _read_tags(out, paths)
    _read_edit(out, paths)
    return out
