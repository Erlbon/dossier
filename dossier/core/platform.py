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


SERVER_SCHEMES = ("sftp://", "scp://", "webdav://", "ftp://", "opds://", "subsonic://", "gdrive://")


def is_full_path(path: str) -> bool:
    """``os.path.isabs``, but the same on every Python: before 3.12 a share root itself (``\\\\nas\\Media``, no backslash
    after the share) was not absolute on Windows. Any path starting with two slashes there is a network or long path."""
    return os.path.isabs(path) or (IS_WINDOWS and len(path) > 2 and path[0] in "\\/" and path[1] in "\\/")


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


def is_case_only_change(old: str, new: str) -> bool:
    """True when ``old`` and ``new`` differ only in the case of letters (or, off Windows, in how an accented letter is written:
    composed or decomposed) and the system sees them as one file, so
    renaming one to the other is a change of spelling, never a clash with another item. Always so on Windows; on
    other systems only where the volume ignores case (macOS's default APFS, a FAT or NTFS stick on Linux), which
    the system itself answers: both names reach the same file."""
    if old == new or has_scheme(old) or has_scheme(new):
        return False
    if IS_WINDOWS:
        return os.path.normcase(old) == os.path.normcase(new)
    import unicodedata
    # The Mac's disk also ignores how an accent is written ("e" plus a combining accent, or one "é"): a respelling of either kind
    # is the same file there.
    if unicodedata.normalize("NFC", old).lower() != unicodedata.normalize("NFC", new).lower():
        return False
    try:
        return os.path.samefile(old, new)
    except (OSError, ValueError):
        return False


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
_UF_HIDDEN = 0x8000     # the Mac's (and BSD's) "hidden" file flag, which Finder uses for ~/Library and the like
HIDDEN_FLAG = 1 << 24   # carried in an Entry's mode bits off Windows when the item has that flag (above every mode bit)


def mode_and_flags(st) -> int:
    """An item's mode bits off Windows, with ``HIDDEN_FLAG`` added when the system's own hidden flag is set (the Mac's ``UF_HIDDEN``,
    read from ``st_flags``; Linux has no such flag, so there it is the mode alone)."""
    flags = getattr(st, "st_flags", 0) or 0
    return int(st.st_mode) | (HIDDEN_FLAG if flags & _UF_HIDDEN else 0)


def is_hidden_name(name: str) -> bool:
    """Hidden by its name: a dot name off Windows, and on every system the Mac's AppleDouble ``._name`` leftovers."""
    return name.startswith("._") or (not IS_WINDOWS and name.startswith("."))


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


_GVFS_REMOVABLE = ("mtp", "gphoto2", "afc", "cdda")            # phones, cameras, iPhones, audio CDs
_GVFS_NETWORK = ("smb-share", "smb-server", "sftp", "ftp", "ftps", "dav", "davs", "nfs", "afp-volume", "google-drive",
                 "onedrive", "dns-sd", "network")


def _gvfs_value(text: str) -> str:
    from urllib.parse import unquote
    return unquote(text)


def gvfs_label(name: str) -> tuple:
    """``(label, kind)`` for one mount in the desktop's GVfs folder, from its name: ``smb-share:server=nas,share=media`` is "media
    on nas", network; ``mtp:host=SAMSUNG_Galaxy`` is "SAMSUNG Galaxy", removable."""
    scheme, _, rest = name.partition(":")
    fields = {}
    for part in rest.split(","):
        key, _, value = part.partition("=")
        if key:
            fields[key] = _gvfs_value(value)
    kind = "removable" if scheme in _GVFS_REMOVABLE else "network"
    if scheme == "smb-share" and "share" in fields:
        label = f"{fields['share']} on {fields.get('server', '?')}"
    elif scheme == "google-drive":
        label = f"Google Drive ({fields.get('user', '')}@{fields.get('host', '')})".replace("(@)", "").strip()
    elif scheme in _GVFS_REMOVABLE:
        label = fields.get("host", rest).replace("_", " ")
    else:
        where = fields.get("host") or fields.get("server") or rest
        label = f"{where}{' (' + fields['user'] + ')' if fields.get('user') else ''} ({scheme})"
    return label, kind


