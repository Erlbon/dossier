"""A small FTP and FTPS server for the tests, in this process: a folder served over the FTP commands a file manager uses.

It answers like the servers that matter: passive mode, ``FEAT`` with or without ``MLST``/``MLSD``, a Unix or a DOS style ``LIST`` when MLSD is
off, ``REST`` for resuming, ``MFMT`` for dates, explicit TLS (``AUTH TLS``, ``PBSZ``, ``PROT P``) with the option, which vsftpd has, of
refusing a data connection that does not resume the control connection's TLS session. ``log`` lists the commands received and
``peak_clients`` the most control connections that were open at once (servers limit them).
"""
from __future__ import annotations

import os
import shutil
import socket
import ssl
import threading
import time
from datetime import datetime, timezone


class FtpServer:
    def __init__(self, root: str, *, users: dict | None = None, mlsd: bool = True, dos_list: bool = False, certfile: str = "",
                 keyfile: str = "", require_reuse: bool = False, mfmt: bool = True, latin1: bool = False) -> None:
        self.root, self.users = root, users or {}
        self.mlsd, self.dos_list, self.mfmt, self.latin1 = mlsd, dos_list, mfmt, latin1
        self.require_reuse = require_reuse
        self.context = None
        if certfile:
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(certfile, keyfile)
        self.log: list = []
        self.clients = 0
        self.peak_clients = 0
        self._lock = threading.Lock()
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.stopped = False
        threading.Thread(target=self._accept, daemon=True, name="test-ftp").start()

    def stop(self) -> None:
        self.stopped = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _accept(self) -> None:
        while not self.stopped:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=Session(self, conn).run, daemon=True, name="test-ftp-client").start()

    def commands(self) -> list:
        return [line.split(" ", 1)[0].upper() for line in self.log]


