"""Writing zip files: pack items into a new zip, change a zip or a zip-based file (cbz, epub, docx...) and convert other
archives to zip. Only zip is ever written (decided with the owner): 7z and RAR stay read only, and a way out of them is
``convert_to_zip``.

Nothing here changes an archive in place. A new file is written beside the old one under a temporary name and put in place
at the end (``rewrite`` through ``Swap``, so the old file goes to the recycle bin only after the new one is in place); a
failure or a cancel leaves the original exactly as it was. Passwords are not written (the standard library cannot).
Everything runs on a thread: the window passes a ``CancelToken`` and a ``progress(done, total)`` in bytes.

The writing itself is redactor_common's ``core/zip_rewrite`` (since 2026-11-04 the one zip writer Dossier, cbzredactor and the
other Redactor apps share): entries streamed in chunks, every entry's metadata and extra fields kept, legacy entry names kept byte
for byte, every CRC checked before the swap. ``tests/test_shared_writers.py`` fails if a zip is written anywhere else.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from redactor_common.core.zip_rewrite import (Action, NewEntry, RewriteCancelled, RewriteError, RewritePlan, rewrite_archive,
                                              write_new_archive, zip_date_time)

from . import archives
from .progress import Cancelled, CancelToken, check

ZIP_BASED = (".zip", ".cbz", ".epub", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".jar", ".apk", ".xpi", ".kmz",
             ".vsix", ".nupkg", ".whl", ".xlsm", ".docm", ".pptm", ".dotx", ".xltx", ".potx")
STORE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".mp3",
                    ".m4a", ".flac", ".ogg", ".opus", ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".docx", ".xlsx",
                    ".pptx", ".epub", ".cbz", ".jar")
LEVELS = {"store": None, "fast": 1, "normal": 6, "maximum": 9}
MAX_MEMBERS = 1_000_000
TEMP_SUFFIX = ".dossier-part"


class ZipWriteError(OSError):
    """A zip could not be written or changed; the original is untouched."""


@dataclass
class WriteResult:
    path: str = ""
    files: int = 0
    folders: int = 0
    bytes_in: int = 0
    skipped: list = field(default_factory=list)      # (path, why): links, unreadable files


def is_zip_based(path: str) -> bool:
    return path.lower().endswith(ZIP_BASED)


def why_not_editable(path: str) -> str:
    """Empty when ``path`` is a local zip or zip-based file that can be rewritten, otherwise the reason."""
    if not os.path.isfile(path):
        return "this is not a file on a drive of this computer"
    if not is_zip_based(path):
        return "only zip and zip-based files (cbz, epub, docx and the like) can be changed; other archives can be converted to zip"
    if not zipfile.is_zipfile(path):
        return "this file is not a readable zip"
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS:
                return "this archive has too many entries"
            if any(i.flag_bits & 0x1 for i in infos):
                return "this archive has encrypted entries, which cannot be rewritten"
    except (zipfile.BadZipFile, OSError) as e:
        return f"this file is not a readable zip ({e})"
    return ""


def unique_path(path: str) -> str:
    """``path``, or ``name (2).ext``, ``name (3).ext``... when it is taken."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _method(name: str, level: str, store_compressed: bool) -> tuple:
    """(compress_type, compresslevel) for a file called ``name``."""
    if LEVELS.get(level, 6) is None or (store_compressed and name.lower().endswith(STORE_EXTENSIONS)):
        return zipfile.ZIP_STORED, None
    return zipfile.ZIP_DEFLATED, LEVELS.get(level, 6)


def _attrs(mode: int, is_dir: bool) -> int:
    """The external attributes of an entry for a file or folder with this ``st_mode`` (Unix mode, plus the DOS folder bit)."""
    return ((stat.S_IFDIR | 0o755 if is_dir else (mode & 0xFFFF) | stat.S_IFREG) << 16) | (0x10 if is_dir else 0)


def _new_entry(arcname: str, path: Optional[str], mtime: float, mode: int, is_dir: bool,
               method: tuple = (zipfile.ZIP_STORED, None)) -> NewEntry:
    """The entry for a file (streamed from ``path``) or a folder, with its own date and attributes, made on Unix (3)."""
    return NewEntry(arcname + "/" if is_dir else arcname, date_time=zip_date_time(mtime), source_path=None if is_dir else path,
                    compress_type=method[0], compresslevel=method[1], external_attr=_attrs(mode, is_dir), create_system=3)