def is_desktop_mount(path: str) -> bool:
    """A share or phone mounted by the Linux desktop (GVfs or KDE's kio-fuse), whose folder name says little: shown by its label."""
    return "/gvfs/" in path or "/kio-fuse-" in path


def gvfs_volumes(folder: str, listdir=os.listdir) -> list:
    """``(root, label, kind)`` for each share, phone or camera the desktop mounted in its GVfs ``folder``. Reading that folder only
    lists the mounts: no share is asked anything."""
    try:
        names = sorted(listdir(folder))
    except OSError:
        return []
    return [(folder.rstrip("/") + "/" + n, *gvfs_label(n)) for n in names]


def _posix_volumes() -> list:
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    return volumes_from_mounts(lines)


def volumes_from_mounts(lines: list, listdir=os.listdir) -> list:
    """``(root, label, kind)`` from the lines of Linux's mount table (``/proc/mounts``)."""
    out = []
    seen = set()
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if mount in seen:
            continue
        if fstype == "fuse.gvfsd-fuse":                  # the desktop's own mounts: one folder per share, phone or camera
            seen.add(mount)
            out += gvfs_volumes(mount, listdir)
            continue
        if fstype == "fuse.kio-fuse":                    # KDE's network folders, when it mounts them through FUSE
            seen.add(mount)
            out.append((mount, "KDE network folders", "network"))
            continue
        if fstype in _PSEUDO_FS:
            continue
        network = fstype.startswith(_NETWORK_FS)
        if not (device.startswith("/dev/") or network) or (mount != "/" and mount.startswith(_SKIP_MOUNT_PREFIXES)):
            continue
        seen.add(mount)
        kind = "network" if network else ("removable" if mount.startswith(("/media", "/run/media", "/Volumes")) else "fixed")
        out.append((mount, "System" if mount == "/" else os.path.basename(mount), kind))
    if not out and IS_MACOS:
        out.append(("/", "System", "fixed"))
        for name in sorted(listdir("/Volumes")) if os.path.isdir("/Volumes") else []:
            if not os.path.islink(os.path.join("/Volumes", name)):         # the start-up disk's link back to /
                out.append((os.path.join("/Volumes", name), name, "removable"))
    return out or [("/", "System", "fixed")]


_MAC_NETWORK_FS = ("smbfs", "nfs", "afpfs", "webdav", "cifs", "ftp", "macfuse-sshfs", "osxfuse-sshfs")
_MAC_SKIP_FS = ("devfs", "autofs", "nullfs", "fdesc")
_MNT_RDONLY, _MNT_LOCAL, _MNT_ROOTFS, _MNT_DONTBROWSE = 0x1, 0x1000, 0x4000, 0x00100000


