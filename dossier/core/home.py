"""The Home page: the root of every panel (``home://``), listing where things are kept.

Sections, in this order: local drives, places (the user's folders and cloud sync folders), pinned folders
(the user's own shortcuts) and network (drives that are mapped or mounted, saved network locations, and an
entry that adds one). Servers (SFTP, WebDAV, FTP) join as another section when their file systems exist
(docs/home-and-servers-review.md). Nothing here touches the network and nothing is probed: drives come from the
operating system's own list, folders are checked with a plain ``exists``, so the page opens at once.

The listing is a plain folder of entries (``kind`` says what each one is), so panels, tabs, the selection
and the drive menu treat it like any other place; opening an entry goes to its real path.
"""
from __future__ import annotations

import errno
import os
from dataclasses import dataclass, replace as dc_replace
from typing import Callable, Optional

from .drive_identity import DriveMemory
from .lights import LIT_KINDS, OK, UNCHECKED, LightBoard, describe
from .platform import home_dir, list_volumes
from .vfs import Entry, FileSystem, NotWritable
from .listings import FlatFileSystem, FoundFileSystem
from .sftpfs import SftpFileSystem
from .zipfs import ZipFileSystem

HOME_URL = "home://"
HEADER_PREFIX = "home://#"
ADD_NETWORK = HEADER_PREFIX + "add-network"
ADD_SERVER = HEADER_PREFIX + "add-server"
TYPE_NAMES = {"fixed": "Local disk", "removable": "Removable disk", "optical": "Optical disc", "other": "Disk",
              "network": "Network drive", "place": "Folder", "pin": "Pinned folder", "netloc": "Network location", "server": "Server",
              "action": "", "header": ""}
SECTIONS = ("drives", "places", "pins", "network", "servers")
SECTION_TITLES = {"drives": "Local drives", "places": "Places", "pins": "Pinned folders", "network": "Network", "servers": "Servers"}

# the user's folders, by their usual name under the home folder
KNOWN_FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")


def is_home(path: str) -> bool:
    return path.rstrip("/") == "home:"


@dataclass
class ServerItem:
    """A saved server as the Home page shows it (the window makes these from its saved connections)."""
    name: str
    path: str                  # sftp://user@host/ : where it opens once connected
    detail: str
    connected: bool = False


@dataclass
class HomeProvider:
    """Where the Home page gets its facts. Every one can be replaced, so the page is testable without a disk."""

    volumes: Callable[[], list] = list_volumes
    home: Callable[[], str] = home_dir
    exists: Callable[[str], bool] = os.path.isdir
    environ: Optional[dict] = None
    pins: Callable[[], list] = lambda: []
    network: Callable[[], list] = lambda: []
    servers: Callable[[], list] = lambda: []      # ServerItem objects: the saved servers (nothing is contacted to list them)
    board: LightBoard = None                      # what the panels found out about places (set in __post_init__)
    memory: DriveMemory = None                    # which drive each letter held

    def __post_init__(self) -> None:
        self.board = self.board or LightBoard()
        self.memory = self.memory or DriveMemory()

    def env(self, name: str) -> str:
        return (self.environ if self.environ is not None else os.environ).get(name, "")


USER_FOLDER_NOTE = "Your user folder"


def user_folder_name(home: str) -> str:
    """How the user's own folder is called in lists: ``erlbon (your folder)``. The word Home belongs to the Home page."""
    return f"{os.path.basename(home.rstrip('/' + chr(92))) or 'Home'} (your folder)"


def place_folders(p: HomeProvider) -> list:
    """``(title, path)`` of the user's own folders that exist, then the cloud sync folders that exist."""
    home = p.home()
    out = [(user_folder_name(home), home)]
    out += [(name, os.path.join(home, name)) for name in KNOWN_FOLDERS]
    for title, path in (("OneDrive", p.env("OneDrive") or p.env("OneDriveConsumer") or os.path.join(home, "OneDrive")),
                        ("Dropbox", os.path.join(home, "Dropbox")),
                        ("Google Drive", os.path.join(home, "Google Drive"))):
        out.append((title, path))
    seen, result = set(), []
    for title, path in out:
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen and p.exists(path):
            seen.add(key)
            result.append((title, path))
    return result


def _header(section: str) -> Entry:
    return Entry(name=SECTION_TITLES[section], path=HEADER_PREFIX + section, is_dir=False, kind="header")


def _lit(p: HomeProvider, entry: Entry) -> Entry:
    """Give an entry its light: what the panels already learned about it, else grey (not checked). No I/O."""
    if entry.kind not in LIT_KINDS:
        return entry
    found = p.board.get(entry.path)
    status, note = found if found else (UNCHECKED, "")
    return dc_replace(entry, status=status, note=describe(status, note))


