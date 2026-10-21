"""Which paths an assistant may name: only inside the folders the owner listed. Every path is resolved first (``..`` and links included), so a
name that leads out of a listed folder by any route is refused."""
from __future__ import annotations

import os


class Denied(Exception):
    """A request the owner's settings do not allow. The text says why, in words the assistant can pass on."""


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class Scope:
    def __init__(self, roots: list) -> None:
        self.roots = [os.path.normpath(r) for r in roots if r]
        self._keys = [_key(r) for r in self.roots]

    def resolve(self, path) -> str:
        """The real path for ``path``, or ``Denied``. Relative paths are refused (an assistant has no current folder)."""
        if not isinstance(path, str) or not path.strip():
            raise Denied("a path is needed")
        if "\x00" in path:
            raise Denied("that is not a path")
        if "://" in path:
            raise Denied("only folders and files on this computer can be used (not archives or servers)")
        if not os.path.isabs(path):
            raise Denied(f"use a full path (starting with a drive letter or a slash): {path}")
        if not self._keys:
            raise Denied("the owner has not listed any folder the assistant may use (Settings > Assistant Access in Dossier)")
        real = os.path.realpath(path)
        key = os.path.normcase(real)
        for root in self._keys:
            if key == root or key.startswith(root.rstrip(os.sep) + os.sep):
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