def _mac_mounts() -> list:
    """The Mac's own mount list, the one ``mount`` prints: ``(fstype, mount point, source, flags)`` for each, read with
    ``getmntinfo`` (MNT_NOWAIT, so a dead share is never asked)."""
    import ctypes
    import ctypes.util

    class StatFs(ctypes.Structure):                  # struct statfs, 64-bit inode layout (the only one on Apple Silicon)
        _fields_ = [("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32), ("f_blocks", ctypes.c_uint64),
                    ("f_bfree", ctypes.c_uint64), ("f_bavail", ctypes.c_uint64), ("f_files", ctypes.c_uint64),
                    ("f_ffree", ctypes.c_uint64), ("f_fsid", ctypes.c_int32 * 2), ("f_owner", ctypes.c_uint32),
                    ("f_type", ctypes.c_uint32), ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
                    ("f_fstypename", ctypes.c_char * 16), ("f_mntonname", ctypes.c_char * 1024),
                    ("f_mntfromname", ctypes.c_char * 1024), ("f_flags_ext", ctypes.c_uint32),
                    ("f_reserved", ctypes.c_uint32 * 7)]

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    try:
        call = getattr(libc, "getmntinfo$INODE64")   # Intel Macs keep the old layout under the plain name
    except AttributeError:
        call = libc.getmntinfo
    call.argtypes = [ctypes.POINTER(ctypes.POINTER(StatFs)), ctypes.c_int]
    call.restype = ctypes.c_int
    table = ctypes.POINTER(StatFs)()
    count = call(ctypes.byref(table), 2)              # MNT_NOWAIT
    return [(table[i].f_fstypename.decode("utf-8", "replace"), os.fsdecode(table[i].f_mntonname),
             os.fsdecode(table[i].f_mntfromname), table[i].f_flags) for i in range(max(count, 0))]


def mac_volumes(mounts: list) -> list:
    """``(root, label, kind)`` for the Mac's mounts (see ``_mac_mounts``): the start-up disk as "/", shares as network
    (no bin there: a delete is permanent, and the plan says so), other disks under /Volumes as removable. The system's
    hidden volumes (Data, Preboot, VM...) and pseudo file systems are left out."""
    out, seen = [], set()
    for fstype, mount, _source, flags in mounts:
        if fstype in _MAC_SKIP_FS or mount in seen:
            continue
        network = fstype.startswith(_MAC_NETWORK_FS) or not flags & _MNT_LOCAL
        if mount == "/" or flags & _MNT_ROOTFS:
            kind, label = "fixed", "System"
        elif flags & _MNT_DONTBROWSE and not network:
            continue
        elif network:
            kind, label = "network", os.path.basename(mount)
        elif mount.startswith("/Volumes/"):
            kind, label = "removable", os.path.basename(mount)
        else:
            continue
        seen.add(mount)
        out.append((mount, label, kind))
    return out


def _posix_or_mac_volumes() -> list:
    if IS_MACOS:
        try:
            found = mac_volumes(_mac_mounts())
        except (OSError, AttributeError, ValueError):
            found = []
        return found or _posix_volumes()
    return _posix_volumes()


def list_volumes() -> list:
    """The mounted volumes as ``(root, label, kind)``; kind is fixed, removable, network, optical or other.
    Drive letters on Windows, mount points elsewhere (O3). Never touches the disk space of a share, so it
    cannot hang on a dead network drive."""
    return _windows_volumes() if IS_WINDOWS else _posix_or_mac_volumes()


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


def set_title_backdrop(hwnd: int, on: bool, dark: bool = False) -> bool:
    """Give the title bar of this window Windows 11's frosted material (acrylic), or put the plain one back. ``dark`` makes the title text
    and buttons light, to match a dark scheme. It is the window's own look: nothing else changes. Windows 10 and other systems ignore it
    (returns False)."""
    if not IS_WINDOWS:
        return False
    import ctypes
    try:
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        hole = ctypes.c_void_p(int(hwnd))
        dark_mode = ctypes.c_int(1 if dark else 0)
        set_attribute(hole, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))               # DWMWA_USE_IMMERSIVE_DARK_MODE
        backdrop = ctypes.c_int(3 if on else 0)                                                 # DWMSBT_TRANSIENTWINDOW (acrylic) / automatic
        return set_attribute(hole, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)) == 0   # DWMWA_SYSTEMBACKDROP_TYPE
    except (AttributeError, OSError, ValueError):
        return False


