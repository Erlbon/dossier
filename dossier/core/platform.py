"""The only place that knows which operating system we run on (spec section 13).

The rest of the core calls these helpers and never tests ``sys.platform`` itself.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

REPLACEMENT = "\ufffd"


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+)://")   # two or more letters: 'C://' is a drive
_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = "\\\\?\\UNC\\"
# Windows refuses ordinary paths near 260 characters (folders already at 248); stay safely below.
_LONGPATH_THRESHOLD = 240


def has_scheme(path: str) -> bool:
    """True for a path of a virtual file system (``zip://a.zip/x``), false for a local path."""
    return bool(_SCHEME.match(path))


SERVER_SCHEMES = ("sftp://", "scp://", "webdav://")


def is_server_path(path: str) -> bool:
    """True for a path on a server that is reached over the network (``sftp://user@host/dir``): no recycle bin, slow, may drop."""
    return path.startswith(SERVER_SCHEMES)


def strip_longpath(path: str) -> str:
    """Remove the Windows extended-length prefix so one file has one spelling."""
    if not IS_WINDOWS:
        return path
    if path.startswith(_EXTENDED_UNC):
        return "\\\\" + path[len(_EXTENDED_UNC):]
    if path.startswith(_EXTENDED):
        return path[len(_EXTENDED):]
    return path


def longpath(path: str) -> str:
    """The form to hand to the operating system (O6, F12).

    On Windows a path of 240 characters or more becomes an extended-length path, which is
    absolute and not normalised by the system, so it is made absolute first. Shorter paths and
    every path on other systems are returned unchanged.
    """
    if not IS_WINDOWS or len(path) < _LONGPATH_THRESHOLD or path.startswith(_EXTENDED):
        return path
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return _EXTENDED_UNC + full[2:]
    return _EXTENDED + full


def path_key(path: str) -> str:
    """Identity key for a path: equal keys mean the same file on this system.

    Windows compares paths without regard to case, Linux does not (O11), so this
    delegates to ``os.path.normcase``. The original spelling is kept elsewhere for display.
    Paths of a virtual file system carry a scheme (``zip://a.zip/x``): they never equal a
    local path, the scheme is case-folded and the rest is compared exactly.
    """
    m = _SCHEME.match(path)
    if m:
        return m.group(1).lower() + "://" + path[m.end():]
    return os.path.normcase(os.path.normpath(strip_longpath(path)))


def decode_name(name: str | bytes) -> str:
    """Make a file name safe to show (O12).

    Linux names are arbitrary bytes. Bytes that are not valid text become U+FFFD, so a
    listing never fails on one odd file.
    """
    if isinstance(name, bytes):
        try:
            name = os.fsdecode(name)
        except UnicodeDecodeError:  # Windows: the file system encoding has no escape for bad bytes
            name = name.decode("utf-8", errors="replace")
    # Undecodable bytes (Linux) and unpaired UTF-16 halves (NTFS) are lone surrogates; they cannot be displayed.
    return "".join(REPLACEMENT if "\ud800" <= ch <= "\udfff" else ch for ch in name)


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def is_link_like(st_mode_is_link: bool, attributes: int | None = None) -> bool:
    """True for symlinks and, on Windows, junctions and other reparse points.

    Walking into these can loop forever (a junction pointing at its own parent), so callers
    treat them as leaves. ``attributes`` is ``st_file_attributes`` where the system has it.
    """
    if st_mode_is_link:
        return True
    return IS_WINDOWS and attributes is not None and bool(attributes & _REPARSE_POINT)


_PSEUDO_FS = {
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2", "overlay", "squashfs", "autofs",
    "securityfs", "debugfs", "tracefs", "configfs", "fusectl", "mqueue", "hugetlbfs", "pstore", "bpf",
    "binfmt_misc", "ramfs", "efivarfs", "nsfs", "rpc_pipefs", "fuse.gvfsd-fuse", "fuse.portal",
}
_NETWORK_FS = ("nfs", "nfs4", "cifs", "smbfs", "smb3", "fuse.sshfs", "fuse.rclone", "davfs", "9p")
_SKIP_MOUNT_PREFIXES = ("/boot", "/snap", "/var/lib", "/proc", "/sys", "/dev", "/run/user", "/run/snapd")


def _windows_volumes() -> list:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kinds = {2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "fixed"}
    old_mode = kernel32.SetErrorMode(1)   # SEM_FAILCRITICALERRORS: no "insert a disk" pop-ups
    try:
        mask = kernel32.GetLogicalDrives()
        out = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = f"{chr(65 + i)}:\\"
            kind = kinds.get(kernel32.GetDriveTypeW(root), "other")
            label = ""
            if kind in ("fixed", "removable"):   # never ask a network share: it can hang for seconds
                buf = ctypes.create_unicode_buffer(261)
                if kernel32.GetVolumeInformationW(wintypes.LPCWSTR(root), buf, 261, None, None, None, None, 0):
                    label = buf.value
            elif kind == "network":
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if ctypes.windll.mpr.WNetGetConnectionW(f"{chr(65 + i)}:", buf, ctypes.byref(size)) == 0:
                    label = buf.value
            out.append((root, label, kind))
        return out
    finally:
        kernel32.SetErrorMode(old_mode)


def _posix_volumes() -> list:
    out = []
    seen = set()
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype in _PSEUDO_FS or mount in seen:
            continue
        network = fstype.startswith(_NETWORK_FS)
        if not (device.startswith("/dev/") or network) or (mount != "/" and mount.startswith(_SKIP_MOUNT_PREFIXES)):
            continue
        seen.add(mount)
        kind = "network" if network else ("removable" if mount.startswith(("/media", "/run/media", "/Volumes")) else "fixed")
        out.append((mount, "System" if mount == "/" else os.path.basename(mount), kind))
    if not out and IS_MACOS:
        for name in sorted(os.listdir("/Volumes")) if os.path.isdir("/Volumes") else []:
            out.append((os.path.join("/Volumes", name), name, "fixed"))
    return out or [("/", "System", "fixed")]


def list_volumes() -> list:
    """The mounted volumes as ``(root, label, kind)``; kind is fixed, removable, network, optical or other.
    Drive letters on Windows, mount points elsewhere (O3). Never touches the disk space of a share, so it
    cannot hang on a dead network drive."""
    return _windows_volumes() if IS_WINDOWS else _posix_volumes()


def set_app_id(app_id: str) -> None:
    """Tell Windows this program is its own application, so the taskbar groups its windows under its own icon
    instead of the Python interpreter's. Does nothing elsewhere."""
    if IS_WINDOWS:
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except (AttributeError, OSError):
            pass


def set_window_border(hwnd: int, color: Optional[str]) -> bool:
    """Colour the thin border Windows 11 draws round a window (``#rrggbb``), or remove it (``None``). It is
    the window's own look, not a system setting: only this window changes. Older Windows and other systems
    ignore it (returns False)."""
    if not IS_WINDOWS:
        return False
    import ctypes
    try:
        if color is None:
            colorref = ctypes.c_uint32(0xFFFFFFFE)                                   # DWMWA_COLOR_NONE
        else:
            rgb = int(color.lstrip("#"), 16)
            colorref = ctypes.c_uint32(((rgb & 0xFF) << 16) | (rgb & 0xFF00) | (rgb >> 16))   # 0x00BBGGRR
        DWMWA_BORDER_COLOR = 34
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), DWMWA_BORDER_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref))
        return result == 0
    except (AttributeError, OSError, ValueError):
        return False


def machine_name() -> str:
    """This computer's name, for the file manager's title."""
    import socket
    try:
        return socket.gethostname() or "this computer"
    except OSError:
        return "this computer"


def is_elevated() -> bool:
    """True when this process runs with administrator (Windows) or root rights."""
    if IS_WINDOWS:
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def quote_arg(arg: str) -> str:
    """One argument, quoted for the shell the command line uses (cmd on Windows, sh elsewhere)."""
    if IS_WINDOWS:
        import subprocess
        return subprocess.list2cmdline([arg])
    import shlex
    return shlex.quote(arg)


def console_encoding() -> str:
    """The encoding a console program's output is written in (the OEM code page on Windows)."""
    if IS_WINDOWS:
        import ctypes
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    return "utf-8"


def home_dir() -> str:
    return os.path.expanduser("~")


def is_hidden(name: str, attributes: int | None = None) -> bool:
    """Hidden by the dot on Linux; on Windows by the hidden attribute (O9)."""
    if IS_WINDOWS and attributes is not None:
        return bool(attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN
    return name.startswith(".")
