"""SFTP servers as folders: ``sftp://user@host:port/path`` behind the common ``FileSystem`` interface.

Every window, viewer, search and copy command that works on a local folder works on these paths, because they only ever talk to the
interface. A server is a *session* (a live connection, made by ``sshlink.connect`` after the owner agreed to the host key and gave a
password); a path of a server that is not connected raises ``NotConnected`` (a ``ConnectionError``) and the window offers to connect.
A connection can be read-only (the default for a new one): then every write, rename and delete is refused here, whatever a command asks.

There is no recycle bin on a server: a delete is permanent, and ``is_remote`` tells the operations layer so that it can say so.
"""
from __future__ import annotations

import errno
import posixpath
import stat as stat_module
from dataclasses import dataclass
from typing import Optional

from .sftp_proto import SftpClient, SftpReadFile, SftpWriteFile
from .vfs import Entry, FileSystem, NotWritable

SCHEME = "sftp"
ROOT = "sftp://"


class NotConnected(ConnectionError):
    """The path belongs to a server there is no connection to (yet, or any more)."""

    def __init__(self, authority: str) -> None:
        super().__init__(f"not connected to {authority}")
        self.authority = authority


def split_path(path: str) -> tuple:
    """``(authority, remote path)`` of ``sftp://user@host:22/a/b``; the remote path always starts with ``/``."""
    rest = path[len(ROOT):] if path.startswith(ROOT) else path
    authority, slash, tail = rest.partition("/")
    return authority, posixpath.normpath("/" + tail) if tail.strip("/") else "/"


def make_path(authority: str, remote: str) -> str:
    return ROOT + authority + (remote if remote.startswith("/") else "/" + remote)


@dataclass
class Session:
    authority: str
    client: SftpClient
    read_only: bool = True
    base: str = ""                    # a prefix put before every remote path (a fixed folder the whole session lives in)
    home: str = "/"                   # where the server put us at login: where the connection opens

    def remote(self, remote_path: str) -> str:
        return (self.base.rstrip("/") + remote_path) if self.base else remote_path

    def local(self, remote_path: str) -> str:
        """The virtual path for a path the server gave back (the inverse of ``remote``)."""
        if self.base and remote_path.startswith(self.base.rstrip("/")):
            return remote_path[len(self.base.rstrip("/")):] or "/"
        return remote_path

    @property
    def alive(self) -> bool:
        return not self.client.closed


def _entry(session: Session, folder: str, name: str, attrs, size_of_link=None) -> Entry:
    is_link = attrs.is_link
    is_dir = attrs.is_dir
    path = make_path(session.authority, posixpath.join(folder, name))
    return Entry(name, path, is_dir, 0 if is_dir else attrs.size, float(attrs.mtime), is_link, attrs=attrs.perm & 0o7777,
                 atime=float(attrs.atime))


