"""Copy one file between any two file systems, with progress and cancel.

The data goes to a temporary name beside the target and is renamed into place at the end, so
a cancelled or failed copy never leaves a half-written target and never damages an existing one.
"""
from __future__ import annotations

import errno
import os
from typing import Optional

from . import fastcopy
from .platform import has_scheme
from .progress import CancelToken, ProgressFn, check
from .vfs import FileSystem, NotWritable

PART_SUFFIX = ".dossier-part"


def move_item(fs: FileSystem, src: str, dst: str, is_dir: bool, cancel: Optional[CancelToken] = None, *,
              progress: Optional[ProgressFn] = None, throttle=None) -> None:
    """Rename in place; across drives a file is copied, verified by size, then removed."""
    try:
        fs.rename(src, dst)
    except OSError as e:
        if isinstance(e, FileExistsError) or e.errno != errno.EXDEV:
            raise
        if is_dir:
            raise OSError("moving a folder to another drive is not supported yet; nothing was changed") from e
        copy_file(fs, src, fs, dst, cancel=cancel, progress=progress, throttle=throttle)
        if fs.stat(dst).size != fs.stat(src).size:
            fs.remove(dst)
            raise OSError("the copy does not match the original; the original was kept") from e
        fs.remove(src)


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
    part = dst + PART_SUFFIX
    done = 0
    try:
        if native and throttle is None and total >= fastcopy.FAST_MIN and _plain_local(src_fs, src) and _plain_local(dst_fs, dst):
            if fastcopy.fast_copy(src, part, total, progress, cancel):       # the system's own copy, in the kernel
                _finish(dst_fs, part, dst, info, overwrite, cancel)
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
        _finish(dst_fs, part, dst, info, overwrite, cancel)
    except BaseException:
        try:
            dst_fs.remove(part)
        except OSError:
            pass
        raise


def _plain_local(fs: FileSystem, path: str) -> bool:
    """A path on the real disk, which the operating system can copy by itself."""
    return fs.scheme == "" and not has_scheme(path) and fs.writable


def _finish(dst_fs: FileSystem, part: str, dst: str, info, overwrite: bool, cancel) -> None:
    check(cancel)
    try:
        dst_fs.set_mtime(part, info.mtime)
    except NotWritable:
        pass
    dst_fs.rename(part, dst, overwrite=overwrite)


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
