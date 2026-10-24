"""Writing zip files: pack items into a new zip, change a zip or a zip-based file (cbz, epub, docx...) and convert other
archives to zip. Only zip is ever written (decided with the owner): 7z and RAR stay read only, and a way out of them is
``convert_to_zip``.

Nothing here changes an archive in place. A new file is written beside the old one under a temporary name and put in place
at the end (``rewrite`` through ``Swap``, so the old file goes to the recycle bin only after the new one is in place); a
failure or a cancel leaves the original exactly as it was. Passwords are not written (the standard library cannot).
Everything runs on a thread: the window passes a ``CancelToken`` and a ``progress(done, total)`` in bytes.
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

from . import archives
from .fsretry import replace_with_retry
from .progress import Cancelled, CancelToken, check

ZIP_BASED = (".zip", ".cbz", ".epub", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".jar", ".apk", ".xpi", ".kmz",
             ".vsix", ".nupkg", ".whl", ".xlsm", ".docm", ".pptm", ".dotx", ".xltx", ".potx")
STORE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".mp3",
                    ".m4a", ".flac", ".ogg", ".opus", ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".docx", ".xlsx",
                    ".pptx", ".epub", ".cbz", ".jar")
LEVELS = {"store": None, "fast": 1, "normal": 6, "maximum": 9}
CHUNK = 1 << 20
ZIP64_LIMIT = (1 << 31) - 1
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


def _info(arcname: str, mtime: float, mode: int, is_dir: bool) -> zipfile.ZipInfo:
    try:
        stamp = time.localtime(max(mtime, 315532800))             # a zip cannot hold a date before 1980
        zi = zipfile.ZipInfo(arcname + "/" if is_dir else arcname, stamp[:6])
    except (OverflowError, OSError, ValueError):
        zi = zipfile.ZipInfo(arcname + "/" if is_dir else arcname, (1980, 1, 1, 0, 0, 0))
    zi.external_attr = ((stat.S_IFDIR | 0o755 if is_dir else (mode & 0xFFFF) | stat.S_IFREG) << 16) | (0x10 if is_dir else 0)
    zi.create_system = 3
    return zi


def _set_method(zi: zipfile.ZipInfo, method: tuple) -> None:
    zi.compress_type = method[0]
    try:
        zi._compresslevel = method[1]                               # the documented way to choose it per entry is private
    except AttributeError:
        pass


class _Counter:
    def __init__(self, total: int, progress: Optional[Callable]) -> None:
        self.total, self.done, self.progress = max(total, 1), 0, progress

    def add(self, n: int) -> None:
        self.done += n
        if self.progress is not None:
            self.progress(min(self.done, self.total), self.total)


def _copy_into(zf: zipfile.ZipFile, zi: zipfile.ZipInfo, src, size: int, counter: _Counter, cancel) -> None:
    with zf.open(zi, "w", force_zip64=size > ZIP64_LIMIT) as out:
        while True:
            check(cancel)
            block = src.read(CHUNK)
            if not block:
                break
            out.write(block)
            counter.add(len(block))


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
    counter = _Counter(total, progress)
    part = dest + TEMP_SUFFIX
    try:
        with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
            for arcname, path, is_dir in items:
                check(cancel)
                try:
                    st = os.stat(path)
                    zi = _info(arcname, st.st_mtime, st.st_mode, is_dir)
                    if is_dir:
                        zf.writestr(zi, b"")
                        result.folders += 1
                        continue
                    _set_method(zi, _method(arcname, level, store_compressed))
                    zi.file_size = st.st_size
                    with open(path, "rb") as src:
                        _copy_into(zf, zi, src, st.st_size, counter, cancel)
                    result.files += 1
                    result.bytes_in += st.st_size
                except OSError as e:
                    result.skipped.append((path, e.strerror or str(e)))
        os.replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
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
    recycle bin (``trasher``)."""
    reason = why_not_editable(archive)
    if reason:
        raise ZipWriteError(reason)
    rename = {k.strip("/"): v.strip("/") for k, v in (rename or {}).items()}
    remove = [r.strip("/") for r in remove]
    result = WriteResult(path=archive)
    part = archive + TEMP_SUFFIX
    try:
        with zipfile.ZipFile(archive) as zin:
            infos = zin.infolist()
            added = {name.strip("/"): src for name, src in add}
            plan: list = []
            for zi in infos:
                name = zi.filename.rstrip("/")
                if any(_under(name, r) for r in remove):
                    continue
                for old, new in rename.items():
                    if _under(name, old):
                        name = new + name[len(old):]
                        break
                if name in added:
                    continue                                    # replaced by an added item of the same name
                plan.append((zi, name))
            names = [n for _z, n in plan] + [n for n in added]
            if len(set(n.casefold() for n in names)) != len(names):
                raise ZipWriteError("two entries would get the same name")
            total = sum(zi.file_size for zi, _n in plan if not zi.is_dir())
            for src in added.values():
                if src is not None:
                    total += os.path.getsize(src)
            counter = _Counter(total, progress)
            with zipfile.ZipFile(part, "w", allowZip64=True) as zout:
                zout.comment = zin.comment
                for zi, name in plan:
                    check(cancel)
                    copy = zipfile.ZipInfo(name + "/" if zi.is_dir() else name, zi.date_time)
                    copy.compress_type = zi.compress_type
                    copy.external_attr, copy.create_system, copy.comment, copy.extra = (zi.external_attr, zi.create_system,
                                                                                      zi.comment, b"")
                    copy.flag_bits = zi.flag_bits & 0x800
                    if zi.is_dir():
                        zout.writestr(copy, b"")
                        result.folders += 1
                        continue
                    copy.file_size = zi.file_size
                    with zin.open(zi) as src:
                        _copy_into(zout, copy, src, zi.file_size, counter, cancel)
                    result.files += 1
                for name, src_path in added.items():
                    check(cancel)
                    if src_path is None:
                        zout.writestr(_info(name, time.time(), 0o755, True), b"")
                        result.folders += 1
                        continue
                    st = os.stat(src_path)
                    zi = _info(name, st.st_mtime, st.st_mode, False)
                    _set_method(zi, _method(name, level, True))
                    zi.file_size = st.st_size
                    with open(src_path, "rb") as src:
                        _copy_into(zout, zi, src, st.st_size, counter, cancel)
                    result.files += 1
                    result.bytes_in += st.st_size
        with zipfile.ZipFile(part) as check_zip:                 # the new file must read back before it replaces anything
            if check_zip.testzip() is not None:
                raise ZipWriteError("the new archive did not read back correctly; the original was kept")
        _swap_in(archive, part, trasher)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return result


REPLACE_TRIES = 12                       # a program that has the archive open for a moment (the panel's listing, a virus
REPLACE_WAIT = 0.1                       # scanner, a preview) lets go within a second or two: wait for it, do not give up


def _replace(src: str, dst: str) -> None:
    """``os.replace`` that waits a little when another program has either file open (a sharing violation on Windows)."""
    try:
        replace_with_retry(src, dst, REPLACE_TRIES, REPLACE_WAIT)
    except PermissionError as e:
        raise ZipWriteError(f"the archive is in use by another program ({e.strerror or e}); nothing was changed") from e


def _swap_in(archive: str, part: str, trasher: Optional[Callable]) -> None:
    """Put the new file in the old one's place; the old one is set aside first and sent to the bin once the new one is there."""
    old = unique_path(archive + ".dossier-old")
    _replace(archive, old)
    try:
        _replace(part, archive)
    except BaseException:
        _replace(old, archive)
        raise
    try:
        if trasher is not None:
            trasher(old)
        else:
            os.remove(old)
    except OSError:
        pass                                                      # the old file stays beside the new one, named .dossier-old


swap_in = _swap_in                       # public: other writers (the tags of an mp3, ComicInfo) put their new file in place the same way


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
