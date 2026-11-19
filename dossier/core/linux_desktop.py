"""Dossier in the Linux desktop's own places (card 52A): a launcher in the application menu, and Dossier as the program that opens
folders. Everything is in the user's own folders (``~/.local/share``, ``~/.config``), nothing system-wide.

- **The launcher:** ``applications/dossier.desktop`` and the icon ``icons/hicolor/256x256/apps/dossier.png`` below the XDG data home.
  Its ``Exec`` points at the running program and takes ``%F``, so a file manager or a browser can pass folders (and files, whose
  folder is shown).
- **Folders:** the key ``inode/directory`` in the ``[Default Applications]`` group of the user's own ``mimeapps.list``. Only that
  one key is changed; every other line and group stays as it was, and the file is replaced as a whole, so a crash never leaves half
  a file. What the key said before is kept by the caller, and ``restore_folder_default`` puts it back. The desktop's own file
  (``gnome-mimeapps.list``) is read first and wins, so where it already names a folder program it is changed the same way and
  put back on Off (question 72A); where it names none it is not touched.

Nothing here imports Qt. Every function takes the folders as parameters; the callers pass ``data_home()`` and ``config_home()``.
The writes are small, but the window still runs them on a thread.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from typing import Optional

from . import desktop_entries as D
from .platform import IS_LINUX

APP_ID = "dossier.desktop"
FOLDER_TYPE = "inode/directory"
DEFAULT_GROUP = "[Default Applications]"
TARBALL_CHANNEL = "linux-tarball"
ICON_RELATIVE = os.path.join("icons", "hicolor", "256x256", "apps", "dossier.png")


# where ----------------------------------------------------------------------------------------------------------------------
def data_home(environ: Optional[dict] = None, home: Optional[str] = None) -> str:
    """``XDG_DATA_HOME``, else ``~/.local/share``."""
    return D.data_dirs(environ, home)[0]


def config_home(environ: Optional[dict] = None, home: Optional[str] = None) -> str:
    """``XDG_CONFIG_HOME``, else ``~/.config``."""
    return D.config_dirs(environ, home)[0]


def launcher_path(data: str) -> str:
    return os.path.join(data, "applications", APP_ID)


def icon_path(data: str) -> str:
    return os.path.join(data, ICON_RELATIVE)


def mimeapps_path(config: str) -> str:
    return os.path.join(config, "mimeapps.list")


# which copy of Dossier this is -----------------------------------------------------------------------------------------------
def running_from_tarball(linux: bool = IS_LINUX, channel: Optional[str] = None) -> bool:
    """True for the Linux tarball: on Linux and its ``update-channel`` file says ``linux-tarball``. ``channel`` is given by tests;
    otherwise it is read beside the program (redactor_common's ``channel_of``). A run from source says ``source``, so is not one."""
    if not linux:
        return False
    if channel is None:
        try:
            from redactor_common.core.selfupdate import channel_of
            channel = channel_of()
        except Exception:                                    # the shared package is missing: then it is no known copy
            return False
    return channel == TARBALL_CHANNEL


def program_command(frozen: Optional[bool] = None, executable: Optional[str] = None) -> list:
    """The words that start this Dossier: the built program itself, or Python running the package when run from source."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable or sys.executable
    return [exe] if frozen else [exe, "-m", "dossier"]


# the launcher text ------------------------------------------------------------------------------------------------------------
_MUST_QUOTE = set(" \t\n\"'" + chr(92) + "><~|&;$*?#()`")


def exec_word(word: str) -> str:
    """One argument of an ``Exec`` line as the Desktop Entry standard writes it: a word with a space or one of the reserved
    characters goes in double quotes, with a backslash before ``"``, `` ` ``, ``$`` and backslash inside them; a percent sign is
    doubled; and every backslash is doubled once more, because the file's value is itself unescaped first (a literal backslash in a
    quoted word is four backslashes in the file)."""
    out = word.replace("%", "%%")
    if out and not any(c in _MUST_QUOTE for c in out):
        return out
    bs = chr(92)
    quoted = "".join(bs + c if c in '"`$' + bs else c for c in out)
    return ('"' + quoted + '"').replace(bs, bs * 2)


def exec_line(command: list, arguments: tuple = ("%F",)) -> str:
    """``command`` (the program and its own arguments) quoted, then the field codes (``%F``) as they are."""
    return " ".join([exec_word(w) for w in command] + list(arguments))


def launcher_text(command: list, icon: str = "dossier", name: str = "Dossier") -> str:
    """A valid ``[Desktop Entry]`` for Dossier. It names ``inode/directory`` so Dossier is offered in Open With for a folder; that
    makes it nobody's default (the folder switch does that)."""
    lines = ["[Desktop Entry]", "Type=Application", "Version=1.0", f"Name={name}", "GenericName=File Manager",
             "Comment=Two-panel file manager that shows a plan before it changes anything",
             "Exec=" + exec_line(command), "Icon=" + icon, "Terminal=false",
             "Categories=Utility;System;FileTools;FileManager;", "MimeType=" + FOLDER_TYPE + ";",
             "StartupWMClass=dossier", "Keywords=files;folders;commander;"]
    return chr(10).join(lines) + chr(10)


