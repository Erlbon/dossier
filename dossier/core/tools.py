"""The tools bar: programs the user keeps one click away, like bookmarks, and folders of them.

A tool is a name, a program, the arguments to give it and an optional folder to start in. The arguments can name what the program is
to work on: ``{files}`` (every marked item, or the one under the cursor), ``{file}`` (the first of them), ``{name}`` (its name),
``{dir}`` (the folder of the active panel) and ``{other}`` (the folder of the other panel). The text is cut into words first and the
values are put in afterwards, each as one argument, so a name with spaces or quotes can never become a second argument or a command.
Nothing here starts a shell; the program is started directly.

The bar is a list of tools, folders (which hold more of the same, a few levels deep) and separators, stored as JSON in the settings.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

MAX_DEPTH = 4
MAX_ITEMS = 500
PLACEHOLDERS = (("{files}", "every marked item, or the one under the cursor (as separate arguments)"),
                ("{file}", "the first of them"), ("{name}", "the name of the first"),
                ("{dir}", "the folder of this panel"), ("{other}", "the folder of the other panel"))


@dataclass
class Tool:
    name: str
    command: str
    args: str = ""
    start_in: str = ""                       # empty: the folder of the active panel

    kind = "tool"


@dataclass
class Folder:
    name: str
    items: list = field(default_factory=list)

    kind = "folder"


@dataclass
class Separator:
    name: str = ""

    kind = "separator"


class BadTool(ValueError):
    """The tool cannot be saved or run as written."""


# the stored form -------------------------------------------------------------------------------------------------------
def to_data(items: list) -> list:
    out = []
    for it in items:
        if isinstance(it, Tool):
            out.append({"type": "tool", "name": it.name, "command": it.command, "args": it.args, "start_in": it.start_in})
        elif isinstance(it, Folder):
            out.append({"type": "folder", "name": it.name, "items": to_data(it.items)})
        else:
            out.append({"type": "separator"})
    return out


def from_data(data, depth: int = 0, budget: Optional[list] = None) -> list:
    """The items of stored data; anything damaged or too deep is left out, never an error."""
    budget = budget if budget is not None else [MAX_ITEMS]
    out: list = []
    if not isinstance(data, list) or depth > MAX_DEPTH:
        return out
    for d in data:
        if budget[0] <= 0 or not isinstance(d, dict):
            continue
        budget[0] -= 1
        kind = d.get("type")
        name = str(d.get("name", ""))[:80]
        if kind == "tool" and name.strip() and str(d.get("command", "")).strip():
            out.append(Tool(name.strip(), str(d["command"]).strip(), str(d.get("args", "")), str(d.get("start_in", ""))))
        elif kind == "folder" and name.strip():
            out.append(Folder(name.strip(), from_data(d.get("items"), depth + 1, budget)))
        elif kind == "separator":
            out.append(Separator())
    return out


def dumps(items: list) -> str:
    return json.dumps(to_data(items), ensure_ascii=False, separators=(",", ":"))


def loads(text) -> list:
    try:
        return from_data(json.loads(text)) if text else []
    except (TypeError, ValueError):
        return []


def walk(items: list, path: tuple = ()):
    """Every item with its position: ``(path of indexes, item)``, folders before what is inside them."""
    for i, it in enumerate(items):
        yield path + (i,), it
        if isinstance(it, Folder):
            yield from walk(it.items, path + (i,))


def container(items: list, path: tuple) -> list:
    """The list that holds the item at ``path`` (the top list for a path of one)."""
    here = items
    for i in path[:-1]:
        here = here[i].items
    return here


def places(items: list) -> list:
    """``[(label, list that a new item goes into)]``: the bar itself, then every folder as ``A / B``."""
    out = [("(the bar itself)", items)]

    def go(lst: list, prefix: str) -> None:
        for it in lst:
            if isinstance(it, Folder):
                label = prefix + it.name
                out.append((label, it.items))
                go(it.items, label + " / ")
    go(items, "")
    return out


# the arguments ---------------------------------------------------------------------------------------------------------
def split_words(text: str) -> list:
    """Cut an argument line into words: spaces separate, double quotes keep spaces together (and are dropped)."""
    words, cur, quoted, started = [], [], False, False
    for ch in text:
        if ch == '"':
            quoted = not quoted
            started = True
        elif ch.isspace() and not quoted:
            if started:
                words.append("".join(cur))
                cur, started = [], False
        else:
            cur.append(ch)
            started = True
    if quoted:
        raise BadTool("a quote is opened and never closed")
    if started:
        words.append("".join(cur))
    return words


def check_args(text: str) -> None:
    """Raise ``BadTool`` for an argument line that cannot work."""
    for w in split_words(text):
        if "{files}" in w and w != "{files}":
            raise BadTool("{files} must stand alone as a word of its own, for example:  --open {files}")
        for open_at in range(len(w)):
            if w[open_at] == "{" and not any(w.startswith(p, open_at) for p, _why in PLACEHOLDERS):
                raise BadTool(f"unknown placeholder near {w[open_at:open_at + 8]}: use {{files}} {{file}} {{name}} {{dir}} {{other}}")


def expand(args: str, files: list, folder: str, other: str, basename: Callable = os.path.basename) -> list:
    """The argument list for a launch."""
    check_args(args)
    first = files[0] if files else ""
    one = {"{file}": first, "{name}": basename(first.rstrip("/" + chr(92))) if first else "", "{dir}": folder, "{other}": other}
    out: list = []
    for w in split_words(args):
        if w == "{files}":
            out.extend(files)
            continue
        for key, value in one.items():
            w = w.replace(key, value)
        out.append(w)
    return out


# starting ---------------------------------------------------------------------------------------------------------------
def launch(tool: Tool, files: list, folder: str, other: str, starter: Optional[Callable] = None) -> list:
    """Start the program of ``tool`` for ``files``; returns the argument list used. The program is started on its own, not waited
    for. On Windows the system starts it (so a shortcut, a script, or a program that asks for administrator rights works)."""
    argv = expand(tool.args, files, folder, other)
    cwd = tool.start_in or (folder if folder and os.path.isdir(folder) else None)
    if starter is not None:
        starter(tool.command, argv, cwd)
        return argv
    if sys.platform == "win32":
        os.startfile(tool.command, arguments=subprocess.list2cmdline(argv), cwd=cwd)          # noqa: S606 -- the user's own tool
    else:
        subprocess.Popen([tool.command, *argv], cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL)
    return argv


# what could be offered ---------------------------------------------------------------------------------------------------
SUGGESTED = (
    ("7-Zip File Manager", r"C:\Program Files\7-Zip\7zFM.exe", ""),
    ("File Locksmith (who has this file open)", r"C:\Program Files\PowerToys\WinUI3Apps\PowerToys.FileLocksmithUI.exe", "{files}"),
    ("PowerRename", r"C:\Program Files\PowerToys\PowerToys.PowerRename.exe", "{files}"),
    ("Windows Terminal", r"C:\Program Files\WindowsApps\Microsoft.WindowsTerminal_*\wt.exe", ""),
    ("Notepad", r"C:\Windows\System32\notepad.exe", "{file}"),
    ("Calculator", r"C:\Windows\System32\calc.exe", ""),
)


def suggestions(exists: Callable = os.path.isfile) -> list:
    """Programs that are installed here and make a good start: ``[Tool]``. Looks at a few known places on the disk, so the window
    calls it on a thread."""
    found = []
    for name, path, args in SUGGESTED:
        if "*" in path:
            continue
        if exists(path):
            found.append(Tool(name, path, args))
    return found
