"""A server that has a shell but no SFTP service (the ``scp`` kind of connection): files through a persistent ``ssh host sh``.

Some servers (old routers and NAS boxes, restricted accounts) offer only a command line over SSH. Dossier keeps one ``sh`` running over
the connection and sends it ordinary POSIX commands, each followed by a marker line that carries its exit status, so the end of every
answer is known exactly. Listing is ``ls -la``, a folder is made with ``mkdir``, a file is moved with ``mv``; the contents of a file are
read with ``dd`` (block by block, so any size and any starting point) and written as base64 text that the server decodes, which needs
nothing but the standard tools every such server has (``sh``, ``ls``, ``dd``, ``mkdir``, ``mv``, ``rm``, ``rmdir``, ``touch``,
``base64``).

The class offers the same calls as ``SftpClient`` (``listdir``, ``stat``, ``open``, ``read_blocks``...), so ``SftpFileSystem`` and
everything above it work on either kind of server unchanged. It is slower than SFTP (a command is a round trip and base64 is a third
larger): use SFTP when the server has it. Names go through the shell, so they are quoted with ``shlex.quote``; nothing a file is called
can become a command.
"""
from __future__ import annotations

import base64
import errno
import re
import secrets
import shlex
import threading
import time
from datetime import datetime, timezone
from typing import BinaryIO, Callable, Optional

from .sftp_proto import (CREAT_FLAG, EXCL_FLAG, FAILURE, NO_SUCH_FILE, PERMISSION_DENIED, S_IFDIR, S_IFLNK, S_IFREG, SftpError,
                         WRITE_FLAG, Attrs, Name, error_for)

BLOCK = 65536                         # dd's block size: reads start on a block boundary, so ``skip`` can seek
READ_BLOCKS = 16                      # blocks per read command (1 MB)
WRITE_BYTES = 48 * 1024               # bytes per write command (64 KB of base64)
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
LS_LINE = re.compile(r"^(?P<type>[-dlcbpsD])(?P<perm>[rwxsStTl-]{9})[+.@]?\s+\d+\s+(?:\S+\s+){1,2}?(?P<size>\d+)\s+"
                     r"(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<when>\d{1,2}:\d{2}|\d{4})\s+(?P<name>.+)$")
TYPE_BITS = {"-": S_IFREG, "d": S_IFDIR, "l": S_IFLNK}


def quote(path: str) -> str:
    return shlex.quote(path)


def perm_bits(text: str) -> int:
    """The permission bits of ``rwxr-xr-x`` (setuid, setgid and sticky letters count as their execute bit plus the special bit)."""
    value = 0
    for i, ch in enumerate(text):
        bit = 1 << (8 - i)
        if ch in "rwxst":                                 # s and t stand on an execute bit that is set
            value |= bit
        if ch in "sS":
            value |= 0o4000 if i == 2 else 0o2000
        if ch in "tT":
            value |= 0o1000
    return value


def parse_ls_line(line: str, now: float, utc_offset: int = 0) -> Optional[tuple]:
    """``(name, link target or "", Attrs)`` for one line of ``ls -la`` (None for a line that is not an entry). ``utc_offset`` is the
    server's offset from UTC in seconds: ``ls`` prints its local time."""
    m = LS_LINE.match(line.rstrip("\r\n"))
    if m is None:
        return None
    kind = m.group("type")
    if kind not in TYPE_BITS:
        return None                                       # devices, pipes, sockets: not files
    name, target = m.group("name"), ""
    if kind == "l" and " -> " in name:
        name, target = name.split(" -> ", 1)
    year_now = datetime.fromtimestamp(now, timezone.utc).year
    when = m.group("when")
    try:
        if ":" in when:
            hour, minute = (int(x) for x in when.split(":"))
            stamp = datetime(year_now, MONTHS[m.group("mon")], int(m.group("day")), hour, minute, tzinfo=timezone.utc)
            if stamp.timestamp() - utc_offset > now + 86400:                    # a recent date without a year is never in the future
                stamp = stamp.replace(year=year_now - 1)
        else:
            stamp = datetime(int(when), MONTHS[m.group("mon")], int(m.group("day")), tzinfo=timezone.utc)
        mtime = int(stamp.timestamp()) - utc_offset
    except (ValueError, KeyError):
        mtime = 0
    attrs = Attrs(size=int(m.group("size")), perm=TYPE_BITS[kind] | perm_bits(m.group("perm")), mtime=mtime, atime=mtime,
                  flags=1 | 4 | 8)
    return name, target, attrs


