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
                out.append(Node(n.name, "", kept))
        elif needle in n.name.casefold():
            out.append(n)
    return out
