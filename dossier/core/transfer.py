"""Copy one file between any two file systems, with progress and cancel.

The data goes to a temporary name beside the target and is renamed into place at the end, so
a cancelled or failed copy never leaves a half-written target and never damages an existing one.
"""
from __future__ import annotations

import errno
import os
import stat
import uuid
from typing import Callable, Optional

from . import fastcopy
from .platform import IS_WINDOWS, has_scheme, longpath
from .progress import CancelToken, ProgressFn, check
from .vfs import FileSystem, NotWritable

PART_SUFFIX = ".dossier-part"
MAX_NAME_WITH_SUFFIX = 240          # a file name may be 255 characters; the temporary name must fit too


def carry_tags(src_fs: FileSystem, src: str, dst_fs: FileSystem, dst: str, lost: Optional[list] = None) -> None:
    """Put the tags of ``src`` (kept on the file itself, see filetags.py) on its copy ``dst``: neither Python's copy nor the
    small-file path carries an NTFS stream. Only between two plain local paths. When the destination cannot hold them its path
    is added to ``lost`` so the window can say so once. Never raises: a copy must not fail because its tags could not follow."""
    if not (_plain_local(src_fs, src) and _plain_local(dst_fs, dst)):
        return
    try:
        from . import filetags
        if filetags.copy_tags(src, dst) == "lost" and lost is not None:
            lost.append(dst)
    except Exception:   # noqa: BLE001 -- see above
        pass


def side_name(fs: FileSystem, dst: str, suffix: str, taken=None) -> str:
    """A name next to ``dst`` for something temporary (the half-written copy, the older file set aside). It is
    ``dst`` plus the suffix, which tells the user what it is; when the name is already near the limit of the file
    system it is a short unique name instead, so a long name does not make the copy fail."""
    if len(fs.basename(dst)) + len(suffix) <= MAX_NAME_WITH_SUFFIX:
        return dst + suffix
    return fs.join(fs.dirname(dst), ".~" + uuid.uuid4().hex[:12] + suffix)


def copy_mode(src: str, dst: str) -> None:
    """Keep the permission bits (the exec bit above all) of a file copied by hand, as the system's own copy does."""
    if IS_WINDOWS:
        return
    try:
        os.chmod(dst, stat.S_IMODE(os.stat(src).st_mode))
    except OSError:
        pass


def move_item(fs: FileSystem, src: str, dst: str, is_dir: bool, cancel: Optional[CancelToken] = None, *,
              progress: Optional[ProgressFn] = None, throttle=None, swap=None, tags_lost: Optional[list] = None,
              check_part: Optional[Callable[[str], None]] = None, flush: bool = False) -> bool:
    """Rename in place; across drives a file is copied, verified by size, then removed. ``swap`` puts the item in
    the place of an existing one without ever being without the old one (see ``Swap``). Returns True when the item
    was renamed (it can be renamed back), False when it had to be copied to another drive and removed.
    Across drives, ``check_part`` reads the new data back before it takes the name (see ``copy_file``), and ``flush``
    pushes the copy to the device before the original is removed, so a pulled stick or a power cut never leaves neither."""
    if swap is not None:
        swap.prepare()
    try:
        fs.rename(src, dst)
    except OSError as e:
        if swap is not None:
            swap.rollback()
        if isinstance(e, FileExistsError) or e.errno != errno.EXDEV:
            raise
        if is_dir:
            raise OSError("this folder is on another volume than its new place (a mount point or a link): copy it and delete "
                          "the original; nothing was changed") from e
        copy_file(fs, src, fs, dst, cancel=cancel, progress=progress, throttle=throttle, overwrite=swap is not None, swap=swap,
                  tags_lost=tags_lost, check_part=check_part)
        if flush:
            flush_file(dst)
        if fs.stat(dst).size != fs.stat(src).size:
            fs.remove(dst)
            raise OSError("the copy does not match the original; the original was kept") from e
        fs.remove(src)
        return False
    except BaseException:
        if swap is not None:
            swap.rollback()
        raise
    if swap is not None:
        swap.commit()
    return True


