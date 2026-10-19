"""Copy one file between any two file systems, with progress and cancel.

The data goes to a temporary name beside the target and is renamed into place at the end, so
a cancelled or failed copy never leaves a half-written target and never damages an existing one.
"""
from __future__ import annotations

import errno
from typing import Optional

from .progress import CancelToken, ProgressFn, check
from .vfs import FileSystem, NotWritable

PART_SUFFIX = ".dossier-part"


def move_item(fs: FileSystem, src: str, dst: str, is_dir: bool, cancel: Optional[CancelToken] = None) -> None:
    """Rename in place; across drives a file is copied, verified by size, then removed."""
    try:
        fs.rename(src, dst)
    except OSError as e:
        if isinstance(e, FileExistsError) or e.errno != errno.EXDEV:
            raise
        if is_dir:
            raise OSError("moving a folder to another drive is not supported yet; nothing was changed") from e
        copy_file(fs, src, fs, dst, cancel=cancel)
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
) -> None:
    check(cancel)
    if not overwrite:
        try:
            dst_fs.stat(dst)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(dst)
    info = src_fs.stat(src)
    total = info.size
    part = dst + PART_SUFFIX
    done = 0
    try:
        with src_fs.open_read(src) as r, dst_fs.open_write(part) as w:
            while True:
                check(cancel)
                chunk = r.read(chunk_size)
                if not chunk:
                    break
                w.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if done == 0 and progress:
            progress(0, total)
        check(cancel)
        try:
            dst_fs.set_mtime(part, info.mtime)
        except NotWritable:
            pass
        dst_fs.rename(part, dst, overwrite=overwrite)
    except BaseException:
        try:
            dst_fs.remove(part)
        except OSError:
            pass
        raise
