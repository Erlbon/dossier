"""An SFTP client (protocol version 3, the one every server speaks), over any pair of byte streams. Standard library only.

The streams are the standard input and output of ``ssh -s host sftp`` (see ``sshlink.py``), so the encryption, the keys and the login
are the operating system's OpenSSH and this file only knows the file protocol. Nothing here prints, prompts or opens a window.

A request is one packet; the server answers each with a status, a handle, data, names or attributes. Reading and writing are pipelined (a
window of requests is sent before the answers are read), so a link with a long delay still fills up. One exchange at a time goes over the
wire (a lock), so a listing and a copy running on two threads share the connection safely. Server errors become the ``OSError`` kinds
the rest of the program already understands (``FileNotFoundError``, ``PermissionError``...), and a lost connection is a
``ConnectionError``.
"""
from __future__ import annotations

import errno
import io
import struct
import threading
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Optional

INIT, VERSION, OPEN, CLOSE, READ, WRITE, LSTAT, FSTAT, SETSTAT, FSETSTAT, OPENDIR, READDIR, REMOVE, MKDIR, RMDIR, REALPATH, STAT, RENAME, \
    READLINK, SYMLINK = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20
STATUS, HANDLE, DATA, NAME, ATTRS, EXTENDED, EXTENDED_REPLY = 101, 102, 103, 104, 105, 200, 201
OK, EOF, NO_SUCH_FILE, PERMISSION_DENIED, FAILURE, BAD_MESSAGE, NO_CONNECTION, CONNECTION_LOST, OP_UNSUPPORTED = range(9)
READ_FLAG, WRITE_FLAG, APPEND_FLAG, CREAT_FLAG, TRUNC_FLAG, EXCL_FLAG = 1, 2, 4, 8, 0x10, 0x20
ATTR_SIZE, ATTR_UIDGID, ATTR_PERMISSIONS, ATTR_ACMODTIME, ATTR_EXTENDED = 1, 2, 4, 8, 0x80000000
S_IFMT, S_IFDIR, S_IFREG, S_IFLNK = 0o170000, 0o040000, 0o100000, 0o120000

CHUNK = 32 * 1024                    # every server accepts this much in one read or write
WINDOW = 8                           # requests in flight at once
MAX_PACKET = 8 * 1024 * 1024
POSIX_RENAME = "posix-rename@openssh.com"


@dataclass
class Attrs:
    size: int = 0
    uid: int = 0
    gid: int = 0
    perm: int = 0
    atime: int = 0
    mtime: int = 0
    flags: int = 0

    @property
    def is_dir(self) -> bool:
        return self.perm & S_IFMT == S_IFDIR

    @property
    def is_link(self) -> bool:
        return self.perm & S_IFMT == S_IFLNK

    @property
    def is_file(self) -> bool:
        return self.perm & S_IFMT == S_IFREG


@dataclass
class Name:
    name: str
    longname: str
    attrs: Attrs = field(default_factory=Attrs)