class ShellClient:
    """The calls of ``SftpClient`` on a POSIX shell. ``reader`` and ``writer`` are the streams of ``ssh host sh``."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO, close: Callable[[], None] = lambda: None) -> None:
        self._r, self._w, self._close = reader, writer, close
        self._lock = threading.RLock()
        self._buf = b""
        self.closed = False
        self.version = 0
        self.extensions: dict = {}
        self._handles: dict = {}
        self._next = 0
        self.utc_offset = 0
        out, status = self.run("echo dossier-ready", binary=False)
        if status != 0 or b"dossier-ready" not in out:
            raise ConnectionError("the server did not give a shell to work in")
        self.run("LC_ALL=C; export LC_ALL", binary=False)
        zone, status = self.run("date +%z 2>/dev/null", binary=False)
        text = zone.decode("ascii", "replace").strip()
        if status == 0 and re.fullmatch(r"[+-]\d{4}", text):
            self.utc_offset = (1 if text[0] == "+" else -1) * (int(text[1:3]) * 3600 + int(text[3:5]) * 60)

    # the wire -----------------------------------------------------------------------------------------------------------------------
    def _fail(self, why: str) -> None:
        self.closed = True
        raise ConnectionError(why)

    def run(self, command: str, *, binary: bool = True, timeout: float = 120.0) -> tuple:
        """Run one shell command; ``(its output, its exit status)``. The output is everything it wrote up to the marker line."""
        with self._lock:
            if self.closed:
                raise ConnectionError("the connection to the server was lost")
            mark = secrets.token_hex(8)
            tail = f"__DOSSIER_END_{mark}__".encode()
            line = f"{command}\nprintf '\\n__DOSSIER_END_{mark}__%d__\\n' $?\n"
            try:
                self._w.write(line.encode("utf-8", "surrogateescape"))
                self._w.flush()
            except (OSError, ValueError) as e:
                self._fail(f"the connection to the server was lost ({e})")
            end = time.monotonic() + timeout
            pattern = b"\n" + tail
            while True:
                at = self._buf.find(pattern)
                if at >= 0:
                    close = self._buf.find(b"__\n", at + len(pattern))
                    if close >= 0:
                        output = self._buf[:at]
                        status = int(self._buf[at + len(pattern):close].decode("ascii", "replace") or "1")
                        self._buf = self._buf[close + 3:]
                        return output, status
                if time.monotonic() > end:
                    self._fail("the server did not answer in time")
                read = getattr(self._r, "read1", self._r.read)
                chunk = read(1 << 20)
                if not chunk:
                    self._fail("the connection to the server was lost")
                self._buf += chunk

    def _text(self, command: str) -> tuple:
        out, status = self.run(command + " 2>&1")
        return out.decode("utf-8", "surrogateescape"), status

    def _check(self, command: str, path: str = "") -> str:
        text, status = self._text(command)
        if status != 0:
            raise _shell_error(text.strip(), path)
        return text

    # whole-item calls ------------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        text = self._check(f"cd {quote(path)} && pwd", path)
        return text.strip().splitlines()[-1] if text.strip() else "/"

    def _attrs_of(self, line_text: str, path: str) -> Attrs:
        for line in line_text.splitlines():
            parsed = parse_ls_line(line, time.time(), self.utc_offset)
            if parsed is not None:
                return parsed[2]
        raise FileNotFoundError(errno.ENOENT, "no such file", path)

    def stat(self, path: str, follow: bool = True) -> Attrs:
        flag = "-ldL" if follow else "-ld"
        return self._attrs_of(self._check(f"ls {flag} -- {quote(path)}", path), path)

    def listdir(self, path: str) -> list:
        text = self._check(f"ls -la -- {quote(path)}", path)
        out = []
        for line in text.splitlines():
            parsed = parse_ls_line(line, time.time(), self.utc_offset)
            if parsed is None:
                continue
            name, _target, attrs = parsed
            if name not in (".", ".."):
                out.append(Name(name, line, attrs))
        return out

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        self._check(f"mkdir -- {quote(path)}", path)

    def rmdir(self, path: str) -> None:
        self._check(f"rmdir -- {quote(path)}", path)

    def remove(self, path: str) -> None:
        self._check(f"rm -f -- {quote(path)}", path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        guard = "" if overwrite else f"[ -e {quote(new)} ] && {{ echo 'file exists'; exit 17; }}; "
        text, status = self._text(f"( {guard}mv -f -- {quote(old)} {quote(new)} )")
        if status == 17:
            raise FileExistsError(errno.EEXIST, "file exists", new)
        if status != 0:
            raise _shell_error(text.strip(), old)

    def set_mtime(self, path: str, mtime: float) -> None:
        stamp = datetime.fromtimestamp(int(mtime), timezone.utc).strftime("%Y%m%d%H%M.%S")
        self._check(f"TZ=UTC touch -t {stamp} -- {quote(path)}", path)

    def readlink(self, path: str) -> str:
        return self._check(f"readlink -- {quote(path)}", path).strip()

    # contents -----------------------------------------------------------------------------------------------------------------------------
    def open(self, path: str, flags: int) -> bytes:
        """A handle for reading, or for writing (created, or emptied unless ``EXCL``): the handle is a number the client keeps."""
        with self._lock:
            if flags & WRITE_FLAG:
                if flags & EXCL_FLAG:
                    _out, status = self.run(f"[ -e {quote(path)} ]")
                    if status == 0:
                        raise SftpError(FAILURE, "the file already exists", path)
                self._check(f": > {quote(path)}", path)
            else:
                _out, status = self.run(f"[ -r {quote(path)} ] && [ ! -d {quote(path)} ]")
                if status != 0:
                    raise FileNotFoundError(errno.ENOENT, "no such file", path)
            self._next += 1
            handle = str(self._next).encode()
            self._handles[handle] = path
            return handle

    def close_handle(self, handle: bytes) -> None:
        self._handles.pop(handle, None)

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        """Up to ``count`` bytes from ``offset`` (blocks of 64 KB are read from the one that holds ``offset``, and the front is trimmed)."""
        file = self._handles.get(handle, path)
        first = offset // BLOCK
        lead = offset - first * BLOCK
        blocks = (lead + count + BLOCK - 1) // BLOCK
        out, status = self.run(f"dd if={quote(file)} bs={BLOCK} skip={first} count={blocks} 2>/dev/null")
        if status != 0:
            raise _shell_error("could not read", file)
        return out[lead:lead + count]

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        """Append ``data`` (writes are sequential: a file is made once, from its start)."""
        file = self._handles.get(handle, path)
        pos = 0
        while pos < len(data):
            piece = data[pos:pos + WRITE_BYTES]
            text = base64.b64encode(piece).decode("ascii")
            out, status = self.run(f"{{ printf %s {text} | base64 -d >> {quote(file)}; }} 2>&1")
            if status != 0:
                raise _shell_error(out.decode("utf-8", "replace").strip() or "could not write", file)
            pos += len(piece)

    def close(self) -> None:
        self.closed = True
        try:
            self._close()
        except OSError:
            pass


def _shell_error(text: str, path: str) -> OSError:
    low = text.lower()
    if "no such file" in low or "not found" in low or "cannot find" in low:
        return error_for(NO_SUCH_FILE, text, path)
    if "permission denied" in low or "not permitted" in low:
        return error_for(PERMISSION_DENIED, text, path)
    if "exists" in low:
        return FileExistsError(errno.EEXIST, text or "file exists", path)
    if "not empty" in low:
        return OSError(errno.ENOTEMPTY, text, path)
    return SftpError(FAILURE, text or "the command failed", path)
