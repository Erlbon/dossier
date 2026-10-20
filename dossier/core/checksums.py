"""Checksums of files, computed and compared on request. Nothing is ever written next to the files.

``hash_files`` reads each file once and feeds every wanted algorithm from the same read. ``match`` says which file (if
any) a pasted value belongs to; the algorithm is told from the length of the value.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .progress import CancelToken, check

ALGORITHMS = ("md5", "sha1", "sha256", "sha512")
LABELS = {"md5": "MD5", "sha1": "SHA-1", "sha256": "SHA-256", "sha512": "SHA-512"}
LENGTHS = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}      # hex digits -> algorithm
CHUNK = 1024 * 1024


@dataclass
class FileHash:
    path: str
    size: int = 0
    digests: dict = field(default_factory=dict)      # algorithm -> hex
    error: str = ""


def hash_file(fs, path: str, algorithms: Sequence[str] = ("sha256",), cancel: Optional[CancelToken] = None,
              on_bytes: Callable[[int], None] = lambda n: None) -> FileHash:
    result = FileHash(path)
    hashers = {a: hashlib.new(a) for a in algorithms}
    try:
        with fs.open_read(path) as f:
            while True:
                check(cancel)
                block = f.read(CHUNK)
                if not block:
                    break
                result.size += len(block)
                on_bytes(len(block))
                for h in hashers.values():
                    h.update(block)
    except OSError as e:
        result.error = e.strerror or str(e)
        return result
    result.digests = {a: h.hexdigest() for a, h in hashers.items()}
    return result


def hash_files(fs, paths: Sequence[str], algorithms: Sequence[str] = ("sha256",), cancel: Optional[CancelToken] = None,
               report: Callable[[int, int, str], None] = lambda done, total, name: None) -> list:
    """One FileHash per path, in order. A cancel (``Cancelled``) propagates; a file that cannot be read has ``error``."""
    out = []
    for i, p in enumerate(paths):
        report(i, len(paths), p)
        out.append(hash_file(fs, p, algorithms, cancel))
    report(len(paths), len(paths), "")
    return out


def clean_value(text: str) -> str:
    """A pasted checksum: spaces, a ``sha256:`` prefix, a trailing file name (``hash  name`` / ``hash *name``) are dropped."""
    text = (text or "").strip()
    m = re.search(r"\b([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|[0-9a-fA-F]{128})\b", text)
    return m.group(1).lower() if m else ""


def algorithm_of(value: str) -> str:
    return LENGTHS.get(len(value), "")


def match(value: str, hashes: Sequence[FileHash]) -> list:
    """The files whose checksum equals the pasted value (the algorithm follows from its length)."""
    value = clean_value(value)
    algo = algorithm_of(value)
    return [h for h in hashes if algo and h.digests.get(algo) == value]


def format_report(hashes: Sequence[FileHash], algorithm: str, name_of: Callable[[str], str]) -> str:
    """``hash *name`` lines, the format of sha256sum, md5sum and friends, for copying."""
    lines = []
    for h in hashes:
        if h.error:
            lines.append(f"# {name_of(h.path)}: could not be read ({h.error})")
        else:
            lines.append(f"{h.digests[algorithm]} *{name_of(h.path)}")
    return chr(10).join(lines)