# writing safely ----------------------------------------------------------------------------------------------------------------
def write_atomically(path: str, data: bytes, mode: Optional[int] = None) -> None:
    """Write ``data`` to a temporary file in the same folder, then replace ``path`` with it."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dossier-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def install_launcher(data: str, command: list, icon_source: str) -> str:
    """Put the icon and the launcher in the data folder (replacing earlier copies); returns the launcher's path. The launcher names
    the installed icon by its full path, so it shows without waiting for the system's icon cache."""
    target_icon = icon_path(data)
    os.makedirs(os.path.dirname(target_icon), exist_ok=True)
    with open(icon_source, "rb") as f:
        write_atomically(target_icon, f.read(), 0o644)
    path = launcher_path(data)
    write_atomically(path, launcher_text(command, icon=target_icon).encode("utf-8"), 0o755)
    return path


def remove_launcher(data: str) -> bool:
    """Delete the launcher and the icon this module made; True when either existed."""
    found = False
    for p in (launcher_path(data), icon_path(data)):
        try:
            os.remove(p)
            found = True
        except FileNotFoundError:
            pass
    return found


def is_installed(data: str) -> bool:
    return os.path.isfile(launcher_path(data))


def refresh_menu_cache(data: str, which=shutil.which, runner=None) -> bool:
    """Ask ``update-desktop-database`` (when there is one) to look at the user's launchers; a failure is ignored, since desktops
    that need it find the launcher on their own too. True when it ran without an error."""
    tool = which("update-desktop-database")
    if not tool:
        return False
    import subprocess
    try:
        done = (runner or subprocess.run)([tool, os.path.join(data, "applications")], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


# mimeapps.list -----------------------------------------------------------------------------------------------------------------
def _group_name(line: str) -> Optional[str]:
    s = line.strip()
    return s if s.startswith("[") and s.endswith("]") else None


def _key_of(line: str) -> str:
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s or _group_name(s):
        return ""
    return s.partition("=")[0].strip()


def get_key(text: str, group: str, key: str) -> Optional[str]:
    """The raw value of ``key`` in the first ``group`` that has it, or None."""
    current = None
    for line in text.splitlines():
        name = _group_name(line)
        if name is not None:
            current = name
        elif current == group and _key_of(line) == key:
            return line.partition("=")[2].strip()
    return None


def set_key(text: str, group: str, key: str, value: Optional[str]) -> str:
    """``text`` with ``key`` in ``group`` set to ``value`` (None removes the key). Every other line, comment and group is kept as it
    is, with its own line endings; a missing group is added at the end and a missing key at the end of its group. A repeated line
    of the same key in that group is dropped, since only one counts."""
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else chr(10)
    current, last_in_group, seen, out = None, None, False, []
    group_found = False
    for line in lines:
        name = _group_name(line)
        if name is not None:
            current = name
            group_found = group_found or name == group
        if name is None and current == group and _key_of(line) == key:
            if not seen:
                seen = True
                if value is not None:
                    out.append(f"{key}={value}" + (line[len(line.rstrip("\r\n")):] or eol))
            continue                                         # a second line of the same key: dropped
        out.append(line)
        if current == group and name is None and line.strip():
            last_in_group = len(out)
    if seen or value is None:
        return "".join(out)
    entry = f"{key}={value}{eol}"
    if group_found:
        at = last_in_group if last_in_group is not None else next(i + 1 for i, ln in enumerate(out) if _group_name(ln) == group)
        if at and not out[at - 1].endswith(("\n", "\r")):
            out[at - 1] += eol
        out.insert(at, entry)
        return "".join(out)
    if out and not out[-1].endswith(("\n", "\r")):
        out[-1] += eol
    if out and out[-1].strip():
        out.append(eol)
    out += [group + eol, entry]
    return "".join(out)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def folder_default_value(app_id: str, fallback: tuple = ()) -> str:
    """The value to write: Dossier first, then the programs that were the default before (so closing or removing Dossier leaves a
    working folder program)."""
    ids = [app_id] + [i for i in fallback if i != app_id]
    return ";".join(ids) + ";"


def folder_default(config: str) -> Optional[str]:
    """What the user's own ``mimeapps.list`` says for ``inode/directory`` (the raw value), or None when it says nothing."""
    return get_key(_read(mimeapps_path(config)), DEFAULT_GROUP, FOLDER_TYPE)


def set_folder_default(config: str, app_id: str = APP_ID, fallback: tuple = ()) -> Optional[str]:
    """Make ``app_id`` the default for folders in the user's own ``mimeapps.list``. Returns what the key said before (None when it
    was not there), which the caller keeps for ``restore_folder_default``. Calling it again while Dossier is already first returns
    that earlier value unchanged, so the way back is not lost."""
    path = mimeapps_path(config)
    text = _read(path)
    before = get_key(text, DEFAULT_GROUP, FOLDER_TYPE)
    ids = [i.strip() for i in (before or "").split(";") if i.strip()]
    if ids and ids[0] == app_id:                             # already first: what it kept after itself is the earlier value
        rest = ids[1:]
        return ";".join(rest) + ";" if rest else None
    value = folder_default_value(app_id, tuple(ids) or tuple(fallback))
    write_atomically(path, set_key(text, DEFAULT_GROUP, FOLDER_TYPE, value).encode("utf-8"))
    return before


def restore_folder_default(config: str, before: Optional[str], app_id: str = APP_ID) -> bool:
    """Put the key back as it was (``before`` None: remove it). Only when it still names Dossier first: if the user chose another
    program meanwhile, that choice is left alone. True when the file was changed."""
    path = mimeapps_path(config)
    text = _read(path)
    now = get_key(text, DEFAULT_GROUP, FOLDER_TYPE)
    if now is None or now.split(";")[0].strip() != app_id:
        return False
    write_atomically(path, set_key(text, DEFAULT_GROUP, FOLDER_TYPE, before).encode("utf-8"))
    return True


def desktop_mimeapps_paths(config: str, desktops: tuple) -> list:
    """The desktop's own files in the user's config folder (``gnome-mimeapps.list``, ``kde-mimeapps.list``), in the order the
    standard reads them; they come before ``mimeapps.list``, so a folder program named there wins."""
    out: list = []
    for d in desktops:
        path = os.path.join(config, f"{d.lower()}-mimeapps.list")
        if path not in out:
            out.append(path)
    return out


def set_desktop_folder_defaults(config: str, desktops: tuple, app_id: str = APP_ID) -> dict:
    """Question 72A: also put Dossier first in the desktop's own file, but only where that file already names a folder program
    (a file that says nothing for folders is not created or touched). Returns {path: what the key said before}, only for the files
    changed, which the caller keeps for ``restore_desktop_folder_defaults``."""
    changed: dict = {}
    for path in desktop_mimeapps_paths(config, desktops):
        text = _read(path)
        before = get_key(text, DEFAULT_GROUP, FOLDER_TYPE)
        ids = [i.strip() for i in (before or "").split(";") if i.strip()]
        if not ids or ids[0] == app_id:
            continue
        write_atomically(path, set_key(text, DEFAULT_GROUP, FOLDER_TYPE, folder_default_value(app_id, tuple(ids))).encode("utf-8"))
        changed[path] = before
    return changed


def restore_desktop_folder_defaults(befores: dict, app_id: str = APP_ID) -> int:
    """Put back exactly what each desktop file said before, where it still names Dossier first (a program chosen since is left
    alone). Returns how many files were changed back."""
    count = 0
    for path, before in befores.items():
        text = _read(path)
        now = get_key(text, DEFAULT_GROUP, FOLDER_TYPE)
        if now is None or now.split(";")[0].strip() != app_id:
            continue
        write_atomically(path, set_key(text, DEFAULT_GROUP, FOLDER_TYPE, before).encode("utf-8"))
        count += 1
    return count


def is_folder_default(config: str, app_id: str = APP_ID) -> bool:
    now = folder_default(config)
    return now is not None and now.split(";")[0].strip() == app_id


# what is asked on the command line ----------------------------------------------------------------------------------------------
def folders_from_arguments(args: list, isdir=os.path.isdir, isfile=os.path.isfile) -> list:
    """The folders a launcher passed (``dossier ~/Music``, ``dossier file:///home/a/Music``, ``dossier notes.txt`` meaning its
    folder): at most two, the first for the left panel. Options and what does not exist are skipped."""
    from urllib.parse import unquote, urlparse
    out: list = []
    for arg in args:
        if not arg or arg.startswith("-"):
            continue
        if arg.startswith("file://"):
            arg = unquote(urlparse(arg).path)
        path = os.path.abspath(arg)
        if isfile(path):
            path = os.path.dirname(path)
        if isdir(path) and path not in out:
            out.append(path)
    return out[:2]