class _TaskbarList3:
    """The progress fill on a window's taskbar button (Windows 7 and later), through the shell's ITaskbarList3 COM object. Made
    on the first use; a system without it (or a refusal) turns every later call into nothing."""

    _FLAGS = {"none": 0, "indeterminate": 1, "normal": 2, "error": 4, "paused": 8}       # TBPF_*

    def __init__(self, hwnd) -> None:
        self._hwnd = hwnd
        self._object = None
        self._calls = None
        self._broken = False

    def _make(self) -> None:
        import ctypes
        import uuid
        from ctypes import wintypes

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)                         # the GUI thread is already a COM apartment (Qt): this only counts one more user
        clsid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("56FDF344-FD6D-11D0-958A-006097C9A090").bytes_le)   # CLSID_TaskbarList
        iid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF").bytes_le)     # IID_ITaskbarList3
        pointer = ctypes.c_void_p()
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.HRESULT
        ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer))   # CLSCTX_INPROC_SERVER
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

        def method(index, *args):
            return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *args)(table[index])

        method(3)(pointer)                                                                 # HrInit
        self._calls = (method(9, wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong),  # SetProgressValue
                       method(10, wintypes.HWND, ctypes.c_int))                            # SetProgressState
        self._object = pointer

    def set(self, state: str, done: int, total: int) -> None:
        if self._broken:
            return
        try:
            if self._object is None:
                self._make()
            set_value, set_state = self._calls
            hwnd = int(self._hwnd())
            set_state(self._object, hwnd, self._FLAGS[state])
            if state in ("normal", "paused", "error"):                                     # the colour first: a value alone turns the bar green
                set_value(self._object, hwnd, done, total)
        except (AttributeError, OSError, ValueError, KeyError):
            self._broken = True


def taskbar_button(hwnd):
    """Something with ``set(state, done, total)`` that shows progress on the taskbar button of the window ``hwnd()`` gives (asked at
    every call, as the window may be made again), or None where the system has no such thing. ``core.taskbar`` decides what it shows.
    Linux: None (the Unity launcher's progress needs a desktop file id and D-Bus; not worth it while the Linux build has no
    desktop entry)."""
    return _TaskbarList3(hwnd) if IS_WINDOWS else None