def build_entries(p: HomeProvider) -> list:
    """The Home page as a list of entries, headers included. Free space is left empty here: it needs the disks
    and is filled in afterwards, in the background, so a dead drive cannot hold the page up."""
    volumes = p.volumes()
    entries: list = [_header("drives")]
    network_volumes = [v for v in volumes if v[2] == "network"]
    for root, label, kind in volumes:
        if kind == "network":
            continue
        name = root.rstrip("\\/") if os.sep == "\\" else root
        entries.append(_lit(p, Entry(name=f"{name}  {label}".strip() if label else name, path=root, is_dir=True, kind=kind)))
    entries.append(_header("places"))
    for title, path in place_folders(p):
        entries.append(Entry(name=title, path=path, is_dir=True, kind="place", detail=path,
                             note=USER_FOLDER_NOTE if title == user_folder_name(p.home()) else ""))
    pins = [x for x in p.pins() if x]
    if pins:
        entries.append(_header("pins"))
        for path in pins:
            entries.append(Entry(name=os.path.basename(path.rstrip("\\/")) or path, path=path, is_dir=True, kind="pin",
                                 detail=path if p.exists(path) else f"{path}  (not found)"))
    entries.append(_header("network"))
    for root, label, _kind in network_volumes:
        name = root.rstrip("\\/") if os.sep == "\\" else root
        entries.append(_lit(p, Entry(name=name, path=root, is_dir=True, kind="network", detail=label)))
    for address in p.network():
        entries.append(_lit(p, Entry(name=address, path=address, is_dir=True, kind="netloc", detail="Saved network location")))
    entries.append(Entry(name="Add a network share...", path=ADD_NETWORK, is_dir=False, kind="action"))
    entries.append(_header("servers"))
    for item in p.servers():
        entries.append(Entry(name=item.name, path=item.path, is_dir=True, kind="server", detail=item.detail,
                             status=OK if item.connected else UNCHECKED,
                             note="Connected" if item.connected else "Not connected: nothing is contacted until you open it"))
    entries.append(Entry(name="Add a server...", path=ADD_SERVER, is_dir=False, kind="action"))
    return entries


def is_shortcut_kind(kind: str) -> bool:
    """Entries that open a folder (as against headers and actions)."""
    return kind in ("fixed", "removable", "optical", "other", "network", "place", "pin", "netloc", "server")


def removable_from_home(kind: str) -> bool:
    """Only the user's own shortcuts can be taken off the page."""
    return kind in ("pin", "netloc")


class HomeFileSystem(FileSystem):
    """``home://`` as a read-only file system with one folder."""

    scheme = "home"
    writable = False

    def __init__(self, provider: HomeProvider) -> None:
        self.provider = provider

    def list(self, path: str) -> list:
        if not is_home(path):
            raise FileNotFoundError(path)
        return build_entries(self.provider)

    def stat(self, path: str) -> Entry:
        if not is_home(path):
            raise FileNotFoundError(path)
        return Entry(name="Home", path=HOME_URL, is_dir=True, kind="header")

    def open_read(self, path: str):
        raise NotWritable("the Home page has no files")


class RouterFileSystem(FileSystem):
    """One file system made of several: ``home://`` goes to the Home page, every other path to the local disk
    (later ``sftp://`` and the like to their own systems). Panels and operations are given the router and never
    need to know which system holds a path."""

    writable = True

    def __init__(self, local: FileSystem, home: HomeFileSystem) -> None:
        self.local = local
        self.home = home
        self.zip = ZipFileSystem()
        self.sftp = SftpFileSystem()                  # sftp://user@host/path: servers, once connected
        self.scp = SftpFileSystem("scp")              # scp://user@host/path: servers reached through a shell
        self.dav = SftpFileSystem("webdav")           # webdav://user@host/path: WebDAV servers
        self.ftp = SftpFileSystem("ftp")              # ftp://user@host/path: FTP and FTPS servers
        self.opds = SftpFileSystem("opds")            # opds://user@host/path: OPDS book catalogues (read-only)
        self.subsonic = SftpFileSystem("subsonic")    # subsonic://user@host/path: Subsonic music servers (read-only)
        self.flat = FlatFileSystem(self)              # flat://<folder>: every file below a folder, as one list
        self.found = FoundFileSystem(self)            # found://<n>: the result list of a search
        self.sep = local.sep
        self.case_sensitive = local.case_sensitive

    def fs_for(self, path: str) -> FileSystem:
        if path.startswith("home:"):
            return self.home
        if path.startswith("zip:"):
            return self.zip
        if path.startswith("sftp:"):
            return self.sftp
        if path.startswith("scp:"):
            return self.scp
        if path.startswith("webdav:"):
            return self.dav
        if path.startswith("ftp:"):
            return self.ftp
        if path.startswith("opds:"):
            return self.opds
        if path.startswith("subsonic:"):
            return self.subsonic
        if path.startswith("flat:"):
            return self.flat
        return self.found if path.startswith("found:") else self.local

    def is_writable(self, path: str) -> bool:
        return self.fs_for(path).is_writable(path)

    # path functions go to the system the path belongs to
    @property
    def root(self) -> str:
        return self.local.root

    def join(self, base: str, *parts: str) -> str:
        return self.fs_for(base).join(base, *parts)

    def basename(self, path: str) -> str:
        return self.fs_for(path).basename(path)

    def dirname(self, path: str) -> str:
        return self.fs_for(path).dirname(path)

    def is_root(self, path: str) -> bool:
        return self.fs_for(path).is_root(path)

    def parent(self, path: str) -> Optional[str]:
        return self.fs_for(path).parent(path)

    # the contract
    def list(self, path: str) -> list:
        return self.fs_for(path).list(path)

    def scan(self, path: str):
        return self.fs_for(path).scan(path)

    def stat(self, path: str) -> Entry:
        return self.fs_for(path).stat(path)

    def open_read(self, path: str):
        return self.fs_for(path).open_read(path)

    def mkdir(self, path: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        self.fs_for(path).mkdir(path, parents=parents, exist_ok=exist_ok)

    def rename(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        a, b = self.fs_for(src), self.fs_for(dst)
        if a is not b or (a is not self.local and src.partition("://")[2].split("/", 1)[0] != dst.partition("://")[2].split("/", 1)[0]):
            raise OSError(errno.EXDEV, "cannot rename from one file system or server to another")      # the caller copies and removes
        a.rename(src, dst, overwrite=overwrite)

    def remove(self, path: str) -> None:
        self.fs_for(path).remove(path)

    def open_write(self, path: str, *, exclusive: bool = False):
        return self.fs_for(path).open_write(path, exclusive=exclusive)

    def set_mtime(self, path: str, mtime: float) -> None:
        self.fs_for(path).set_mtime(path, mtime)