class Swap:
    """Replace an existing file without a moment where neither exists. ``prepare`` moves the old file aside (same
    folder, so it cannot fail for want of another drive), the caller puts the new one in place, and then either
    ``commit`` sends the old one to the recycle bin or ``rollback`` puts it back. A copy that fails halfway therefore
    leaves the old file exactly where it was. In the bin the old file is called ``<name>.dossier-old``. Where there is
    no bin (``permanent``) the old file is deleted once the new one is in place."""

    SUFFIX = ".dossier-old"

    def __init__(self, fs: FileSystem, dst: str, trasher, permanent: bool = False) -> None:
        self.fs, self.dst, self.trasher = fs, dst, trasher
        self.permanent = permanent                    # no recycle bin there (a network drive): the old file is deleted
        self.backup = ""

    def prepare(self) -> None:
        name = side_name(self.fs, self.dst, self.SUFFIX)
        n = 1
        while True:
            try:
                self.fs.stat(name)
            except FileNotFoundError:
                break
            n += 1
            name = side_name(self.fs, self.dst, f"{self.SUFFIX}{n}")
        self.fs.rename(self.dst, name)
        self.backup = name

    def rollback(self) -> None:
        if self.backup:
            try:
                self.fs.rename(self.backup, self.dst)
            except OSError:
                pass                                  # the old file is still there, under the backup name
            self.backup = ""

    def commit(self) -> None:
        backup, self.backup = self.backup, ""
        if backup:
            try:
                if self.permanent:
                    self.fs.remove(backup)
                else:
                    self.trasher(backup)
            except OSError as e:
                where = "deleted" if self.permanent else "sent to the recycle bin"
                raise OSError(f"replaced, but the older version could not be {where} and was left as "
                              f"{backup}: {e.strerror or e}") from e


