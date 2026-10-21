"""An FTP and FTPS client on the standard library's ``ftplib``, with the same calls as ``SftpClient`` (so ``SftpFileSystem`` works on it).

FTP is old and every server does it a little differently, so this file is mostly about the awkward parts:

* **Encryption.** Plain FTP sends the password and the files in the clear; the window says so. FTPS (explicit TLS, ``AUTH TLS``) is
  checked like the web: the system's certificates decide, or the owner pins a certificate by its SHA-256 fingerprint and a changed
  certificate stops the connection. Both the control and the data connections are encrypted, and the data connection reuses the TLS
  session of the control connection, which many servers insist on.
* **Listings.** The exact, machine-readable ``MLSD`` is asked for first. Only a server without it gets the ``LIST`` text read as best it
  can be (Unix and DOS/IIS styles); ``exact_listings`` says which, so the window can warn that sizes and times may be off.
* **One connection is not enough.** A transfer holds an FTP connection busy until it is done, so listing a folder while a file is copied
  would break the protocol. Each open file gets a connection of its own (kept in a small pool and reused), and at most ``MAX_TRANSFERS``
  at once, because servers limit how many connections one client may have.
* **Names** are UTF-8 (negotiated where the server says it can); a server that sends something else is read as Latin-1.
* **Dates:** ``MFMT`` sets the modified time of an uploaded file where the server has it; where not, the server dates the file itself.
"""
from __future__ import annotations

import errno
import ftplib
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .davclient import AuthError, CertificateError, fingerprint_of
from .shellclient import parse_ls_line
from .sftp_proto import EXCL_FLAG, FAILURE, NO_SUCH_FILE, PERMISSION_DENIED, S_IFDIR, S_IFLNK, S_IFREG, WRITE_FLAG, Attrs, Name, SftpError, error_for

TIMEOUT = 30
MAX_TRANSFERS = 2
KEEPALIVE = 25.0
BLOCK = 65536
READ_CHUNK = 1024 * 1024
DOS_LINE = re.compile(r"^(?P<m>\d\d)-(?P<d>\d\d)-(?P<y>\d\d(?:\d\d)?)\s+(?P<h>\d{1,2}):(?P<min>\d\d)\s*(?P<ap>[AP]M)?\s+"
                      r"(?P<size>\d+|<DIR>)\s+(?P<name>.+)$", re.I)


class LoginError(AuthError):
    """The server refused the user name or the password."""