class Session:
    def __init__(self, server: FtpServer, conn: socket.socket) -> None:
        self.s, self.sock = server, conn
        self.cwd = "/"
        self.user = ""
        self.authed = not server.users and False
        self.rest = 0
        self.rnfr = ""
        self.pasv: socket.socket | None = None
        self.prot_p = False
        self.tls = False
        self.buf = b""

    # the control channel ----------------------------------------------------------------------------------------------------------------
    def send(self, text: str) -> None:
        self.sock.sendall(text.encode("utf-8") + b"\r\n")

    def readline(self) -> str | None:
        while b"\r\n" not in self.buf:
            try:
                chunk = self.sock.recv(4096)
            except (OSError, ssl.SSLError):
                return None
            if not chunk:
                return None
            self.buf += chunk
        line, _s, self.buf = self.buf.partition(b"\r\n")
        return line.decode("latin-1" if self.s.latin1 else "utf-8", "replace")

    def run(self) -> None:
        with self.s._lock:
            self.s.clients += 1
            self.s.peak_clients = max(self.s.peak_clients, self.s.clients)
        try:
            self.send("220 test server")
            while True:
                line = self.readline()
                if line is None:
                    return
                self.s.log.append(line)
                cmd, _sp, arg = line.partition(" ")
                handler = getattr(self, "do_" + cmd.upper(), None)
                if handler is None:
                    self.send("502 not implemented")
                    continue
                if cmd.upper() not in ("USER", "PASS", "QUIT", "AUTH", "FEAT", "PBSZ", "PROT", "OPTS", "SYST") and not self.authed:
                    self.send("530 please log in")
                    continue
                try:
                    if handler(arg) == "quit":
                        return
                except (OSError, ssl.SSLError):
                    return
        finally:
            with self.s._lock:
                self.s.clients -= 1
            try:
                self.sock.close()
            except OSError:
                pass

    # paths ------------------------------------------------------------------------------------------------------------------------------
    def virtual(self, arg: str) -> str:
        path = arg if arg.startswith("/") else (self.cwd.rstrip("/") + "/" + arg)
        parts: list = []
        for p in path.split("/"):
            if p in ("", "."):
                continue
            if p == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(p)
        return "/" + "/".join(parts)

    def real(self, arg: str) -> str:
        return os.path.join(self.s.root, *self.virtual(arg).strip("/").split("/")) if self.virtual(arg) != "/" else self.s.root

    # the commands -------------------------------------------------------------------------------------------------------------------------
    def do_USER(self, arg: str) -> None:
        self.user = arg
        if not self.s.users:
            self.authed = True
            return self.send("230 anonymous ok")
        self.send("331 password please")

    def do_PASS(self, arg: str) -> None:
        if self.s.users.get(self.user) == arg:
            self.authed = True
            self.send("230 logged in")
        else:
            self.send("530 login incorrect")

    def do_SYST(self, arg: str) -> None:
        self.send("215 UNIX Type: L8")

    def do_FEAT(self, arg: str) -> None:
        feats = ["UTF8", "REST STREAM"] + (["MLST type*;size*;modify*;unix.mode*;", "MLSD"] if self.s.mlsd else []) + (["MFMT"] if self.s.mfmt else [])
        feats += ["AUTH TLS", "PBSZ", "PROT"] if self.s.context else []
        self.send("211-Features:")
        for f in feats:
            self.send(" " + f)
        self.send("211 End")

    def do_OPTS(self, arg: str) -> None:
        self.send("200 ok")

    def do_AUTH(self, arg: str) -> None:
        if not self.s.context:
            return self.send("502 no TLS")
        self.send("234 go ahead")
        self.sock = self.s.context.wrap_socket(self.sock, server_side=True)
        self.tls = True

    def do_PBSZ(self, arg: str) -> None:
        self.send("200 PBSZ=0")

    def do_PROT(self, arg: str) -> None:
        self.prot_p = arg.upper() == "P"
        self.send("200 ok")

    def do_TYPE(self, arg: str) -> None:
        self.send("200 type set")

    def do_PWD(self, arg: str) -> None:
        self.send(f'257 "{self.cwd}" is the current directory')

    def do_CWD(self, arg: str) -> None:
        if os.path.isdir(self.real(arg)):
            self.cwd = self.virtual(arg)
            self.send("250 ok")
        else:
            self.send("550 no such directory")

    def do_NOOP(self, arg: str) -> None:
        self.send("200 ok")

    def do_QUIT(self, arg: str) -> str:
        self.send("221 bye")
        return "quit"

    def do_PASV(self, arg: str) -> None:
        if self.pasv is not None:
            self.pasv.close()
        self.pasv = socket.socket()
        self.pasv.bind(("127.0.0.1", 0))
        self.pasv.listen(1)
        self.pasv.settimeout(10)
        port = self.pasv.getsockname()[1]
        self.send(f"227 Entering Passive Mode (127,0,0,1,{port >> 8},{port & 255})")

    def data(self):
        """The data connection the client opens after PASV (encrypted when the client asked for it)."""
        if self.pasv is None:
            self.send("425 use PASV first")
            return None
        try:
            conn, _a = self.pasv.accept()
        except OSError:
            self.send("425 no data connection")
            return None
        finally:
            self.pasv.close()
            self.pasv = None
        return conn

    def secure_data(self, conn):
        """Encrypt the data connection (after the 150 reply, as real servers do); None when the client did not resume the control TLS session."""
        if not (self.tls and self.prot_p):
            return conn
        conn = self.s.context.wrap_socket(conn, server_side=True)
        if self.s.require_reuse and not conn.session_reused:
            conn.close()
            self.send("425 unable to build data connection: TLS session of data connection not reused")
            return None
        return conn

    def finish(self, conn) -> None:
        try:
            if isinstance(conn, ssl.SSLSocket):
                try:
                    conn = conn.unwrap()
                except (OSError, ssl.SSLError):
                    pass
            conn.close()
        except OSError:
            pass
        self.send("226 transfer complete")

    def unix_line(self, path: str, name: str) -> str:
        st = os.stat(path)
        when = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%b %d %H:%M")
        kind = "d" if os.path.isdir(path) else "-"
        return f"{kind}rw-r--r-- 1 owner group {st.st_size if kind == '-' else 4096} {when} {name}"

    def dos_line(self, path: str, name: str) -> str:
        st = os.stat(path)
        when = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%m-%d-%y  %I:%M%p")
        return f"{when} {'<DIR>' if os.path.isdir(path) else st.st_size:>14} {name}"

    def facts(self, path: str) -> str:
        st = os.stat(path)
        kind = "dir" if os.path.isdir(path) else "file"
        mod = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y%m%d%H%M%S")
        size = f"size={st.st_size};" if kind == "file" else ""
        return f"type={kind};{size}modify={mod};unix.mode=0644;"

    def do_LIST(self, arg: str) -> None:
        target = self.real(arg) if arg and not arg.startswith("-") else self.real(self.cwd)
        if not os.path.isdir(target):
            return self.send("550 no such directory")
        conn = self.data()
        if conn is None:
            return
        self.send("150 here comes the listing")
        conn = self.secure_data(conn)
        if conn is None:
            return
        make = self.dos_line if self.s.dos_list else self.unix_line
        for name in sorted(os.listdir(target)):
            conn.sendall((make(os.path.join(target, name), name) + "\r\n").encode("utf-8"))
        self.finish(conn)

    def do_MLSD(self, arg: str) -> None:
        if not self.s.mlsd:
            return self.send("500 unknown command")
        target = self.real(arg) if arg else self.real(self.cwd)
        if not os.path.isdir(target):
            return self.send("550 no such directory")
        conn = self.data()
        if conn is None:
            return
        self.send("150 here comes the listing")
        conn = self.secure_data(conn)
        if conn is None:
            return
        for name in sorted(os.listdir(target)):
            conn.sendall(f"{self.facts(os.path.join(target, name))} {name}\r\n".encode("utf-8"))
        self.finish(conn)

    def do_MLST(self, arg: str) -> None:
        if not self.s.mlsd:
            return self.send("500 unknown command")
        target = self.real(arg)
        if not os.path.exists(target):
            return self.send("550 no such file")
        self.send("250-listing")
        self.send(f" {self.facts(target)} {os.path.basename(target)}")
        self.send("250 End")

    def do_REST(self, arg: str) -> None:
        self.rest = int(arg)
        self.send("350 restarting")

    def do_RETR(self, arg: str) -> None:
        target = self.real(arg)
        if not os.path.isfile(target):
            return self.send("550 no such file")
        conn = self.data()
        if conn is None:
            return
        self.send("150 sending")
        conn = self.secure_data(conn)
        if conn is None:
            return
        with open(target, "rb") as f:
            f.seek(self.rest)
            self.rest = 0
            while True:
                block = f.read(65536)
                if not block:
                    break
                try:
                    conn.sendall(block)
                except OSError:
                    break
        self.finish(conn)

    def do_STOR(self, arg: str) -> None:
        target = self.real(arg)
        if not os.path.isdir(os.path.dirname(target)):
            return self.send("550 no such directory")
        conn = self.data()
        if conn is None:
            return
        self.send("150 receiving")
        conn = self.secure_data(conn)
        if conn is None:
            return
        with open(target, "wb") as f:
            while True:
                try:
                    block = conn.recv(65536)
                except (OSError, ssl.SSLError):
                    break
                if not block:
                    break
                f.write(block)
        self.finish(conn)

    def do_DELE(self, arg: str) -> None:
        target = self.real(arg)
        if not os.path.isfile(target):
            return self.send("550 no such file")
        os.remove(target)
        self.send("250 deleted")

    def do_MKD(self, arg: str) -> None:
        target = self.real(arg)
        if os.path.exists(target):
            return self.send("550 file exists")
        if not os.path.isdir(os.path.dirname(target)):
            return self.send("550 no such directory")
        os.mkdir(target)
        self.send(f'257 "{self.virtual(arg)}" created')

    def do_RMD(self, arg: str) -> None:
        target = self.real(arg)
        if not os.path.isdir(target):
            return self.send("550 no such directory")
        if os.listdir(target):
            return self.send("550 directory not empty")
        os.rmdir(target)
        self.send("250 removed")

    def do_RNFR(self, arg: str) -> None:
        if not os.path.exists(self.real(arg)):
            return self.send("550 no such file")
        self.rnfr = self.real(arg)
        self.send("350 ready for RNTO")

    def do_RNTO(self, arg: str) -> None:
        target = self.real(arg)
        if os.path.exists(target):
            return self.send("553 target exists")
        os.rename(self.rnfr, target)
        self.send("250 renamed")

    def do_MFMT(self, arg: str) -> None:
        if not self.s.mfmt:
            return self.send("500 unknown command")
        stamp, _sp, name = arg.partition(" ")
        target = self.real(name)
        if not os.path.exists(target):
            return self.send("550 no such file")
        t = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        os.utime(target, (t, t))
        self.send(f"213 Modify={stamp}; {name}")
