"""Dossier in Windows' "Open with" for pictures and text files (card 69C).

Windows lets no program make itself the default for a type: the user clicks "Always" himself (Settings > Default apps). What a program
can do is offer itself: a ProgID (a named way to open files) listed under each extension's ``OpenWithProgids``. That is all this does,
per user, under ``HKEY_CURRENT_USER\\Software\\Classes`` (no administrator rights), and it never touches the user's own choice
(``UserChoice``) or another program's entries. Taking it away deletes exactly what was written.

Two groups, each a switch: pictures (``dossier view``, the picture viewer alone) and text files (``dossier edit``, the notepad alone).
The installer's two ticks write the same keys (``installer/dossier.iss``; a test keeps the two lists equal), so the switches in
Settings > Opening Files show what the installer did.

Nothing here imports Qt, and the registry is reached through a writer object (``WinRegistry`` for real, a fake in the tests).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, Protocol

BS = chr(92)
CLASSES = BS.join(("Software", "Classes"))
APP_KEY = BS.join((CLASSES, "Applications", "dossier.exe"))
EXE_NAME = "dossier.exe"


def key_path(*parts: str) -> str:
    return BS.join(parts)


@dataclass(frozen=True)
class Group:
    key: str               # "picture" or "text"
    progid: str
    friendly: str          # the name Windows shows in Open with
    verb: str              # the command word: "view" or "edit"
    extensions: tuple
    label: str             # the switch in Settings


PICTURES = Group("picture", "Dossier.Picture", "Dossier Picture Viewer", "view",
                 (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".svg"),
                 "Offer Dossier's Picture Viewer in Open With")
TEXTS = Group("text", "Dossier.Text", "Dossier Notepad", "edit",
              (".txt", ".md", ".log", ".ini", ".cfg", ".json", ".xml", ".yaml", ".yml", ".csv"),
              "Offer Dossier's Notepad in Open With")
GROUPS = (PICTURES, TEXTS)


class Registry(Protocol):
    """What this module needs of the registry, all under HKEY_CURRENT_USER. A value of None is written as REG_NONE (an empty marker,
    as Windows itself writes OpenWithProgids). ``get_value`` returns None for a missing value, and "" for an empty one."""

    def set_value(self, path: str, name: str, value: Optional[str]) -> None: ...
    def get_value(self, path: str, name: str) -> Optional[str]: ...
    def delete_value(self, path: str, name: str) -> None: ...
    def delete_tree(self, path: str) -> None: ...
    def list_values(self, path: str) -> list: ...
    def notify_changed(self) -> None: ...


def exe_path(frozen: Optional[bool] = None, executable: Optional[str] = None) -> Optional[str]:
    """The program Windows should start: the running exe of the installed or one-file build. None when run from source, where there
    is no exe of Dossier's own to name (``python.exe -m dossier`` is not something to register)."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    return (executable or sys.executable) if frozen else None


def open_command(group: Group, exe: str) -> str:
    """The command Windows runs: the exe in quotes (a path with spaces), the verb, and the file in quotes."""
    return f'"{exe}" {group.verb} "%1"'


def _progid_key(group: Group) -> str:
    return key_path(CLASSES, group.progid)


def _command_key(group: Group) -> str:
    return key_path(_progid_key(group), "shell", "open", "command")


def _with_progids_key(extension: str) -> str:
    return key_path(CLASSES, extension, "OpenWithProgids")


def _supported_key() -> str:
    return key_path(APP_KEY, "SupportedTypes")


def enable(reg: Registry, group: Group, exe: str) -> None:
    """Offer Dossier for the group's extensions. Safe to run again (it rewrites the same values, so a moved exe is corrected)."""
    reg.set_value(_progid_key(group), "", group.friendly)
    reg.set_value(_progid_key(group), "FriendlyTypeName", group.friendly)
    reg.set_value(key_path(_progid_key(group), "DefaultIcon"), "", f'"{exe}",0')
    reg.set_value(_command_key(group), "", open_command(group, exe))
    reg.set_value(APP_KEY, "FriendlyAppName", "Dossier")
    reg.set_value(key_path(APP_KEY, "DefaultIcon"), "", f'"{exe}",0')
    reg.set_value(key_path(APP_KEY, "shell", "open", "command"), "", f'"{exe}" "%1"')
    for extension in group.extensions:
        reg.set_value(_with_progids_key(extension), group.progid, None)
        reg.set_value(_supported_key(), extension, None)
    reg.notify_changed()


def disable(reg: Registry, group: Group) -> None:
    """Take away exactly what ``enable`` wrote for the group: its ProgID, its entries in each extension's list, its supported types.
    The program's own key goes when no group is left. Another program's entries and the user's own choice are never touched."""
    for extension in group.extensions:
        reg.delete_value(_with_progids_key(extension), group.progid)
        reg.delete_value(_supported_key(), extension)
    reg.delete_tree(_progid_key(group))
    if not reg.list_values(_supported_key()):
        reg.delete_tree(APP_KEY)
    reg.notify_changed()


def is_enabled(reg: Registry, group: Group, exe: Optional[str] = None) -> bool:
    """Whether the group is on: its command is written, and (when ``exe`` is given) names this program, so a copy that has moved is
    shown as off until it is switched on again. This reads the registry, so call it on a thread."""
    command = reg.get_value(_command_key(group), "")
    if command is None:
        return False
    return exe is None or command == open_command(group, exe)


class WinRegistry:
    """The real registry (Windows only), under HKEY_CURRENT_USER."""

    def __init__(self) -> None:
        import winreg
        self._w = winreg

    def set_value(self, path: str, name: str, value: Optional[str]) -> None:
        w = self._w
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, path, 0, w.KEY_WRITE) as key:
            if value is None:
                w.SetValueEx(key, name, 0, w.REG_NONE, b"")
            else:
                w.SetValueEx(key, name, 0, w.REG_SZ, value)

    def get_value(self, path: str, name: str) -> Optional[str]:
        w = self._w
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_READ) as key:
                value, kind = w.QueryValueEx(key, name)
        except OSError:
            return None
        return value if isinstance(value, str) else ""

    def delete_value(self, path: str, name: str) -> None:
        w = self._w
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_SET_VALUE) as key:
                w.DeleteValue(key, name)
        except OSError:
            pass                                       # it was not there

    def delete_tree(self, path: str) -> None:
        w = self._w
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_READ | w.KEY_WRITE) as key:
                while True:
                    try:
                        child = w.EnumKey(key, 0)
                    except OSError:
                        break
                    self.delete_tree(path + BS + child)
            w.DeleteKey(w.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    def list_values(self, path: str) -> list:
        w = self._w
        names = []
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, path, 0, w.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        names.append(w.EnumValue(key, index)[0])
                    except OSError:
                        break
                    index += 1
        except OSError:
            pass
        return names

    def notify_changed(self) -> None:
        """Tell Explorer that file associations changed (SHCNE_ASSOCCHANGED), so Open with shows the change at once."""
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