class SftpFileSystem(FileSystem):
    writable = True
    scheme = SCHEME
    sep = "/"
    case_sensitive = True
    is_remote = True                  # no recycle bin, slow, may drop: the operations layer asks

    def __init__(self) -> None:
        self.sessions: dict = {}

    # sessions -------------------------------------------------------------------------------------------------------------------------
    def add_session(self, session: Session) -> None:
        old = self.sessions.get(session.authority)
        self.sessions[session.authority] = session
        if old is not None and old is not session:
            old.client.close()

    def drop(self, authority: str) -> None:
        session = self.sessions.pop(authority, None)
        if session is not None:
            session.client.close()

    def connected(self, authority: str) -> bool:
        s = self.sessions.get(authority)
        return s is not None and s.alive

    def _session(self, path: str) -> tuple:
        authority, remote = split_path(path)
        session = self.sessions.get(authority)
        if session is None or not session.alive:
            raise NotConnected(authority)
        return session, remote

    def is_writable(self, path: str) -> bool:
        authority, _remote = split_path(path)
        session = self.sessions.get(authority)
        return session is not None and session.alive and not session.read_only

    def _need_write(self, path: str):
        session, remote = self._session(path)
        if session.read_only:
            raise NotWritable(path)
        return session, remote

    # path functions ---------------------------------------------------------------------------------------------------------------------
    @property
    def root(self) -> str:
        return ROOT

    def join(self, base: str, *parts: str) -> str:
        authority, remote = split_path(base)
        for part in parts:
            if part.strip("/"):
                remote = posixpath.join(remote, part.strip("/"))
        return make_path(authority, remote)

    def basename(self, path: str) -> str:
        authority, remote = split_path(path)
        return posixpath.basename(remote) or authority

    def dirname(self, path: str) -> str:
        authority, remote = split_path(path)
        return make_path(authority, posixpath.dirname(remote) or "/")

    def is_root(self, path: str) -> bool:
        return split_path(path)[1] == "/"

    def parent(self, path: str) -> Optional[str]:
        return None if self.is_root(path) else self.dirname(path)

    # the contract -----------------------------------------------------------------------------------------------------------------------
    def list(self, path: str) -> list:
        session, remote = self._session(path)
        names = session.client.listdir(session.remote(remote))
        out = []
        for n in names:
            entry = _entry(session, remote, n.name, n.attrs)
            if n.attrs.is_link:                              # a link to a folder is a folder to the person looking
                try:
                    target = session.client.stat(session.remote(posixpath.join(remote, n.name)))
                    entry = _entry(session, remote, n.name, target)
                    entry = Entry(entry.name, entry.path, entry.is_dir, entry.size, entry.mtime, True, attrs=entry.attrs, atime=entry.atime)
                except OSError:
                    pass                                      # a broken link stays a link
            out.append(entry)
        return out

    def stat(self, path: str) -> Entry:
        session, remote = self._session(path)
        attrs = session.client.stat(session.remote(remote))
        name = posixpath.basename(remote) or session.authority
        return _entry(session, posixpath.dirname(remote), name, attrs) if remote != "/" else \
            Entry(name, make_path(session.authority, "/"), True, 0, float(attrs.mtime), False, attrs=attrs.perm & 0o7777)

    def open_read(self, path: str):
        session, remote = self._session(path)
        attrs = session.client.stat(session.remote(remote))
        return SftpReadFile(session.client, session.remote(remote), attrs.size)

    def mkdir(self, path: str, *, parents: bool = False, exist_ok: bool = False) -> None:
        session, remote = self._need_write(path)
        if parents:
            chain, cur = [], remote
            while cur not in ("/", ""):
                chain.append(cur)
                cur = posixpath.dirname(cur)
            for part in reversed(chain):
                try:
                    session.client.mkdir(session.remote(part))
                except OSError:
                    if not self._is_dir(session, part):
                        raise
            return
        try:
            session.client.mkdir(session.remote(remote))
        except OSError:
            if exist_ok and self._is_dir(session, remote):
                return
            if self._exists(session, remote):
                raise FileExistsError(remote)
            raise

    @staticmethod
    def _exists(session: Session, remote: str) -> bool:
        try:
            session.client.stat(session.remote(remote))
            return True
        except OSError:
            return False

    @staticmethod
    def _is_dir(session: Session, remote: str) -> bool:
        try:
            return session.client.stat(session.remote(remote)).is_dir
        except OSError:
            return False

    def rename(self, src: str, dst: str, *, overwrite: bool = False) -> None:
        session, rsrc = self._need_write(src)
        session2, rdst = self._session(dst)
        if session2 is not session:
            raise OSError(errno.EXDEV, "a rename cannot go from one server to another")
        if not overwrite and self._exists(session, rdst):
            raise FileExistsError(dst)
        session.client.rename(session.remote(rsrc), session.remote(rdst), overwrite=overwrite)

    def remove(self, path: str) -> None:
        session, remote = self._need_write(path)
        attrs = session.client.stat(session.remote(remote), follow=False)
        if attrs.is_dir:
            session.client.rmdir(session.remote(remote))
        else:
            session.client.remove(session.remote(remote))

    def open_write(self, path: str, *, exclusive: bool = False):
        session, remote = self._need_write(path)
        return SftpWriteFile(session.client, session.remote(remote), exclusive)

    def set_mtime(self, path: str, mtime: float) -> None:
        session, remote = self._need_write(path)
        session.client.set_mtime(session.remote(remote), mtime)


def mode_text(perm: int) -> str:
    return stat_module.filemode(perm)[1:] if perm else ""