class _ReusingTLS(ftplib.FTP_TLS):
    """``FTP_TLS`` whose data connections resume the TLS session of the control connection (servers such as vsftpd demand it)."""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def mlsd_time(text: str) -> int:
    """The modified time of an MLSD ``modify`` fact (``YYYYMMDDHHMMSS`` in UTC, maybe with a fraction)."""
    try:
        return int(datetime.strptime(text.split(".")[0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def _attrs_from_facts(facts: dict) -> Optional[tuple]:
    """``(Attrs, link target)`` from the facts of an MLSD or MLST line, or None for a folder's own entries (``cdir``, ``pdir``)."""
    kind = facts.get("type", "").lower()
    if kind in ("cdir", "pdir"):
        return None
    unix = facts.get("unix.mode", "")
    mode = int(unix, 8) & 0o7777 if unix.isdigit() else (0o755 if kind == "dir" else 0o644)
    if kind == "dir":
        bits = S_IFDIR
    elif kind.startswith("os.unix=slink"):
        bits = S_IFLNK
    else:
        bits = S_IFREG
    size = int(facts["size"]) if facts.get("size", "").isdigit() else 0
    mtime = mlsd_time(facts["modify"]) if "modify" in facts else 0
    return Attrs(size=size, perm=bits | mode, mtime=mtime, atime=mtime, flags=1 | 4 | 8), kind.partition(":")[2]


def parse_dos_line(line: str) -> Optional[tuple]:
    m = DOS_LINE.match(line.rstrip("\r\n"))
    if m is None:
        return None
    year = int(m.group("y"))
    year += 2000 if year < 70 else 1900 if year < 100 else 0
    hour = int(m.group("h")) % 12 + (12 if (m.group("ap") or "").upper() == "PM" else 0) if m.group("ap") else int(m.group("h"))
    try:
        mtime = int(datetime(year, int(m.group("m")), int(m.group("d")), hour, int(m.group("min")), tzinfo=timezone.utc).timestamp())
    except ValueError:
        mtime = 0
    is_dir = m.group("size").upper() == "<DIR>"
    attrs = Attrs(size=0 if is_dir else int(m.group("size")), perm=(S_IFDIR | 0o755) if is_dir else (S_IFREG | 0o644), mtime=mtime,
                  atime=mtime, flags=1 | 4 | 8)
    return m.group("name"), attrs


def parse_list_line(line: str, now: float) -> Optional[tuple]:
    """``(name, Attrs)`` of one line of a ``LIST`` answer, Unix style or DOS style (None for anything else)."""
    parsed = parse_ls_line(line, now, 0)
    if parsed is not None:
        return parsed[0], parsed[2]
    return parse_dos_line(line)


def _error(e: BaseException, path: str = "") -> OSError:
    """The ``OSError`` for what ftplib raised."""
    text = str(e)
    code = text[:3]
    low = text.lower()
    if isinstance(e, (socket.timeout, TimeoutError)):
        return ConnectionError("the server did not answer in time")
    if isinstance(e, ftplib.error_perm):
        if code in ("530", "331", "332"):
            return LoginError(errno.EACCES, text)
        if "not empty" in low:
            return OSError(errno.ENOTEMPTY, text, path)
        if "exist" in low and "no such" not in low and "not exist" not in low and "does not exist" not in low:
            return FileExistsError(errno.EEXIST, text, path)
        if code == "550" and any(w in low for w in ("permission", "denied", "not allowed", "access")):
            return error_for(PERMISSION_DENIED, text, path)
        if code in ("550", "450") or "no such" in low or "not found" in low or "not exist" in low:
            return error_for(NO_SUCH_FILE, text, path)
        if code in ("553", "532"):
            return error_for(PERMISSION_DENIED, text, path)
        return SftpError(FAILURE, text, path)
    if isinstance(e, ftplib.error_temp):
        if code == "421":
            return ConnectionError(text)
        return SftpError(FAILURE, text, path)
    if isinstance(e, (EOFError, ConnectionError, ssl.SSLError, ftplib.error_reply, ftplib.error_proto, OSError)):
        return e if isinstance(e, OSError) and not isinstance(e, ssl.SSLError) else ConnectionError(f"the connection to the server was lost ({e})")
    return SftpError(FAILURE, text, path)


class FtpClient:
    def __init__(self, host: str, port: int = 21, secure: bool = True, user: str = "", password: str = "", pinned: str = "",
                 timeout: float = TIMEOUT) -> None:
        self.host, self.port, self.secure = host, port, secure
        self.user, self.password, self.pinned = user or "anonymous", password if user else "dossier@", pinned
        self.timeout = timeout
        self.closed = False
        self.version = 0
        self.extensions: dict = {}
        self.exact_listings = True
        self.can_set_mtime = True
        self.peer_fingerprint = ""
        self.features: set = set()
        self.home = "/"
        self._lock = threading.RLock()
        self._ftp: Optional[ftplib.FTP] = None
        self._used = 0.0
        self._pool: list = []
        self._slots = {"read": threading.BoundedSemaphore(MAX_TRANSFERS), "write": threading.BoundedSemaphore(MAX_TRANSFERS)}
        self._handles: dict = {}
        self._next = 0

    # connections ---------------------------------------------------------------------------------------------------------------------
    def _context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if self.pinned:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE                    # the pinned fingerprint is checked instead of the chain of trust
        return context

    def _new_session(self) -> ftplib.FTP:
        """A logged-in connection (encrypted when asked), in binary mode. Raises ``CertificateError``, ``LoginError`` or ``ConnectionError``."""
        ftp: ftplib.FTP = _ReusingTLS(context=self._context(), timeout=self.timeout) if self.secure else ftplib.FTP(timeout=self.timeout)
        try:
            ftp.connect(self.host, self.port)
            if self.secure:
                ftp.auth()
                self.peer_fingerprint = fingerprint_of(ftp.sock.getpeercert(binary_form=True) or b"")
                if self.pinned and self.peer_fingerprint != self.pinned:
                    raise CertificateError("the server's certificate is not the one you approved", self.peer_fingerprint, changed=True)
            ftp.login(self.user, self.password)
            if self.secure:
                ftp.prot_p()
            ftp.voidcmd("TYPE I")
            return ftp
        except ssl.SSLCertVerificationError as e:                        # not expected here: connect() asked about the certificate first
            self._quit(ftp)
            raise CertificateError(f"the server's certificate is not trusted ({getattr(e, 'verify_message', None) or e})",
                                   self.peer_fingerprint)
        except CertificateError:
            self._quit(ftp)
            raise
        except ftplib.all_errors as e:
            self._quit(ftp)
            raise _error(e)

    @staticmethod
    def _quit(ftp) -> None:
        try:
            ftp.close()
        except Exception:   # noqa: BLE001
            pass

    def connect(self) -> None:
        """Make the main connection and learn what the server can do; raises ``CertificateError``, ``LoginError``, ``ConnectionError``."""
        with self._lock:
            if self.secure and not self.pinned:
                self._probe_certificate()
            self._ftp = self._new_session()
            self._used = time.monotonic()
            try:
                reply = self._ftp.sendcmd("FEAT")
                self.features = {line.strip().split(" ")[0].upper() for line in reply.splitlines()[1:-1] if line.strip()}
            except ftplib.all_errors:
                self.features = set()
            if "UTF8" in self.features:
                try:
                    self._ftp.sendcmd("OPTS UTF8 ON")
                except ftplib.all_errors:
                    pass
            self.exact_listings = "MLST" in self.features
            self.home = self._ftp.pwd() or "/"

    def _probe_certificate(self) -> None:
        """Before logging in over TLS, find out whether the certificate is trusted: the owner is asked about it, not about a login."""
        ftp = _ReusingTLS(context=self._context(), timeout=self.timeout)
        try:
            ftp.connect(self.host, self.port)
            ftp.auth()
        except ssl.SSLCertVerificationError as e:
            self._quit(ftp)
            shown = ""
            try:
                shown = self._fetch_fingerprint()
            except Exception:   # noqa: BLE001
                pass
            raise CertificateError(f"the server's certificate is not trusted ({getattr(e, 'verify_message', None) or e})", shown)
        except ftplib.all_errors as e:
            self._quit(ftp)
            raise _error(e)
        self._quit(ftp)

    def _fetch_fingerprint(self) -> str:
        """The certificate an FTPS server shows, trusted or not (the control connection is opened plain, then upgraded without checks)."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        ftp = ftplib.FTP(timeout=self.timeout)
        try:
            ftp.connect(self.host, self.port)
            ftp.voidcmd("AUTH TLS")
            tls = context.wrap_socket(ftp.sock, server_hostname=self.host)
            return fingerprint_of(tls.getpeercert(binary_form=True) or b"")
        finally:
            self._quit(ftp)

    def close(self) -> None:
        self.closed = True
        with self._lock:
            for session in self._pool + ([self._ftp] if self._ftp is not None else []):
                self._quit(session)
            self._pool.clear()
            self._ftp = None
            for state in list(self._handles.values()):
                self._drop_handle(state)
            self._handles.clear()

    def _main(self) -> ftplib.FTP:
        if self.closed:
            raise ConnectionError("the connection to the server was closed")
        if self._ftp is None:
            raise ConnectionError("the connection to the server was lost")
        if time.monotonic() - self._used > KEEPALIVE:
            try:
                self._ftp.voidcmd("NOOP")
            except ftplib.all_errors:
                self._ftp = self._new_session()                      # the server dropped an idle connection: log in again
        return self._ftp

    def _do(self, action: Callable, path: str = ""):
        """Run ``action(ftp)`` on the main connection, one thing at a time; ftplib's errors become the program's."""
        with self._lock:
            ftp = self._main()
            try:
                result = action(ftp)
                self._used = time.monotonic()
                return result
            except UnicodeDecodeError:
                ftp.encoding = "latin-1"                              # a server that does not speak UTF-8
                ftp.close()
                self._ftp = self._new_session()
                self._ftp.encoding = "latin-1"
                return action(self._ftp)
            except ftplib.all_errors as e:
                err = _error(e, path)
                if isinstance(err, ConnectionError):
                    self._quit(ftp)
                    self._ftp = None
                raise err

    # whole-item calls -----------------------------------------------------------------------------------------------------------------------
    def realpath(self, path: str) -> str:
        if path in (".", ""):
            return self.home
        return path

    def _list_names(self, path: str) -> list:
        def mlsd(ftp):
            return list(ftp.mlsd(path, facts=["type", "size", "modify", "unix.mode"]))
        if "MLST" in self.features:
            out = []
            for name, facts in self._do(mlsd, path):
                got = _attrs_from_facts({k.lower(): v for k, v in facts.items()})
                if got is not None and name not in (".", ".."):
                    out.append(Name(name, "", got[0]))
            return out
        lines: list = []
        self._do(lambda ftp: ftp.retrlines(f"LIST {path}" if path not in ("", "/") else "LIST", lines.append), path)
        now = time.time()
        out = []
        for line in lines:
            parsed = parse_list_line(line, now)
            if parsed is not None and parsed[0] not in (".", ".."):
                out.append(Name(parsed[0], line, parsed[1]))
        return out

    def listdir(self, path: str) -> list:
        return self._list_names(path)

    def stat(self, path: str, follow: bool = True) -> Attrs:
        if path in ("/", ""):
            return Attrs(perm=S_IFDIR | 0o755, flags=1 | 4 | 8)
        if "MLST" in self.features:
            reply = self._do(lambda ftp: ftp.sendcmd(f"MLST {path}"), path)
            for line in reply.splitlines()[1:-1]:
                text = line.strip()
                facts_text, _sp, _name = text.partition(" ")
                facts = {}
                for pair in facts_text.split(";"):
                    key, _eq, value = pair.partition("=")
                    if key:
                        facts[key.lower()] = value
                got = _attrs_from_facts(facts)
                if got is not None:
                    return got[0]
            raise error_for(NO_SUCH_FILE, "no such file", path)
        parent, _s, name = path.rstrip("/").rpartition("/")
        for entry in self._list_names(parent or "/"):
            if entry.name == name:
                return entry.attrs
        raise error_for(NO_SUCH_FILE, "no such file", path)

    def mkdir(self, path: str, perm: int = 0o755) -> None:
        self._do(lambda ftp: ftp.mkd(path), path)

    def rmdir(self, path: str) -> None:
        self._do(lambda ftp: ftp.rmd(path), path)

    def remove(self, path: str) -> None:
        self._do(lambda ftp: ftp.delete(path), path)

    def rename(self, old: str, new: str, overwrite: bool = False) -> None:
        if overwrite:
            try:
                self.stat(new)
            except FileNotFoundError:
                pass
            else:
                self.remove(new)                                       # FTP has no replace: the old file goes first (not atomic)
        self._do(lambda ftp: ftp.rename(old, new), old)

    def set_mtime(self, path: str, mtime: float) -> None:
        if not self.can_set_mtime or "MFMT" not in self.features:
            return
        stamp = datetime.fromtimestamp(int(mtime), timezone.utc).strftime("%Y%m%d%H%M%S")
        try:
            self._do(lambda ftp: ftp.voidcmd(f"MFMT {stamp} {path}"), path)
        except OSError:
            self.can_set_mtime = False                                 # it said it could and cannot: stop trying

    def readlink(self, path: str) -> str:
        raise OSError(errno.EINVAL, "FTP gives no link targets", path)

    # contents: one connection per open file -------------------------------------------------------------------------------------------------
    def _take_session(self, kind: str) -> ftplib.FTP:
        """A connection for one transfer. Reads and writes have their own limit, so copying inside one server cannot wait for itself."""
        self._slots[kind].acquire()
        try:
            with self._lock:
                while self._pool:
                    session = self._pool.pop()
                    try:
                        session.voidcmd("NOOP")
                        return session
                    except ftplib.all_errors:
                        self._quit(session)
            return self._new_session()
        except BaseException:
            self._slots[kind].release()
            raise

    def _give_back(self, session: Optional[ftplib.FTP], healthy: bool, kind: str) -> None:
        try:
            if session is not None:
                if healthy and not self.closed:
                    with self._lock:
                        self._pool.append(session)
                else:
                    self._quit(session)
        finally:
            self._slots[kind].release()

    def _drop_handle(self, state: dict) -> None:
        conn, session = state.get("conn"), state.get("session")
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if session is not None:
            self._give_back(session, False, "write" if state["write"] else "read")
        state["conn"] = state["session"] = None

    def open(self, path: str, flags: int) -> bytes:
        with self._lock:
            self._next += 1
            handle = str(self._next).encode()
        if flags & WRITE_FLAG:
            if flags & EXCL_FLAG:
                try:
                    self.stat(path)
                except FileNotFoundError:
                    pass
                else:
                    raise SftpError(FAILURE, "the file already exists", path)
            session = self._take_session("write")
            try:
                conn, _size = session.ntransfercmd(f"STOR {path}")
            except ftplib.all_errors as e:
                self._give_back(session, False, "write")
                raise _error(e, path)
            state = {"path": path, "write": True, "conn": conn, "session": session, "pos": 0}
        else:
            attrs = self.stat(path)
            if attrs.is_dir:
                raise error_for(NO_SUCH_FILE, "it is a folder", path)
            state = {"path": path, "write": False, "conn": None, "session": None, "pos": 0, "size": attrs.size}
        self._handles[handle] = state
        return handle

    def _start_read(self, state: dict, offset: int) -> None:
        self._drop_handle(state)                                         # a jump: the old transfer is given up, not drained
        session = self._take_session("read")
        try:
            conn, _size = session.ntransfercmd(f"RETR {state['path']}", rest=offset if offset else None)
        except ftplib.all_errors as e:
            self._give_back(session, False, "read")
            raise _error(e, state["path"])
        state.update(conn=conn, session=session, pos=offset)

    def read_blocks(self, handle: bytes, offset: int, count: int, path: str = "") -> bytes:
        state = self._handles[handle]
        if offset >= state["size"]:
            return b""
        if state["conn"] is None or state["pos"] != offset:
            self._start_read(state, offset)
        out = []
        left = min(count, state["size"] - offset)
        try:
            while left > 0:
                chunk = state["conn"].recv(min(left, BLOCK))
                if not chunk:
                    break
                out.append(chunk)
                left -= len(chunk)
        except (OSError, ssl.SSLError) as e:
            self._drop_handle(state)
            raise _error(e, state["path"])
        data = b"".join(out)
        state["pos"] += len(data)
        if state["pos"] >= state["size"]:                                # the whole file came: close the transfer properly and reuse the connection
            self._finish(state, read=True)
        return data

    def _finish(self, state: dict, read: bool) -> None:
        conn, session = state["conn"], state["session"]
        state["conn"] = state["session"] = None
        healthy = False
        try:
            if conn is not None:
                if isinstance(conn, ssl.SSLSocket):
                    try:
                        conn.unwrap()
                    except (OSError, ssl.SSLError):
                        pass
                conn.close()
            if session is not None:
                session.voidresp()                                         # the 226 that says the server has it all
                healthy = True
        except ftplib.all_errors as e:
            if not read:
                self._give_back(session, False, "write")
                session = None
                raise _error(e, state["path"])
        finally:
            if session is not None:
                self._give_back(session, healthy, "read" if read else "write")

    def write_blocks(self, handle: bytes, offset: int, data: bytes, path: str = "") -> None:
        state = self._handles[handle]
        if offset != state["pos"]:
            raise OSError(errno.EINVAL, "an FTP file can only be written from its start, in order", state["path"])
        try:
            view = memoryview(data)
            for i in range(0, len(data), BLOCK):
                state["conn"].sendall(view[i:i + BLOCK])
        except (OSError, ssl.SSLError) as e:
            self._drop_handle(state)
            raise _error(e, state["path"])
        state["pos"] += len(data)

    def close_handle(self, handle: bytes) -> None:
        state = self._handles.pop(handle, None)
        if state is None:
            return
        if state["write"] and state["conn"] is not None:
            self._finish(state, read=False)                              # raises when the server did not take the file
        else:
            self._drop_handle(state)