def copy_file(
    src_fs: FileSystem,
    src: str,
    dst_fs: FileSystem,
    dst: str,
    *,
    progress: Optional[ProgressFn] = None,
    cancel: Optional[CancelToken] = None,
    overwrite: bool = False,
    chunk_size: int = 1 << 20,
    throttle=None,
    native: bool = True,
    swap=None,
    tags_lost: Optional[list] = None,
    check_part: Optional[Callable[[str], None]] = None,
) -> None:
    """Copy one file through a part file beside the target. ``check_part(part)`` runs on the complete part file before it
    takes the target's name (the read-back of Verify): when it raises, the part is removed and an existing target was
    never touched. A small new local file is the exception: the system copies it straight to its name (``_copy_straight``)."""
    check(cancel)
    if not overwrite:
        try:
            dst_fs.stat(dst)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(dst)
    if throttle is not None:
        chunk_size = min(chunk_size, max(16384, throttle.rate // 4))     # a slow limit still reports and cancels often
    info = src_fs.stat(src)
    total = info.size
    part = side_name(dst_fs, dst, PART_SUFFIX)
    done = 0
    resumable = total >= RESUME_MIN and part == dst + PART_SUFFIX and _plain_local(src_fs, src) and _plain_local(dst_fs, dst)
    if resumable:
        try:
            _copy_resumable(src, part, info, progress, cancel, chunk_size, throttle)
        except OSError:
            raise                                      # the part and its note stay: the next try goes on from there
        except BaseException:
            _drop_part(part)                           # a cancel (or a bug) removes it, as for any copy
            raise
        try:
            _check_whole(os.path.getsize(longpath(part)), total, src)
            copy_mode(src, part)
            if check_part is not None:
                check_part(part)
            _finish(dst_fs, part, dst, info, overwrite, cancel, swap)
        except BaseException:
            _drop_part(part)
            raise
        _drop_note(part)
        carry_tags(src_fs, src, dst_fs, dst, tags_lost)
        return
    try:
        if throttle is None and src_fs is dst_fs and getattr(dst_fs, "copy_on_server", None) and dst_fs.copy_on_server(src, part):
            _check_whole(dst_fs.stat(part).size, total, src)           # copied on the server itself (it allows commands): no bytes came here
            if check_part is not None:
                check_part(part)
            _finish(dst_fs, part, dst, info, overwrite, cancel, swap)
            if progress:
                progress(total, total)
            return
        if (native and throttle is None and not overwrite and swap is None and total < fastcopy.FAST_MIN
                and _system_can_copy(src_fs, src) and _system_can_copy(dst_fs, dst)):
            if _copy_straight(src_fs, src, dst_fs, dst, info, progress, cancel, check_part):
                carry_tags(src_fs, src, dst_fs, dst, tags_lost)
                return
        if native and throttle is None and total >= fastcopy.FAST_MIN and _system_can_copy(src_fs, src) and _system_can_copy(dst_fs, dst):
            if fastcopy.fast_copy(src, part, total, progress, cancel):       # the system's own copy, in the kernel
                _check_whole(dst_fs.stat(part).size, total, src)
                if check_part is not None:
                    check_part(part)
                _finish(dst_fs, part, dst, info, overwrite, cancel, swap)
                carry_tags(src_fs, src, dst_fs, dst, tags_lost)
                return
        with src_fs.open_read(src) as r, dst_fs.open_write(part) as w:
            while True:
                check(cancel)
                chunk = r.read(chunk_size)
                if not chunk:
                    break
                w.write(chunk)
                done += len(chunk)
                if throttle is not None:
                    throttle.wait(len(chunk), cancel)
                if progress:
                    progress(done, total)
        if done == 0 and progress:
            progress(0, total)
        _check_whole(done, total, src)
        if _plain_local(src_fs, src) and _plain_local(dst_fs, dst):
            copy_mode(src, part)
        if check_part is not None:
            check_part(part)
        _finish(dst_fs, part, dst, info, overwrite, cancel, swap)
        carry_tags(src_fs, src, dst_fs, dst, tags_lost)
    except BaseException:
        try:
            dst_fs.remove(part)
        except OSError:
            pass
        raise


RESUME_MIN = 64 * 1024 * 1024       # a file at least this big continues where an interrupted copy stopped
RESUME_BACK = 4 * 1024 * 1024       # what was written last may not have reached the target: go back this far and write it again
RESUME_CHECK = 1024 * 1024          # and compare this much before that point with the original first
NOTE_SUFFIX = ".json"


def _note_path(part: str) -> str:
    return part + NOTE_SUFFIX


def _drop_note(part: str) -> None:
    try:
        os.remove(longpath(_note_path(part)))
    except OSError:
        pass


def _drop_part(part: str) -> None:
    for p in (part, _note_path(part)):
        try:
            os.remove(longpath(p))
        except OSError:
            pass


def _resume_from(src: str, part: str, info) -> int:
    """Where a copy into ``part`` can go on: 0 to start over. The note beside the part (written when the copy began, while the
    target could still be reached) must name the same original, with the same size and time; the part is cut back a little
    (``RESUME_BACK``), and the stretch before that point must match the original, or nothing of it is trusted."""
    import json
    try:
        with open(longpath(_note_path(part)), encoding="utf-8") as f:
            note = json.load(f)
        have = os.path.getsize(longpath(part))
    except (OSError, ValueError):
        return 0
    if not isinstance(note, dict) or note.get("source") != os.path.abspath(src) or note.get("size") != info.size \
            or abs(float(note.get("mtime", 0)) - info.mtime) > 1:
        return 0
    good = min(have, info.size) - RESUME_BACK
    if good <= RESUME_CHECK:
        return 0
    try:
        with open(longpath(src), "rb") as a, open(longpath(part), "rb") as b:
            a.seek(good - RESUME_CHECK)
            b.seek(good - RESUME_CHECK)
            if a.read(RESUME_CHECK) != b.read(RESUME_CHECK):
                return 0
    except OSError:
        return 0
    return good


def _copy_resumable(src: str, part: str, info, progress, cancel, chunk_size: int, throttle) -> None:
    """Copy a big local file into ``part``, going on from an earlier interrupted copy when its part is still there and sound.
    The system's own copy cannot continue a part, so this is the plain loop; it is not slower over a network."""
    import json
    start = _resume_from(src, part, info)
    if start == 0:
        try:
            with open(longpath(_note_path(part)), "w", encoding="utf-8") as f:
                json.dump({"source": os.path.abspath(src), "size": info.size, "mtime": info.mtime}, f)
        except OSError:
            pass                                       # no note: this copy simply cannot be continued later
    done = start
    with open(longpath(src), "rb") as r, open(longpath(part), "r+b" if start else "wb") as w:
        if start:
            r.seek(start)
            w.seek(start)
            w.truncate()
            if progress:
                progress(done, info.size)
        while True:
            check(cancel)
            chunk = r.read(chunk_size)
            if not chunk:
                break
            w.write(chunk)
            done += len(chunk)
            if throttle is not None:
                throttle.wait(len(chunk), cancel)
            if progress:
                progress(done, info.size)


def resumed_part(dst: str) -> bool:
    """Whether a copy to ``dst`` left a part that a next try can continue (for tests and the Health window)."""
    return os.path.exists(longpath(dst + PART_SUFFIX)) and os.path.exists(longpath(_note_path(dst + PART_SUFFIX)))


def _copy_straight(src_fs: FileSystem, src: str, dst_fs: FileSystem, dst: str, info, progress, cancel, check_part) -> bool:
    """A small new file, copied by the system straight to its name (decided with the owner 2026-11-06, after timing against
    robocopy): the part file and its rename cost about a quarter of the time of a small file. Nothing is replaced: the system
    refuses a name that was taken meanwhile. A failure, a cancel or a Verify that fails removes the file it made, so what is
    left is whole or not there; only a power cut in the middle can leave a short file (under 8 MB) under its name.
    False when the system cannot copy this pair (nothing was written): the caller copies the usual way."""
    total = info.size
    try:
        if not fastcopy.fast_copy(src, dst, total, progress, cancel, fail_if_exists=True):
            return False
    except FileExistsError:
        raise                                          # not ours: never removed
    except BaseException:
        _drop_partial(dst)
        raise
    try:
        _check_whole(os.path.getsize(longpath(dst)), total, src)
        if not IS_WINDOWS:
            dst_fs.set_mtime(dst, info.mtime)          # Windows' copy keeps the time (and the attributes and streams) itself
        if check_part is not None:
            check_part(dst)
    except BaseException:
        _drop_partial(dst)
        raise
    if progress:
        progress(total, total)
    return True


def _drop_partial(path: str) -> None:
    try:
        os.remove(longpath(path))
    except OSError:
        pass


def _system_can_copy(fs: FileSystem, path: str) -> bool:
    """Whether the system's own copy may stand in for ``fs``: a plain local path, and a file system that reads and writes files the
    plain local way (one that changes how, a wrapper or a test's, keeps its own calls)."""
    from .vfs import LocalFileSystem
    if not _plain_local(fs, path):
        return False
    real = fs.fs_for(path) if hasattr(fs, "fs_for") else fs          # the window's router hands a local path to its local disk
    return type(real).open_read is LocalFileSystem.open_read and type(real).open_write is LocalFileSystem.open_write


def _plain_local(fs: FileSystem, path: str) -> bool:
    """A path on the real disk, which the operating system can copy by itself."""
    return fs.scheme == "" and not has_scheme(path) and fs.writable


def _check_whole(written: int, expected: int, src: str) -> None:
    """A source that got shorter while it was copied (a file being rewritten, a truncated log) gives a short copy:
    that is an error, not a success. A source that grew is copied as far as it was read."""
    if written < expected:
        raise OSError(f"the file changed while it was copied ({expected:,} bytes when it was listed, {written:,} "
                      f"read): {os.path.basename(src)}")


def _finish(dst_fs: FileSystem, part: str, dst: str, info, overwrite: bool, cancel, swap=None) -> None:
    check(cancel)
    try:
        dst_fs.set_mtime(part, info.mtime)
    except NotWritable:
        pass
    if swap is not None:
        swap.prepare()                                # the old target moves aside only now, with the new data complete
    try:
        dst_fs.rename(part, dst, overwrite=overwrite)
    except BaseException:
        if swap is not None:
            swap.rollback()
        raise
    if swap is not None:
        swap.commit()


class VerifyFailed(OSError):
    """The copy does not match the original."""


def _read_exact(stream, n: int) -> bytes:
    """``n`` bytes unless the stream ends first (a stream may hand out less than asked)."""
    parts, have = [], 0
    while have < n:
        chunk = stream.read(n - have)
        if not chunk:
            break
        parts.append(chunk)
        have += len(chunk)
    return parts[0] if len(parts) == 1 else b"".join(parts)


def verify_copy(src_fs: FileSystem, src: str, dst_fs: FileSystem, dst: str, *,
                progress=None, cancel: Optional[CancelToken] = None, chunk_size: int = 1 << 20) -> None:
    """Read both files again and compare them byte for byte. ``progress(bytes_checked)`` is called per chunk.
    Raises ``VerifyFailed`` at the first difference. A copy that was just written may be answered from the
    system's file cache, so this proves the data that was written, and that it can be read back, but it does
    not by itself prove the device holds it: ``flush_file`` is what pushes the data out to the device."""
    done = 0
    with src_fs.open_read(src) as a, dst_fs.open_read(dst) as b:
        while True:
            check(cancel)
            x = _read_exact(a, chunk_size)
            y = _read_exact(b, chunk_size)
            if x != y:
                at = next((i for i in range(min(len(x), len(y))) if x[i] != y[i]), min(len(x), len(y)))
                raise VerifyFailed(f"the copy differs from the original at byte {done + at:,}")
            done += len(x)
            if progress:
                progress(done)
            if len(x) < chunk_size:
                return


def flush_file(path: str) -> None:
    """Ask the operating system to write a file's data to the device now (``fsync``). Files that cannot be
    opened for it (read-only, special) are skipped: there is nothing of ours left in the cache to push."""
    from .platform import longpath
    try:
        fd = os.open(longpath(path), os.O_RDWR | getattr(os, "O_BINARY", 0))
    except (PermissionError, IsADirectoryError):
        return
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in (errno.EINVAL, errno.EBADF, errno.ENOTSUP):
            raise
    finally:
        os.close(fd)
