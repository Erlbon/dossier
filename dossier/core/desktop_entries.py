"""The Linux desktop's programs: launchers (``.desktop`` files), which program opens which type, and a file's type.

Three published freedesktop standards, read directly (no GLib, no D-Bus), so the same code serves a GNOME, KDE or Xfce desktop:
- **Desktop Entry:** a launcher is an ini-like file with a ``[Desktop Entry]`` group: its name (in the user's language when it has
  one), the command (``Exec``, with ``%f``/``%F``/``%u``/``%U`` for the files), its icon, the types it opens (``MimeType``), and
  whether it runs in a terminal. A launcher's id is its path below an ``applications`` folder, ``/`` turned into ``-``.
- **MIME Applications:** ``mimeapps.list`` in the config folders and in each ``applications`` folder names the default program of a
  type and adds or removes associations; the first file that says something about a type wins.
- **Shared MIME-info:** ``mime/globs2`` gives a type by a name's pattern (``*.txt`` is ``text/plain``) and ``mime/subclasses`` a
  type's parents (``text/x-python`` is a kind of ``text/plain``), so a text editor is offered for every kind of text.

Reading the folders touches the disk (a few hundred small files), so callers do it on a thread. Nothing here starts a program:
``exec_commands`` builds the argument lists, and the caller starts them.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

MAX_APPS = 5000
GROUP = "[Desktop Entry]"


@dataclass
class DesktopApp:
    id: str                                 # firefox.desktop, org.gnome.TextEditor.desktop, kde-okular.desktop
    path: str                               # the launcher file
    name: str
    exec: str = ""
    icon: str = ""                          # a theme icon name or a full path
    comment: str = ""
    mime_types: tuple = ()
    categories: tuple = ()
    terminal: bool = False
    no_display: bool = False                # not in menus, but still a program for its types
    hidden: bool = False                    # deleted by the user: as if it did not exist
    try_exec: str = ""
    only_show_in: tuple = ()
    not_show_in: tuple = ()
    kind: str = "Application"               # Application, Link or Directory
    url: str = ""                           # a Link's address

    def shown_in_menus(self, desktops: tuple = ()) -> bool:
        if self.hidden or self.no_display or self.kind != "Application":
            return False
        if self.only_show_in and not set(self.only_show_in) & set(desktops):
            return False
        return not set(self.not_show_in) & set(desktops)


def _language_keys(lang: str) -> list:
    """``Name[nb_NO]``, ``Name[nb]`` for LANG ``nb_NO.UTF-8``: the most precise first."""
    lang = (lang or "").split(".")[0].split("@")[0]
    if not lang or lang in ("C", "POSIX"):
        return []
    keys = [lang]
    if "_" in lang:
        keys.append(lang.split("_")[0])
    return keys


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        ch = value[i]
        if ch == chr(92) and i + 1 < len(value):
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r"}.get(value[i + 1], value[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _list(value: str) -> tuple:
    return tuple(p for p in (x.strip() for x in value.split(";")) if p)


def parse_entry(text: str, path: str = "", app_id: str = "", lang: Optional[str] = None) -> Optional[DesktopApp]:
    """The ``[Desktop Entry]`` group of a launcher, or None when the text has none. ``lang`` picks the localised name (default: the
    environment's ``LC_ALL``, ``LC_MESSAGES`` or ``LANG``)."""
    if lang is None:
        lang = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    values: dict = {}
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            inside = line == GROUP
            continue
        if inside and "=" in line:
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())
    if not values:
        return None

    def localised(key: str) -> str:
        for code in _language_keys(lang):
            if f"{key}[{code}]" in values:
                return _unescape(values[f"{key}[{code}]"])
        return _unescape(values.get(key, ""))

    yes = lambda key: values.get(key, "").lower() == "true"          # noqa: E731
    name = localised("Name") or os.path.splitext(os.path.basename(path))[0]
    return DesktopApp(id=app_id or os.path.basename(path), path=path, name=name, exec=values.get("Exec", ""),
                      icon=values.get("Icon", ""), comment=localised("Comment"), mime_types=_list(values.get("MimeType", "")),
                      categories=_list(values.get("Categories", "")), terminal=yes("Terminal"), no_display=yes("NoDisplay"),
                      hidden=yes("Hidden"), try_exec=values.get("TryExec", ""), only_show_in=_list(values.get("OnlyShowIn", "")),
                      not_show_in=_list(values.get("NotShowIn", "")), kind=values.get("Type", "Application"),
                      url=values.get("URL", ""))


