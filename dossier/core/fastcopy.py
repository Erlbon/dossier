"""The operating system's own copy for large local files (copy engine plan, C5).

Windows: ``CopyFileExW`` with a progress routine. It is the call Explorer uses; it copies in the kernel,
keeps the attributes and time stamps, and also carries alternate data streams along. Linux: a loop of
``os.copy_file_range``, which lets the kernel (or the file system, as a reflink or a server-side copy)
move the data without passing it through Python. Anywhere else, or when the system refuses, ``fast_copy``
returns False before anything was written and the caller copies by itself.

Progress, pause and cancel work as in the plain copy: the routine is called every chunk, blocks while the
token is paused, and stops the copy when it is cancelled.
"""
from __future__ import annotations

import errno
import os
import sys
from typing import Optional

from .platform import IS_WINDOWS, longpath
from .progress import Cancelled, CancelToken, ProgressFn, check

FAST_MIN = 8 * 1024 * 1024            # smaller files are better served by the worker pool of ``execute``
RANGE_CHUNK = 16 * 1024 * 1024
_NOT_HERE = (errno.ENOSYS, errno.EXDEV, errno.EINVAL, errno.EOPNOTSUPP, errno.EPERM, errno.EBADF)


def available() -> bool:
    return IS_WINDOWS or hasattr(os, "copy_file_range")


def fast_copy(src: str, dst: str, total: int, progress: Optional[ProgressFn], cancel: Optional[CancelToken]) -> bool:
    """Copy ``src`` to ``dst`` (both plain local paths). True when done; False when the system cannot do it
    and nothing was written; raises ``Cancelled`` or ``OSError`` otherwise (``dst`` may then be partial)."""
    if IS_WINDOWS:
        return _copy_file_ex(src, dst, total, progress, cancel)
    if hasattr(os, "copy_file_range") and sys.platform.startswith("linux"):
        return _copy_range(src, dst, total, progress, cancel)
    return False


# Windows -------------------------------------------------------------------------------------------
def _copy_file_ex(src: str, dst: str, total: int, progress, cancel) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    routine = ctypes.WINFUNCTYPE(wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong,
                                 ctypes.c_longlong, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
                                 wintypes.HANDLE, wintypes.LPVOID)
    copy = kernel32.CopyFileExW
    copy.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, routine, wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL),
                     wintypes.DWORD]
    copy.restype = wintypes.BOOL
    PROGRESS_CONTINUE, PROGRESS_CANCEL = 0, 1
    ALLOW_DECRYPTED_DESTINATION = 0x8
    ERROR_REQUEST_ABORTED = 1235
    stopped: dict = {}

    def on_chunk(file_size, transferred, _stream_size, _stream_done, _stream, _reason, _hsrc, _hdst, _data):
        try:
            check(cancel)                                  # waits while paused, raises when cancelled
            if progress is not None:
                progress(min(int(transferred), int(file_size) or int(transferred)), int(file_size) or total)
        except BaseException as e:                         # never let an exception cross into the system call
            stopped["why"] = e
            return PROGRESS_CANCEL
        return PROGRESS_CONTINUE

    callback = routine(on_chunk)                           # kept alive for the whole call
    ok = copy(longpath(src), longpath(dst), callback, None, None, ALLOW_DECRYPTED_DESTINATION)
    if "why" in stopped:
        raise stopped["why"]
    if not ok:
        code = ctypes.get_last_error()
        if code == ERROR_REQUEST_ABORTED and cancel is not None and cancel.cancelled:
            raise Cancelled()
        raise ctypes.WinError(code)
    return True


# Linux ---------------------------------------------------------------------------------------------
def _copy_range(src: str, dst: str, total: int, progress, cancel) -> bool:
    done = 0
    with open(src, "rb") as r, open(dst, "wb") as w:
        while done < total:
            check(cancel)
            try:
                n = os.copy_file_range(r.fileno(), w.fileno(), min(RANGE_CHUNK, total - done))
            except OSError as e:
                if done == 0 and e.errno in _NOT_HERE:
                    return False                           # this pair of files cannot be done this way
                raise
            if n == 0:
                break                                      # the source got shorter than it was: the caller checks
            done += n
            if progress is not None:
                progress(done, total)
    try:
        import shutil
        shutil.copymode(src, dst)
    except OSError:
        pass
    return True
