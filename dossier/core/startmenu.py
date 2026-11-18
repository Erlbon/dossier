"""The programs of the Windows Start menu, as a tree, for choosing what to put on the tools bar.

The Start menu is two folders of shortcuts (``.lnk``): the one for everybody (ProgramData) and the one for this user (AppData). Their
sub-folders are the groups the Start menu shows. A program is chosen by its shortcut: the system starts a shortcut like it starts a
program (with its own start folder and settings), so nothing has to be read out of it. Reading the folders touches the disk, so the
window calls ``scan`` on a thread.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

MAX_ITEMS = 5000
SKIP_PREFIXES = ("uninstall", "remove ")


@dataclass
class Node:
    name: str
    path: str = ""                                 # the shortcut (empty for a group)
    children: list = field(default_factory=list)
    args: str = ""                                 # what the program is given (a part of Windows: core/windows_parts.py)
    icon: str = ""                                 # the file holding its icon, "file,index" (empty: the program's own)

    @property
    def is_group(self) -> bool:
        return not self.path


def roots(environ: Optional[dict] = None) -> list:
    """The Start menu program folders that exist on this computer."""
    env = os.environ if environ is None else environ
    found = []
    for base in (env.get("ProgramData"), env.get("APPDATA")):
        if base:
            folder = os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")
            if os.path.isdir(folder):
                found.append(folder)
    return found


def _skip(name: str) -> bool:
    low = name.lower()
    return low.startswith(SKIP_PREFIXES)


def scan(folders: list, cancel: Optional[Callable] = None) -> list:
    """The programs under ``folders`` as a tree of ``Node``: groups first, then programs, each sorted by name; the same group in both
    Start menu folders is one group. Uninstallers are left out. At most ``MAX_ITEMS`` programs."""
    count = [0]

    def read(folder: str, into: dict) -> None:
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for name in names:
            if cancel is not None:
                cancel()
            full = os.path.join(folder, name)
            if os.path.isdir(full):
                node = into.setdefault(("g", name.lower()), Node(name))
                read(full, node.__dict__.setdefault("_index", {}))
            elif name.lower().endswith(".lnk") and not _skip(name) and count[0] < MAX_ITEMS:
                title = name[:-4]
                into.setdefault(("p", title.lower()), Node(title, full))
                count[0] += 1

    def build(index: dict) -> list:
        groups, programs = [], []
        for key in sorted(index, key=lambda k: (k[0] != "g", k[1])):
            node = index[key]
            if node.is_group:
                node.children = build(node.__dict__.get("_index", {}))
                if node.children:                       # an empty group is not shown
                    groups.append(node)
            else:
                programs.append(node)
        return groups + programs

    top: dict = {}
    for folder in folders:
        read(folder, top)
    return build(top)


def count_programs(nodes: list) -> int:
    return sum(1 if not n.is_group else count_programs(n.children) for n in nodes)


def filter_tree(nodes: list, text: str) -> list:
    """The part of the tree whose program names contain ``text`` (any case); groups are kept only when something below them matches."""
    needle = text.strip().casefold()
    if not needle:
        return nodes
    out = []
    for n in nodes:
        if n.is_group:
            kept = filter_tree(n.children, text)
            if kept:
                out.append(Node(n.name, "", kept, n.args, n.icon))
        elif needle in n.name.casefold():
            out.append(n)
    return out


# the Mac and Linux ------------------------------------------------------------------------------------------------------------
MAC_APP_SUFFIXES = (".app",)


def mac_app_folders(home: Optional[str] = None) -> list:
    """The Mac's folders of apps that exist: Applications, the system's own apps, and the user's own Applications."""
    home = home or os.path.expanduser("~")
    return [f for f in ("/Applications", "/System/Applications", os.path.join(home, "Applications")) if os.path.isdir(f)]


def scan_mac_apps(folders: list, cancel: Optional[Callable] = None) -> list:
    """The apps in the Mac's app folders as a tree of ``Node``: an app (``Mail.app``, a folder the Finder shows as one file) is a
    program, chosen by its own path; a plain folder such as Utilities is a group. The same group in two folders is one group."""
    count = [0]

    def read(folder: str, into: dict, depth: int) -> None:
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for name in names:
            if cancel is not None:
                cancel()
            full = os.path.join(folder, name)
            if name.lower().endswith(MAC_APP_SUFFIXES):
                if count[0] < MAX_ITEMS:
                    into.setdefault(("p", name[:-4].lower()), Node(name[:-4], full))
                    count[0] += 1
            elif depth < 2 and os.path.isdir(full) and not name.startswith("."):
                node = into.setdefault(("g", name.lower()), Node(name))
                read(full, node.__dict__.setdefault("_index", {}), depth + 1)

    def build(index: dict) -> list:
        groups, programs = [], []
        for key in sorted(index, key=lambda k: (k[0] != "g", k[1])):
            node = index[key]
            if node.is_group:
                node.children = build(node.__dict__.get("_index", {}))
                if node.children:
                    groups.append(node)
            else:
                programs.append(node)
        return groups + programs

    top: dict = {}
    for folder in folders:
        read(folder, top, 0)
    return build(top)


# the main category of a launcher, as the desktops' menus group them
CATEGORY_GROUPS = (("AudioVideo", "Sound and Video"), ("Audio", "Sound and Video"), ("Video", "Sound and Video"),
                   ("Development", "Programming"), ("Education", "Education"), ("Game", "Games"), ("Graphics", "Graphics"),
                   ("Network", "Internet"), ("Office", "Office"), ("Science", "Science"), ("Settings", "Settings"),
                   ("System", "System"), ("Utility", "Accessories"))


def scan_launchers(programs: list) -> list:
    """The desktop's menu programs (``desktop_entries.Desktop.menu_programs``) as a tree grouped as its menu groups them, each
    chosen by its launcher file: Dossier starts a launcher as the desktop does (its own command, its own terminal setting)."""
    groups: dict = {}
    for app in programs[:MAX_ITEMS]:
        title = next((g for cat, g in CATEGORY_GROUPS if cat in app.categories), "Other")
        groups.setdefault(title, []).append(Node(app.name, app.path, icon=app.icon))
    return [Node(title, "", sorted(nodes, key=lambda n: n.name.casefold())) for title, nodes in sorted(groups.items())]


def program_tree(cancel: Optional[Callable] = None) -> list:
    """The programs installed here, as a tree to choose from: the Start menu on Windows, the apps on the Mac, the desktop's
    launchers on Linux. Touches the disk: call it on a thread."""
    from .platform import IS_MACOS, IS_WINDOWS
    if IS_WINDOWS:
        return scan(roots(), cancel)
    if IS_MACOS:
        return scan_mac_apps(mac_app_folders(), cancel)
    from .desktop_entries import Desktop
    return scan_launchers(Desktop.load(cancel=cancel).menu_programs())