def _should_cancel(cancel: Optional[CancelToken]) -> Callable[[], bool]:
    """The shared writer's cancel poll: ``check`` raises ``Cancelled`` (and waits while paused)."""
    return lambda: check(cancel) or False


# pack ------------------------------------------------------------------------------------------------------------
def _walk(source: str, arc_top: str, skipped: list, cancel):
    """(arcname, path, is_dir) for the source and everything below it; links are skipped (never followed)."""
    st = os.lstat(source)
    if stat.S_ISLNK(st.st_mode):
        skipped.append((source, "a link"))
        return
    if not stat.S_ISDIR(st.st_mode):
        yield arc_top, source, False
        return
    yield arc_top, source, True
    try:
        names = sorted(os.listdir(source), key=str.casefold)
    except OSError as e:
        skipped.append((source, e.strerror or str(e)))
        return
    for name in names:
        check(cancel)
        yield from _walk(os.path.join(source, name), arc_top + "/" + name, skipped, cancel)


def pack(sources: Sequence[str], dest: str, level: str = "normal", store_compressed: bool = True,
         cancel: Optional[CancelToken] = None, progress: Optional[Callable] = None) -> WriteResult:
    """Write ``sources`` (files and folders, local) into the new zip ``dest``. Each source becomes a top-level entry under its
    own name. ``dest`` must not exist. The zip is written under a temporary name and moved into place at the end."""
    if os.path.exists(dest):
        raise FileExistsError(dest)
    result = WriteResult(path=dest)
    items: list = []
    for source in sources:
        items.extend(_walk(source, os.path.basename(source.rstrip("/" + chr(92))), result.skipped, cancel))
    total = 0
    for _a, p, is_dir in items:
        if not is_dir:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass

    def entries():
        for arcname, path, is_dir in items:
            check(cancel)
            try:
                st = os.stat(path)
            except OSError as e:
                result.skipped.append((path, e.strerror or str(e)))
                continue
            yield _new_entry(arcname, path, st.st_mtime, st.st_mode, is_dir, _method(arcname, level, store_compressed))

    part = dest + TEMP_SUFFIX
    try:
        written = write_new_archive(part, entries(), total_bytes=total, byte_progress=progress,
                                    should_cancel=_should_cancel(cancel), on_unreadable=lambda _entry, _error: None)
        os.replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    result.files, result.folders, result.bytes_in = written.files, written.folders, written.bytes_out
    result.skipped.extend(written.skipped)
    return result


# change a zip ----------------------------------------------------------------------------------------------------
def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + "/")


def rewrite(archive: str, *, remove: Sequence[str] = (), rename: Optional[dict] = None,
            add: Sequence[tuple] = (), level: str = "normal", cancel: Optional[CancelToken] = None,
            progress: Optional[Callable] = None, trasher: Optional[Callable] = None) -> WriteResult:
    """Change a zip or zip-based file: take members (``remove``: names, a folder name takes everything below it) out, rename
    members or folders (``rename``: old -> new), and add files (``add``: (name inside, local path) pairs; a path of ``None``
    makes an empty folder). The members that stay are copied with their own method, date and attributes and in their own order,
    so an epub's ``mimetype`` stays first and stored. The new zip is swapped in at the end and the old one goes to the
    recycle bin (``trasher``); when the bin refuses it, the new zip stays and the old one waits beside it as ``.dossier-old``."""
    reason = why_not_editable(archive)
    if reason:
        raise ZipWriteError(reason)
    rename = {k.strip("/"): v.strip("/") for k, v in (rename or {}).items()}
    remove = [r.strip("/") for r in remove]
    added = {name.strip("/"): src for name, src in add}

    def new_name(name: str) -> Optional[str]:
        """Where the member called ``name`` (no trailing slash) goes: its new name, or None when it is taken out."""
        if any(_under(name, r) for r in remove):
            return None
        for old, new in rename.items():
            if _under(name, old):
                name = new + name[len(old):]
                break
        return None if name in added else name                   # replaced by an added item of the same name

    with zipfile.ZipFile(archive) as zin:
        kept = [n for n in (new_name(zi.filename.rstrip("/")) for zi in zin.infolist()) if n is not None]
    names = kept + list(added)
    if len(set(names)) != len(names):                            # names differing only in case are allowed: such cbz files exist
        raise ZipWriteError("two entries would get the same name")

    def decide(entry, _read):
        name = new_name(entry.name.rstrip("/"))
        if name is None:
            return Action(drop=True)
        target = name + "/" if entry.is_dir else name
        return Action(rename=target) if target != entry.name else None

    after: list = []
    bytes_in = 0
    for name, src_path in added.items():
        if src_path is None:
            after.append(_new_entry(name, None, time.time(), 0o755, True))
            continue
        st = os.stat(src_path)
        bytes_in += st.st_size
        after.append(_new_entry(name, src_path, st.st_mtime, st.st_mode, False, _method(name, level, True)))
    try:
        done = rewrite_archive(archive, archive, RewritePlan(decide=decide, after=after), dispose_original=trasher,
                               temp_suffix=TEMP_SUFFIX, error_prefix="could not change the archive", byte_progress=progress,
                               should_cancel=_should_cancel(cancel), namer=_old_name, keep_new_if_dispose_fails=True)
    except RewriteError as e:
        raise _write_error(e) from e
    except RewriteCancelled as e:
        raise Cancelled() from e
    return WriteResult(path=archive, files=done.files, folders=done.folders, bytes_in=bytes_in)