def ask_windows_to_close(exe_name: str, skip_pids=()) -> list:
    """Windows: send the ordinary close request (WM_CLOSE, what a window's own close button sends) to every visible top-level window
    of every running program called ``exe_name`` of this desktop, except the processes in ``skip_pids`` and this one. The program
    closes as it always does (saving its state, asking about unsaved text). Returns the process ids asked; [] elsewhere."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    skip = set(skip_pids) | {os.getpid()}
    names: dict = {}
    found: dict = {}

    def image_of(pid: int) -> str:
        if pid not in names:
            names[pid] = ""
            handle = kernel32.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        names[pid] = os.path.basename(buf.value)
                finally:
                    kernel32.CloseHandle(handle)
        return names[pid]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):            # GW_OWNER: top-level windows only
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in skip and image_of(pid.value).lower() == exe_name.lower():
                found.setdefault(pid.value, []).append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    for hwnds in found.values():
        for hwnd in hwnds:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)                                  # WM_CLOSE
    return list(found)


def process_running(pid: int) -> bool:
    """Whether the process ``pid`` still runs."""
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x00100000, False, pid)                      # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102                 # WAIT_TIMEOUT: still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_remote_session() -> bool:
    """True inside a remote desktop session, where window transparency and blur are not available."""
    if not IS_WINDOWS:
        return False
    import ctypes
    try:
        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))                    # SM_REMOTESESSION
    except (AttributeError, OSError):
        return False


def set_blur_behind(hwnd: int, tint: int = 0x01ffffff, kind: str = "acrylic") -> bool:
    """Blur whatever is behind this window (Windows 10 and 11). ``kind`` is ``acrylic`` (the strong frosted blur) or ``plain`` (the older,
    lighter blur-behind). ``tint`` is a colour ``0xAABBGGRR`` laid over the blur: a black one (alpha 0 counts as black) turns the whole
    window black and a dark one makes it too dark, so the default is a nearly clear white (measured on Windows 11, 2026-10-28). Returns
    False when the system refuses, so the caller can fall back to a plain see-through window."""
    if not IS_WINDOWS:
        return False
    import ctypes

    class Accent(ctypes.Structure):
        _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("tint", ctypes.c_uint), ("animation", ctypes.c_int)]

    class Attribute(ctypes.Structure):
        _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

    try:
        call = ctypes.windll.user32.SetWindowCompositionAttribute
        call.argtypes = [ctypes.c_void_p, ctypes.POINTER(Attribute)]
        accent = Accent(3 if kind == "plain" else 4, 2, tint, 0)                      # ACCENT_ENABLE_BLURBEHIND / ..._ACRYLICBLURBEHIND, with the tint
        data = Attribute(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))   # WCA_ACCENT_POLICY
        return bool(call(ctypes.c_void_p(int(hwnd)), ctypes.byref(data)))
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


def no_window_flags() -> int:
    """``creationflags`` for a console program started in the background: no black window flashes up on Windows (0 elsewhere)."""
    import subprocess
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


PS_SINGLE_QUOTES ="'" + chr(0x2018) + chr(0x2019) + chr(0x201A) + chr(0x201B)


def ps_quote(text: str) -> str:
    """``text`` as a PowerShell single-quoted string. PowerShell ends such a string at any of four quote characters (the straight
    one and the curly ones), so each is doubled, as PowerShell's own ``EscapeSingleQuotedStringContent`` does: a folder named
    ``a’; command; ’`` stays one string and never becomes a command."""
    return "'" + "".join(c + c if c in PS_SINGLE_QUOTES else c for c in str(text)) + "'"


def windows_program(name: str) -> str:
    """The full path of one of Windows' own programs (``powershell.exe``, ``net.exe``), so a file of that name in the current
    folder is never started instead, least of all with administrator rights."""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:" + chr(92) + "Windows"
    sub = {"powershell.exe": ("System32", "WindowsPowerShell", "v1.0")}.get(name.lower(), ("System32",))
    return os.path.join(root, *sub, name)


FILE_MANAGER_NAME = "Explorer" if IS_WINDOWS else "Finder" if IS_MACOS else "the File Manager"


def file_manager_command(path: str, select: bool):
    """The command that shows ``path`` in the system's own file manager: with ``select``, its folder with ``path`` selected
    (Linux has no standard way to select, so the folder only), else ``path`` itself opened. A string on Windows, where
    Explorer's ``/select,`` wants its own quoting that a list would spoil; a list elsewhere."""
    if IS_WINDOWS:
        explorer = os.path.join(os.environ.get("SystemRoot") or os.environ.get("windir") or "C:" + chr(92) + "Windows", "explorer.exe")
        return f'"{explorer}" /select,"{path}"' if select else f'"{explorer}" "{path}"'
    if IS_MACOS:
        return ["open", "-R", path] if select else ["open", path]
    return ["xdg-open", os.path.dirname(path.rstrip("/")) or "/" if select else path]


def open_with_command(path: str) -> Optional[list]:
    """The system's own "Open with" chooser for one file, or None where there is none (only Windows has one to call)."""
    if not IS_WINDOWS:
        return None
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:" + chr(92) + "Windows"
    return [os.path.join(root, "System32", "rundll32.exe"), "shell32.dll,OpenAs_RunDLL", path]


def console_encoding() -> str:
    """The encoding a console program's output is written in (the OEM code page on Windows)."""
    if IS_WINDOWS:
        import ctypes
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    return "utf-8"


def home_dir() -> str:
    return os.path.expanduser("~")


# the user's own folders: Home page places ----------------------------------------------------------------------------------------
KNOWN_FOLDERS = (("DESKTOP", "Desktop"), ("DOCUMENTS", "Documents"), ("DOWNLOAD", "Downloads"), ("PICTURES", "Pictures"),
                 ("MUSIC", "Music"), ("VIDEOS", "Videos"))
