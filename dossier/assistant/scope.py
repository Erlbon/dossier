"""Which paths an assistant may name: only inside the folders the owner listed. Every path is resolved first (``..`` and links included), so a
name that leads out of a listed folder by any route is refused."""
from __future__ import annotations

import os

from ..core.platform import is_full_path


class Denied(Exception):
    """A request the owner's settings do not allow. The text says why, in words the assistant can pass on."""


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _text_key(path: str) -> str:
    """The path as text only (``abspath`` and ``normpath`` never touch the disk or the network)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _under(key: str, root: str) -> bool:
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


def _server_under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


class Scope:
    def __init__(self, roots: list) -> None:
        from .config import server_root
        self.server_roots = [server_root(r) for r in roots if r and server_root(r)]
        self.roots = [os.path.normpath(r) for r in roots if r and not server_root(r) and "://" not in r]
        self._keys = [_key(r) for r in self.roots]
        self._texts = [_text_key(r) for r in self.roots] + self._keys     # where a listed folder is, by name and for real

    def _resolve_server(self, path: str) -> str:
        """A server path is checked by its text alone (``..`` refused, the rest normalised): links on the server are the server's."""
        from .config import server_root
        clean = server_root(path)
        if not clean:
            raise Denied(f"only folders on this computer, or on the SFTP and SCP servers the owner listed, can be used: {path}")
        for root in self.server_roots:
            if _server_under(clean, root):
                return clean
        raise Denied(f"outside the folders the owner allows: {path}")

    def resolve(self, path) -> str:
        """The real path for ``path``, or ``Denied``. Relative paths are refused (an assistant has no current folder)."""
        if not isinstance(path, str) or not path.strip():
            raise Denied("a path is needed")
        if "\x00" in path:
            raise Denied("that is not a path")
        if "://" in path:
            if not self.server_roots:
                raise Denied("only folders and files on this computer can be used (not archives or servers)")
            return self._resolve_server(path)
        if not is_full_path(path):
            raise Denied(f"use a full path (starting with a drive letter or a slash, or sftp:// for a listed server): {path}")
        if not self._keys:
            if self.server_roots:
                raise Denied(f"outside the folders the owner allows: {path}")
            raise Denied("the owner has not listed any folder the assistant may use (Settings > Assistant Access in Dossier)")
        # First by its name alone: resolving a path opens it, and for a network path (two backslashes, a host, a share) that is a network login that hands the owner's
        # Windows sign-in (an NTLM hash) to whatever host the assistant named, even though the path is refused afterwards.
        if not any(_under(_text_key(path), root) for root in self._texts):
            raise Denied(f"outside the folders the owner allows: {path}")
        real = os.path.realpath(path)
        key = os.path.normcase(real)
        for root in self._keys:
            if _under(key, root):
                return real
        raise Denied(f"outside the folders the owner allows: {path}")

    def contains(self, path: str) -> bool:
        try:
            self.resolve(path)
            return True
        except Denied:
            return False

    def all(self, paths) -> list:
        return [self.resolve(p) for p in paths]
