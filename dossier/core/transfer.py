"""Copy one file between any two file systems, with progress and cancel.

The data goes to a temporary name beside the target and is renamed into place at the end, so
a cancelled or failed copy never leaves a half-written target and never damages an existing one.
"""
from __future__ import annotations

import errno
import os
import stat
import uuid
from typing import Optional

from . import fastcopy
from .platform import has_scheme
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
    if os.name != "posix":
        return
    try:
        os.chmod(dst, stat.S_IMODE(os.stat(src).st_mode))
    except OSError:
        pass


def move_item(fs: FileSystem, src: str, dst: str, is_dir: bool, cancel: Optional[CancelToken] = None, *,
              progress: Optional[ProgressFn] = None, throttle=None, swap=None, tags_lost: Optional[list] = None) -> bool:
    """Rename in place; across drives a file is copied, verified by size, then removed. ``swap`` puts the item in
    the place of an existing one without ever being without the old one (see ``Swap``). Returns True when the item
    was renamed (it can be renamed back), False when it had to be copied to another drive and removed."""
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
                  tags_lost=tags_lost)
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
) -> None:
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
    try:
        if native and throttle is None and total >= fastcopy.FAST_MIN and _plain_local(src_fs, src) and _plain_local(dst_fs, dst):
            if fastcopy.fast_copy(src, part, total, progress, cancel):       # the system's own copy, in the kernel
                _check_whole(dst_fs.stat(part).size, total, src)
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
        _finish(dst_fs, part, dst, info, overwrite, cancel, swap)
        carry_tags(src_fs, src, dst_fs, dst, tags_lost)
    except BaseException:
        try:
            dst_fs.remove(part)
        except OSError:
            pass
        raise


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