def _old_name(archive: str) -> str:
    """Where the old archive waits (and goes to the bin from): ``<name>.dossier-old``."""
    return unique_path(archive + ".dossier-old")


def _write_error(e: RewriteError) -> ZipWriteError:
    """The shared writer's error in Dossier's words; a file another program holds open says so."""
    cause = e.__cause__
    if isinstance(cause, PermissionError) or (isinstance(cause, OSError) and getattr(cause, "winerror", None) in (32, 33)):
        return ZipWriteError(f"the archive is in use by another program ({cause.strerror or cause}); nothing was changed")
    return ZipWriteError(f"{e.detail}; the original was kept")


# convert ---------------------------------------------------------------------------------------------------------
def _extract_all(archive: str, folder: str, cancel) -> None:
    """Unpack the whole archive into ``folder`` with the reader that can open it (one call, not one per member)."""
    check(cancel)
    backend = archives.backend_for(archive)
    if backend is None:
        raise archives.ArchiveError(archives.missing_reader(archive) or "no reader can open this archive")
    if isinstance(backend, archives.SevenZipBackend):
        import py7zr
        try:
            with py7zr.SevenZipFile(archive) as z:
                z.extractall(path=folder)
        except py7zr.exceptions.PasswordRequired as e:
            raise archives.ArchiveError("this archive is encrypted") from e
        except (py7zr.exceptions.ArchiveError, OSError, ValueError) as e:
            raise archives.ArchiveError(f"could not unpack the archive: {e}") from e
    elif isinstance(backend, archives.ExternalBackend):
        done = subprocess.run([backend.exe, "x", "-y", "-bso0", "-bsp0", "-sccUTF-8", f"-o{folder}", "--", archive],
                              capture_output=True, **archives._quiet())
        if done.returncode not in (0, 1):
            tail = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise archives.ArchiveError("7-Zip could not unpack the archive" + (": " + tail[-1] if tail else ""))
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
    check(cancel)


def convert_to_zip(archive: str, dest: Optional[str] = None, level: str = "normal", cancel: Optional[CancelToken] = None,
                   progress: Optional[Callable] = None) -> WriteResult:
    """Write the contents of a 7z, RAR, tar or any other archive a reader can open as a new zip beside it (``dest`` defaults to
    ``<name>.zip``, made unique). The original is not touched."""
    kind = archives.kind_of(archive)
    if kind == "zip":
        raise ZipWriteError("this is already a zip")
    if not kind:
        raise ZipWriteError("this file is not an archive Dossier can read")
    target = dest or unique_path(os.path.splitext(archive)[0] + ".zip")
    work = tempfile.mkdtemp(prefix="dossier-convert-")
    try:
        _extract_all(archive, work, cancel)
        children = [os.path.join(work, n) for n in sorted(os.listdir(work), key=str.casefold)]
        if not children:
            raise ZipWriteError("the archive is empty")
        result = pack(children, target, level=level, cancel=cancel, progress=progress)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result