class SftpError(OSError):
    """An error the server reported (``code`` is its status code)."""

    def __init__(self, code: int, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def error_for(code: int, message: str, path: str = "") -> OSError:
    text = message or {NO_SUCH_FILE: "no such file", PERMISSION_DENIED: "permission denied", FAILURE: "the server refused",
                       OP_UNSUPPORTED: "the server does not support this", CONNECTION_LOST: "connection lost"}.get(code, f"error {code}")
    if code == NO_SUCH_FILE:
        e: OSError = FileNotFoundError(errno.ENOENT, text, path or None)
    elif code == PERMISSION_DENIED:
        e = PermissionError(errno.EACCES, text, path or None)
    elif code in (NO_CONNECTION, CONNECTION_LOST):
        e = ConnectionError(text)
    else:
        e = SftpError(code, text, path)
    return e


# packing -----------------------------------------------------------------------------------------------------------------------------
def p_string(data) -> bytes:
    raw = data.encode("utf-8", "surrogateescape") if isinstance(data, str) else bytes(data)
    return struct.pack(">I", len(raw)) + raw


def p_attrs(size: Optional[int] = None, perm: Optional[int] = None, mtime: Optional[int] = None, atime: Optional[int] = None) -> bytes:
    flags = (ATTR_SIZE if size is not None else 0) | (ATTR_PERMISSIONS if perm is not None else 0) | (ATTR_ACMODTIME if mtime is not None else 0)
    out = struct.pack(">I", flags)
    if size is not None:
        out += struct.pack(">Q", size)
    if perm is not None:
        out += struct.pack(">I", perm)
    if mtime is not None:
        out += struct.pack(">II", int(atime if atime is not None else mtime), int(mtime))
    return out


class Reader:
    """Takes a packet's payload apart."""

    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def u8(self) -> int:
        self.pos += 1
        return self.data[self.pos - 1]

    def u32(self) -> int:
        self.pos += 4
        return struct.unpack(">I", self.data[self.pos - 4:self.pos])[0]

    def u64(self) -> int:
        self.pos += 8
        return struct.unpack(">Q", self.data[self.pos - 8:self.pos])[0]

    def string(self) -> bytes:
        n = self.u32()
        out = self.data[self.pos:self.pos + n]
        if len(out) != n:
            raise ValueError("a string is cut short")
        self.pos += n
        return out

    def text(self) -> str:
        return self.string().decode("utf-8", "surrogateescape")

    def attrs(self) -> Attrs:
        a = Attrs(flags=self.u32())
        if a.flags & ATTR_SIZE:
            a.size = self.u64()
        if a.flags & ATTR_UIDGID:
            a.uid, a.gid = self.u32(), self.u32()
        if a.flags & ATTR_PERMISSIONS:
            a.perm = self.u32()
        if a.flags & ATTR_ACMODTIME:
            a.atime, a.mtime = self.u32(), self.u32()
        if a.flags & ATTR_EXTENDED:
            for _ in range(self.u32()):
                self.string()
                self.string()
        return a

    def rest(self) -> bytes:
        return self.data[self.pos:]


# the client --------------------------------------------------------------------------------------------------------------------------
class SftpClient:
    def __init__(self, reader: BinaryIO, writer: BinaryIO, close: Callable[[], None] = lambda: None) -> None:
        self._r, self._w, self._close = reader, writer, close
        self._lock = threading.RLock()
        self._next = 1
        self.version = 0
        self.extensions: dict = {}
        self.closed = False
        self._handshake()

    # the wire -----------------------------------------------------------------------------------------------------------------------
    def _read_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            part = self._r.read(n - len(out))
            if not part:
                self.closed = True
                raise ConnectionError("the connection to the server was lost")
            out += part
        return out

    def _send_packet(self, kind: int, payload: bytes) -> None:
        try:
            self._w.write(struct.pack(">IB", len(payload) + 1, kind) + payload)
            self._w.flush()
        except (OSError, ValueError) as e:
            self.closed = True
            raise ConnectionError(f"the connection to the server was lost ({e})")

    def _recv_packet(self) -> tuple:
        length = struct.unpack(">I", self._read_exact(4))[0]
        if length < 1 or length > MAX_PACKET:
            self.closed = True
            raise ConnectionError("the server sent something that is not SFTP")
        body = self._read_exact(length)
        return body[0], body[1:]

    def _handshake(self) -> None:
        self._send_packet(INIT, struct.pack(">I", 3))
        kind, payload = self._recv_packet()
        if kind != VERSION:
            raise ConnectionError("the server did not answer like an SFTP server")
        r = Reader(payload)
        self.version = r.u32()
        while r.pos < len(payload):
            name, data = r.text(), r.text()
            self.extensions[name] = data

    def _new_id(self) -> int:
        with self._lock:
            self._next = (self._next + 1) & 0x7FFFFFFF
            return self._next

    def _call(self, kind: int, payload: bytes, path: str = "") -> tuple:
        """One request, its answer: ``(type, Reader)``. A status that is an error is raised."""
        with self._lock:
            rid = self._new_id()
            self._send_packet(kind, struct.pack(">I", rid) + payload)
            rkind, data = self._recv_packet()
            r = Reader(data)
            if r.u32() != rid:
                self.closed = True
                raise ConnectionError("the server answered out of order")
            if rkind == STATUS:
                code, message = r.u32(), r.text()
                if code != OK:
                    raise error_for(code, message, path)
            return rkind, r

    def _expect_ok(self, kind: int, payload: bytes, path: str = "") -> None:
        rkind, _r = self._call(kind, payload, path)
        if rkind != STATUS:
            raise ConnectionError("the server answered with something unexpected")

    # whole-item calls -----------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        kind, r = self._call(REALPATH, p_string(path), path)
        if kind != NAME or r.u32() < 1:
            raise ConnectionError("no answer to REALPATH")
        return r.text()

    def stat(self, path: str, follow: bool = True) -> Attrs:
        kind, r = self._call(STAT if follow else LSTAT, p_string(path), path)
        if kind != ATTRS:
            raise ConnectionError("no attributes in the answer")
        return r.attrs()

    def listdir(self, path: str) -> list:
        """Every entry of a folder as ``Name`` (without ``.`` and ``..``)."""
        with self._lock:
            kind, r = self._call(OPENDIR, p_string(path), path)
            handle = r.string()
            out: list = []
            try:
                while True:
                    try:
                        rkind, r = self._call(READDIR, p_string(handle), path)
                    except SftpError as e:
                        if e.code == EOF:
                            break
                        raise
                    if rkind != NAME:
                        break
                    for _ in range(r.u32()):
                        name, longname, attrs = r.text(), r.text(), r.attrs()
                        if name not in (".", ".."):
                            out.append(Name(name, longname, attrs))
            finally:
                self._close_handle(handle)
        return out

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        self._expect_ok(MKDIR, p_string(path) + p_attrs(perm=perm), path)

    def rmdir(self, path: str) -> None:
        self._expect_ok(RMDIR, p_string(path), path)

    def remove(self, path: str) -> None:
        self._expect_ok(REMOVE, p_string(path), path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        """Version 3 refuses an existing target; OpenSSH servers have an extension that replaces it atomically."""
        if overwrite and POSIX_RENAME in self.extensions:
            self._expect_ok(EXTENDED, p_string(POSIX_RENAME) + p_string(old) + p_string(new), old)
        else:
            self._expect_ok(RENAME, p_string(old) + p_string(new), old)

    def set_mtime(self, path: str, mtime: float) -> None:
        self._expect_ok(SETSTAT, p_string(path) + p_attrs(mtime=int(mtime)), path)

    def readlink(self, path: str) -> str:
        kind, r = self._call(READLINK, p_string(path), path)
        r.u32()
        return r.text()

    # handles --------------------------------------------------------------------------------------------------------------------------
    def open(self, path: str, flags: int) -> bytes:
        kind, r = self._call(OPEN, p_string(path) + struct.pack(">I", flags) + p_attrs(), path)
        return r.string()

    def _close_handle(self, handle: bytes) -> None:
        try:
            self._expect_ok(CLOSE, p_string(handle))
        except OSError:
            pass

    def close_handle(self, handle: bytes) -> None:
        self._close_handle(handle)

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        """Up to ``count`` bytes from ``offset``, as a window of pipelined reads; shorter than asked only at the end of the file."""
        want = [(offset + i * CHUNK, min(CHUNK, count - i * CHUNK)) for i in range((count + CHUNK - 1) // CHUNK)][:WINDOW]
        with self._lock:
            ids = []
            for at, n in want:
                rid = self._new_id()
                ids.append(rid)
                self._send_packet(READ, struct.pack(">I", rid) + p_string(handle) + struct.pack(">QI", at, n))
            parts: dict = {}
            error: Optional[OSError] = None
            for _ in ids:
                rkind, data = self._recv_packet()
                r = Reader(data)
                rid = r.u32()
                if rkind == DATA:
                    parts[rid] = r.string()
                elif rkind == STATUS:
                    code, message = r.u32(), r.text()
                    if code == EOF:
                        parts[rid] = b""
                    elif error is None:
                        error = error_for(code, message, path)
                else:
                    error = error or ConnectionError("unexpected answer to a read")
            if error is not None:
                raise error
        out = b""
        for rid, (_at, n) in zip(ids, want):
            piece = parts.get(rid, b"")
            out += piece
            if len(piece) < n:
                break                                         # the end of the file, or a short answer: nothing after it counts
        return out

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        with self._lock:
            ids = []
            pos = 0
            while pos < len(data):
                batch = 0
                while pos < len(data) and batch < WINDOW:
                    piece = data[pos:pos + CHUNK]
                    rid = self._new_id()
                    ids.append(rid)
                    self._send_packet(WRITE, struct.pack(">I", rid) + p_string(handle) + struct.pack(">Q", offset + pos) + p_string(piece))
                    pos += len(piece)
                    batch += 1
                error: Optional[OSError] = None
                for _ in range(batch):
                    rkind, payload = self._recv_packet()
                    r = Reader(payload)
                    r.u32()
                    if rkind != STATUS:
                        error = error or ConnectionError("unexpected answer to a write")
                        continue
                    code, message = r.u32(), r.text()
                    if code != OK and error is None:
                        error = error_for(code, message, path)
                if error is not None:
                    raise error

    def close(self) -> None:
        self.closed = True
        try:
            self._close()
        except OSError:
            pass


# file objects ------------------------------------------------------------------------------------------------------------------------
class SftpReadFile(io.RawIOBase):
    """A remote file opened for reading: ``read``, ``seek``, ``tell``; reading ahead in pipelined windows."""

    def __init__(self, client: SftpClient, path: str, size: int) -> None:
        super().__init__()
        self._handle = None
        self._client, self._path, self._size = client, path, size
        self._handle = client.open(path, READ_FLAG)
        self._pos = 0
        self._buf = b""
        self._buf_at = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        target = offset if whence == 0 else self._pos + offset if whence == 1 else self._size + offset
        self._pos = max(0, target)
        return self._pos

    def _fill(self) -> bool:
        data = self._client.read_blocks(self._handle, self._pos, CHUNK * WINDOW, self._path)
        self._buf, self._buf_at = data, self._pos
        return bool(data)

    def read(self, n: int = -1) -> bytes:
        if self.closed:
            raise ValueError("read of a closed file")
        out = []
        left = n if n >= 0 else 1 << 62
        while left > 0:
            if not (self._buf_at <= self._pos < self._buf_at + len(self._buf)) and not self._fill():
                break
            start = self._pos - self._buf_at
            piece = self._buf[start:start + left]
            out.append(piece)
            self._pos += len(piece)
            left -= len(piece)
        return b"".join(out)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed:
            try:
                if self._handle is not None:
                    self._client.close_handle(self._handle)
            finally:
                super().close()


class SftpWriteFile(io.RawIOBase):
    """A remote file opened for writing (created or emptied)."""

    def __init__(self, client: SftpClient, path: str, exclusive: bool = False) -> None:
        super().__init__()
        self._handle = None
        self._client, self._path = client, path
        flags = WRITE_FLAG | CREAT_FLAG | (EXCL_FLAG if exclusive else TRUNC_FLAG)
        self._handle = client.open(path, flags)
        self._pos = 0

    def writable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def write(self, data) -> int:
        if self.closed:
            raise ValueError("write to a closed file")
        data = bytes(data)
        self._client.write_blocks(self._handle, self._pos, data, self._path)
        self._pos += len(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        if not self.closed:
            try:
                if self._handle is not None:
                    self._client.close_handle(self._handle)
            finally:
                super().close()