_USER_DIR_LINE = re.compile(r'\s*XDG_([A-Z]+)_DIR\s*=\s*"(.*)"\s*$')


def parse_user_dirs(text: str, home: str) -> dict:
    """The desktop's own folder names from the freedesktop ``user-dirs.dirs`` file: ``{"DESKTOP": "/home/a/Skrivebord", ...}``. A
    line names ``$HOME/...`` or a full path; one that names the home folder itself turns that folder off (left out)."""
    found = {}
    for line in text.splitlines():
        m = _USER_DIR_LINE.match(line)
        if not m:
            continue
        value = m.group(2).replace(chr(92) + '"', '"')
        if value.startswith("$HOME"):
            value = home.rstrip("/") + value[5:]
        elif not value.startswith("/"):
            continue
        value = value.rstrip("/")
        if value and value != home.rstrip("/"):
            found[m.group(1)] = value
    return found


def user_folders(home: str, read=None) -> list:
    """``(title, path)`` of the user's own folders, whether they exist or not (the caller checks). On Linux the desktop's own names from
    ``~/.config/user-dirs.dirs`` (a Norwegian Ubuntu says ``Skrivebord``, ``Nedlastinger``), shown by those names; elsewhere, or when
    the file has no line for one, the English name. On the Mac Applications follows. ``read`` reads a file's text (for tests)."""
    named: dict = {}
    if IS_LINUX:
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        file = os.path.join(config, "user-dirs.dirs")
        try:
            if read is None:
                with open(file, encoding="utf-8") as f:
                    text = f.read()
            else:
                text = read(file)
        except (OSError, UnicodeDecodeError):
            text = ""
        named = parse_user_dirs(text, home)
    out = []
    for key, english in KNOWN_FOLDERS:
        path = named.get(key) or os.path.join(home, english)
        out.append((os.path.basename(path) if key in named else english, path))
    if IS_MACOS:
        out.append(("Applications", "/Applications"))
    return out


def system_cloud_folders(home: str) -> list:
    """``(title, path)`` of cloud folders the system itself keeps: iCloud Drive on the Mac. None elsewhere."""
    if IS_MACOS:
        return [("iCloud Drive", os.path.join(home, "Library", "Mobile Documents", "com~apple~CloudDocs"))]
    return []


# Cloning a file (card 66B): the file system's own "copy that shares the data blocks" -----------------------------------------------

def fstype_from_mounts(path: str, mounts: list) -> str:
    """The file system name (lower case) of the mount that holds ``path``: the longest mount point that is a parent of it.
    ``mounts`` is ``[(fstype, mount point), ...]``. "" when none fits."""
    best, name = -1, ""
    target = path.rstrip("/") or "/"
    for fstype, mount in mounts:
        base = mount.rstrip("/") or "/"
        if target == base or base == "/" or target.startswith(base + "/"):
            if len(base) > best:
                best, name = len(base), fstype.lower()
    return name


def _linux_mounts() -> list:
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 3:
            out.append((parts[2], parts[1].replace(chr(92) + "040", " ")))
    return out


def filesystem_name(path: str) -> str:
    """The file system the volume of ``path`` uses, lower case (ntfs, refs, apfs, btrfs, xfs, ext4...), or "" when it cannot be told."""
    try:
        if IS_WINDOWS:
            import ctypes
            drive = os.path.splitdrive(os.path.abspath(strip_longpath(path)))[0]
            if not drive:
                return ""
            buf = ctypes.create_unicode_buffer(64)
            if ctypes.windll.kernel32.GetVolumeInformationW(drive.rstrip(chr(92)) + chr(92), None, 0, None, None, None, buf, 64):
                return buf.value.lower()
            return ""
        real = os.path.realpath(path)
        if IS_MACOS:
            return fstype_from_mounts(real, [(t, m) for t, m, _s, _f in _mac_mounts()])
        return fstype_from_mounts(real, _linux_mounts())
    except (OSError, AttributeError, ValueError):
        return ""