def read_entry(path: str, lang: Optional[str] = None) -> Optional[DesktopApp]:
    """The launcher at ``path`` (any file ending in ``.desktop``), or None when it cannot be read or is not one."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(256 * 1024)
    except OSError:
        return None
    return parse_entry(text, path, os.path.basename(path), lang)


# where they are kept ------------------------------------------------------------------------------------------------------
def data_dirs(environ: Optional[dict] = None, home: Optional[str] = None) -> list:
    """The XDG data folders, the user's own first: ``~/.local/share``, then ``XDG_DATA_DIRS`` (``/usr/local/share:/usr/share``)."""
    env = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    first = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    rest = [d for d in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    out = []
    for d in [first, *rest]:
        if d not in out:
            out.append(d)
    return out


def config_dirs(environ: Optional[dict] = None, home: Optional[str] = None) -> list:
    env = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    first = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    rest = [d for d in (env.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    return [first, *[d for d in rest if d != first]]


def current_desktops(environ: Optional[dict] = None) -> tuple:
    env = os.environ if environ is None else environ
    return tuple(d for d in (env.get("XDG_CURRENT_DESKTOP") or "").split(":") if d)


def applications(dirs: list, cancel: Optional[Callable] = None, lang: Optional[str] = None) -> dict:
    """Every launcher below ``<dir>/applications`` for each data folder, by id; a launcher in an earlier folder hides one of the
    same id later (the user's own copy wins). Hidden ones are kept, so they can hide the system's copy, and left out by callers."""
    found: dict = {}
    for base in dirs:
        root = os.path.join(base, "applications")
        for folder, subdirs, files in os.walk(root):
            subdirs.sort()
            for name in sorted(files):
                if cancel is not None:
                    cancel()
                if not name.endswith(".desktop") or len(found) >= MAX_APPS:
                    continue
                full = os.path.join(folder, name)
                app_id = os.path.relpath(full, root).replace(os.sep, "-").replace("/", "-")
                if app_id in found:
                    continue
                app = read_entry(full, lang)
                if app is not None:
                    app.id = app_id
                    found[app_id] = app
    return found


# running one ----------------------------------------------------------------------------------------------------------------
class BadExec(ValueError):
    """The launcher's command line cannot be read."""


def split_exec(command: str) -> list:
    """The ``Exec`` line cut into words as the standard says: words split at spaces, a word in double quotes may hold spaces, and in
    there a backslash keeps ``"``, `` ` ``, ``$`` and a backslash as themselves."""
    words, word, quoted, started, i = [], [], False, False, 0
    while i < len(command):
        ch = command[i]
        if quoted:
            if ch == chr(92) and i + 1 < len(command) and command[i + 1] in '"`$' + chr(92):
                word.append(command[i + 1])
                i += 2
                continue
            if ch == '"':
                quoted = False
            else:
                word.append(ch)
        elif ch == '"':
            quoted, started = True, True
        elif ch in " \t":
            if word or started:
                words.append("".join(word))
            word, started = [], False
        else:
            word.append(ch)
        i += 1
    if quoted:
        raise BadExec(f"an unclosed quote in {command!r}")
    if word or started:
        words.append("".join(word))
    return words


def _as_uri(path: str) -> str:
    from urllib.parse import quote
    return path if "://" in path else "file://" + quote(os.path.abspath(path))


def exec_commands(app: DesktopApp, files: list) -> list:
    """The argument lists that open ``files`` with ``app``: one for all when its command takes a list (``%F``, ``%U``), else one per
    file (``%f``, ``%u``), or one with no files when it takes none. ``%i`` becomes the icon, ``%c`` the name, ``%k`` the launcher;
    the old codes (``%d``, ``%n``, ``%m``...) are dropped and ``%%`` is a percent sign."""
    words = split_exec(app.exec)
    if not words:
        raise BadExec(f"{app.id} has no command")
    codes = {w for w in words if w in ("%f", "%F", "%u", "%U")}
    many = "%F" in codes or "%U" in codes
    groups = [list(files)] if many or not codes or not files else [[f] for f in files]

    def build(group: list) -> list:
        argv = []
        for w in words:
            if w in ("%F", "%U"):
                argv += [_as_uri(f) if w == "%U" else f for f in group]
            elif w in ("%f", "%u"):
                if group:
                    argv.append(_as_uri(group[0]) if w == "%u" else group[0])
            elif w == "%i":
                if app.icon:
                    argv += ["--icon", app.icon]
            else:
                out, i = [], 0
                while i < len(w):
                    if w[i] == "%" and i + 1 < len(w):
                        code = w[i + 1]
                        out.append({"%": "%", "c": app.name, "k": app.path}.get(code, ""))
                        i += 2
                        continue
                    out.append(w[i])
                    i += 1
                if "".join(out) or not w.startswith("%"):
                    argv.append("".join(out))
        return argv

    return [build(g) for g in groups]


# which program opens which type -------------------------------------------------------------------------------------------
@dataclass
class Associations:
    default: dict = field(default_factory=dict)     # type -> [ids], the first that is installed wins
    added: dict = field(default_factory=dict)
    removed: dict = field(default_factory=dict)


def parse_mimeapps(texts: list) -> Associations:
    """``mimeapps.list`` files, the most important first: for each type the first file that names a default wins it; added and
    removed associations are gathered from all of them."""
    out = Associations()
    for text in texts:
        group = ""
        seen_default: set = set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                group = line
                continue
            if "=" not in line:
                continue
            mime, _, value = line.partition("=")
            mime, ids = mime.strip(), list(_list(value))
            if group == "[Default Applications]" and mime not in out.default:
                out.default[mime] = ids
                seen_default.add(mime)
            elif group == "[Default Applications]" and mime in seen_default:
                out.default[mime] += ids
            elif group == "[Added Associations]":
                out.added.setdefault(mime, [])
                out.added[mime] += [i for i in ids if i not in out.added[mime]]
            elif group == "[Removed Associations]":
                out.removed.setdefault(mime, [])
                out.removed[mime] += ids
    return out


def mimeapps_files(config: list, data: list, desktops: tuple = ()) -> list:
    """The ``mimeapps.list`` files in the order the standard reads them: for each config folder the desktop's own
    (``gnome-mimeapps.list``) before the plain one, then each data folder's ``applications/`` the same way."""
    out = []
    names = [f"{d.lower()}-mimeapps.list" for d in desktops] + ["mimeapps.list"]
    for base in config:
        out += [os.path.join(base, n) for n in names]
    for base in data:
        out += [os.path.join(base, "applications", n) for n in names]
    return out


def read_texts(paths: list) -> list:
    texts = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                texts.append(f.read())
        except OSError:
            continue
    return texts


def type_family(mime: str, parents: dict) -> list:
    """``mime`` and the types it is a kind of, nearest first: ``text/x-python``, ``text/plain``, ``application/octet-stream``."""
    out, todo = [], [mime]
    while todo:
        m = todo.pop(0)
        if m in out:
            continue
        out.append(m)
        todo += parents.get(m, [])
        if m.startswith("text/") and m != "text/plain":
            todo.append("text/plain")
    if mime != "inode/directory" and "application/octet-stream" not in out:
        out.append("application/octet-stream")
    return out


def apps_for_type(mime: str, apps: dict, assoc: Associations, parents: Optional[dict] = None) -> list:
    """The programs that open ``mime``, the default first: the defaults named for it (or a parent type), then added associations,
    then every program whose own list names the type, by name. Hidden programs and removed associations are left out; a program
    that is NoDisplay still counts (many viewers are)."""
    family = type_family(mime, parents or {})
    out: list = []

    def take(app_id: str, kind: str) -> None:
        app = apps.get(app_id)
        if app is None or app.hidden or app.kind != "Application" or not app.exec or app in out:
            return
        if any(app_id in assoc.removed.get(m, []) for m in family):
            return
        out.append(app)

    for m in family:
        for app_id in assoc.default.get(m, []):
            if apps.get(app_id) is not None:
                take(app_id, "default")
                break
        if out:
            break
    for m in family:
        for app_id in assoc.added.get(m, []):
            take(app_id, "added")
    own = sorted((a for a in apps.values() if set(a.mime_types) & set(family[:-1] if len(family) > 1 else family)),
                 key=lambda a: (family.index(next(m for m in family if m in a.mime_types)), a.name.casefold()))
    for app in own:
        take(app.id, "own")
    return out


# a file's type ---------------------------------------------------------------------------------------------------------------
def parse_globs2(text: str) -> list:
    """``(weight, type, pattern, case_sensitive)`` from ``mime/globs2``, the heaviest first."""
    out = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        flags = parts[3] if len(parts) > 3 else ""
        out.append((int(parts[0]), parts[1], parts[2], "cs" in flags.split(",")))
    out.sort(key=lambda g: (-g[0], -len(g[2])))
    return out


def parse_subclasses(text: str) -> dict:
    parents: dict = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            parents.setdefault(parts[0], []).append(parts[1])
    return parents


def type_of(name: str, is_dir: bool, globs: list) -> str:
    """The type of a file by its name: a folder is ``inode/directory``; otherwise the heaviest pattern that fits (the longest of
    equal weight), else Python's own table, else ``application/octet-stream``."""
    if is_dir:
        return "inode/directory"
    low = name.lower()
    for _w, mime, pattern, case in globs:
        if fnmatch.fnmatchcase(name if case else low, pattern if case else pattern.lower()):
            return mime
    import mimetypes
    guessed = mimetypes.guess_type(name, strict=False)[0]
    return guessed or "application/octet-stream"


@dataclass
class MimeDatabase:
    """The shared MIME-info of every data folder, read once."""
    globs: list = field(default_factory=list)
    parents: dict = field(default_factory=dict)

    @classmethod
    def load(cls, dirs: list) -> "MimeDatabase":
        globs, parents = [], {}
        for base in reversed(dirs):                         # the user's own last, so it adds to the system's
            for text in read_texts([os.path.join(base, "mime", "globs2")]):
                globs += parse_globs2(text)
            for text in read_texts([os.path.join(base, "mime", "subclasses")]):
                for k, v in parse_subclasses(text).items():
                    parents.setdefault(k, [])
                    parents[k] += [p for p in v if p not in parents[k]]
        globs.sort(key=lambda g: (-g[0], -len(g[2])))
        return cls(globs, parents)

    def type_of(self, name: str, is_dir: bool = False) -> str:
        return type_of(name, is_dir, self.globs)


@dataclass
class Desktop:
    """Everything the Linux desktop says about programs, read once on a thread: the launchers, the associations and the type table."""
    apps: dict
    associations: Associations
    mime: MimeDatabase
    desktops: tuple = ()

    @classmethod
    def load(cls, environ: Optional[dict] = None, home: Optional[str] = None, cancel: Optional[Callable] = None) -> "Desktop":
        data, config = data_dirs(environ, home), config_dirs(environ, home)
        desktops = current_desktops(environ)
        return cls(applications(data, cancel), parse_mimeapps(read_texts(mimeapps_files(config, data, desktops))),
                   MimeDatabase.load(data), desktops)

    def programs_for(self, name: str, is_dir: bool = False) -> list:
        return apps_for_type(self.mime.type_of(name, is_dir), self.apps, self.associations, self.mime.parents)

    def menu_programs(self) -> list:
        """The programs a desktop's application menu shows, by name."""
        return sorted((a for a in self.apps.values() if a.shown_in_menus(self.desktops) and a.exec), key=lambda a: a.name.casefold())