def clone_native(src: str, dst: str) -> None:
    """Make ``dst`` (which must not exist) a clone of ``src``: same data blocks, copy-on-write. Raises OSError when the file system
    cannot (the half-made ``dst`` is removed). APFS: ``clonefile``; Linux (btrfs, XFS): the ``FICLONE`` ioctl; Windows (ReFS):
    ``FSCTL_DUPLICATE_EXTENTS_TO_FILE`` (untested on a ReFS volume)."""
    if IS_MACOS:
        import ctypes
        import ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        if libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), dst)
        return
    if IS_LINUX:
        import fcntl
        source = os.open(src, os.O_RDONLY)
        try:
            target = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                fcntl.ioctl(target, 0x40049409, source)          # FICLONE
            except OSError:
                os.close(target)
                target = -1
                os.unlink(dst)
                raise
            finally:
                if target >= 0:
                    os.close(target)
        finally:
            os.close(source)
        return
    if IS_WINDOWS:
        _clone_refs(src, dst)
        return
    raise OSError(95, "This system cannot clone files", dst)


def _clone_refs(src: str, dst: str) -> None:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    k32.SetEndOfFile.argtypes = [wintypes.HANDLE]
    invalid = wintypes.HANDLE(-1).value

    class Extents(ctypes.Structure):                              # DUPLICATE_EXTENTS_DATA
        _fields_ = [("FileHandle", wintypes.HANDLE), ("SourceFileOffset", ctypes.c_longlong),
                    ("TargetFileOffset", ctypes.c_longlong), ("ByteCount", ctypes.c_longlong)]

    def fail(path):
        code = ctypes.get_last_error()
        if code:
            raise ctypes.WinError(code)
        raise OSError(5, "Windows could not clone the file", path)

    size = os.path.getsize(src)
    sectors, per_sector, free, total = (wintypes.DWORD() for _ in range(4))
    cluster = 65536
    root = os.path.splitdrive(os.path.abspath(src))[0] + chr(92)
    if k32.GetDiskFreeSpaceW(root, ctypes.byref(sectors), ctypes.byref(per_sector), ctypes.byref(free), ctypes.byref(total)):
        cluster = max(sectors.value * per_sector.value, 4096)
    rounded = -(-size // cluster) * cluster
    source = k32.CreateFileW(longpath(src), 0x80000000, 7, None, 3, 0x80, None)         # GENERIC_READ, share all, OPEN_EXISTING
    if source == invalid:
        fail(src)
    target = k32.CreateFileW(longpath(dst), 0xC0000000, 0, None, 1, 0x80, None)         # read+write, CREATE_NEW
    if target == invalid:
        k32.CloseHandle(source)
        fail(dst)
    ok = False
    try:
        if rounded:
            if not k32.SetFilePointerEx(target, rounded, None, 0) or not k32.SetEndOfFile(target):
                fail(dst)
            step = max((1 << 30) // cluster, 1) * cluster         # about 1 GiB, a whole number of clusters
            offset = 0
            while offset < rounded:
                count = min(step, rounded - offset)
                data = Extents(source, offset, offset, count)
                returned = wintypes.DWORD()
                if not k32.DeviceIoControl(target, 0x98344, ctypes.byref(data), ctypes.sizeof(data), None, 0, ctypes.byref(returned), None):
                    fail(dst)
                offset += count
            if rounded != size:
                if not k32.SetFilePointerEx(target, size, None, 0) or not k32.SetEndOfFile(target):
                    fail(dst)
        ok = True
    finally:
        k32.CloseHandle(target)
        k32.CloseHandle(source)
        if not ok:
            try:
                os.unlink(dst)
            except OSError:
                pass

