"""Readers for archive files, one per format family, behind one small interface (spec section 5, A1 and A2).

* zip      the standard library, always there;
* 7z       the ``py7zr`` package when it is installed (``pip install dossier[archives]``);
* the rest 7-Zip's command line (``7z``, ``7zz``, ``7za``) when it is on the PATH or in its usual folder:
           RAR, CAB, ISO, TAR, GZ, BZ2, XZ, ARJ, LZH and more. This is also the fallback for 7z.

An archive no reader can open is not an error: ``backend_for`` returns None and ``missing_reader`` says what
would open it, so the window can tell the user and hand the file to the system instead.

Nothing here writes to an archive. A member is read by a stream that cleans up after itself.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Optional

SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
RAR_MAGICS = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
EXTERNAL_EXTENSIONS = (".rar", ".cab", ".iso", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".arj", ".lzh",
                       ".lha", ".cpio", ".wim", ".z")
LIST_TIMEOUT = 300

# Enter on a file with one of these names opens it as a folder. Content alone is not enough: a Word document, an
# epub, a jar or a comic archive is a zip inside, but the user wants to open it, not to look inside. For those,
# "Open as Archive" (Ctrl+PageDown) looks at the content.
FOLDER_EXTENSIONS = (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".cab", ".iso",
                     ".arj", ".lzh", ".lha", ".cpio", ".wim", ".z")


@dataclass
class Member:
    name: str                 # with forward slashes, decoded
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    encrypted: bool = False
    ref: object = None        # what the reader needs to find it again


class ArchiveError(OSError):
    """The archive cannot be read (damaged, encrypted, or the tool failed)."""


# zip -------------------------------------------------------------------------------------------------
def _zip_name(info: zipfile.ZipInfo) -> str:
    """The name as the user should see it. A name without the UTF-8 flag was stored in a code page: UTF-8 is
    tried first (many tools write it without the flag), then the Western European DOS page, which is what
    Windows' own zip writer used."""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp850", errors="replace")


class _Stream:
    """A read stream of one member that also releases what it came from (an archive handle, a process)."""

    def __init__(self, inner, *cleanups) -> None:
        self._inner, self._cleanups = inner, cleanups

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __iter__(self):
        return iter(self._inner)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            cleanups, self._cleanups = self._cleanups, ()
            for fn in cleanups:
                try:
                    fn()
                except OSError:
                    pass


class ZipBackend:
    label = "zip"

    def members(self, archive: str) -> list:
        out = []
        try:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    try:
                        mtime = time.mktime(info.date_time + (0, 0, -1))
                    except (OverflowError, ValueError):
                        mtime = 0.0
                    out.append(Member(_zip_name(info), info.is_dir(), info.file_size, mtime,
                                      bool(info.flag_bits & 0x1), info))
        except zipfile.BadZipFile as e:
            raise ArchiveError(f"not a readable zip archive: {e}") from e
        return out

    def open(self, archive: str, member: Member) -> BinaryIO:
        zf = zipfile.ZipFile(archive)
        try:
            return _Stream(zf.open(member.ref), zf.close)
        except (NotImplementedError, RuntimeError) as e:
            zf.close()
            raise ArchiveError(f"cannot read {os.path.basename(member.name)}: {e}") from e
        except BaseException:
            zf.close()
            raise


# 7z through py7zr ------------------------------------------------------------------------------------------
def have_py7zr() -> bool:
    try:
        import py7zr  # noqa: F401
        return True
    except ImportError:
        return False


class SevenZipBackend:
    """7z archives through the ``py7zr`` package. A member is extracted to a temporary folder (7z is usually
    solid: its data can only be unpacked in order) and read from there; the folder goes when the stream closes."""
    label = "7z (py7zr)"

    def members(self, archive: str) -> list:
        import py7zr
        try:
            with py7zr.SevenZipFile(archive) as z:
                out = []
                for f in z.list():
                    stamp = getattr(f, "creationtime", None)
                    try:
                        mtime = stamp.timestamp() if stamp else 0.0
                    except (OverflowError, OSError, ValueError):
                        mtime = 0.0
                    out.append(Member(f.filename.replace("\\", "/"), bool(f.is_directory), int(f.uncompressed or 0),
                                      mtime, False, f.filename))
                return out
        except py7zr.exceptions.PasswordRequired as e:
            raise ArchiveError("this archive is encrypted") from e
        except (py7zr.exceptions.ArchiveError, OSError, ValueError) as e:
            raise ArchiveError(f"not a readable 7z archive: {e}") from e

    def open(self, archive: str, member: Member) -> BinaryIO:
        import py7zr
        folder = tempfile.mkdtemp(prefix="dossier-7z-")
        try:
            with py7zr.SevenZipFile(archive) as z:
                z.extract(path=folder, targets=[member.ref])
            target = os.path.join(folder, *member.ref.replace("\\", "/").split("/"))
            return _Stream(open(target, "rb"), lambda: shutil.rmtree(folder, ignore_errors=True))
        except py7zr.exceptions.PasswordRequired as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise PermissionError(f"{os.path.basename(member.name)} is encrypted") from e
        except BaseException as e:
            shutil.rmtree(folder, ignore_errors=True)
            if isinstance(e, (OSError, KeyboardInterrupt)):
                raise
            raise ArchiveError(f"cannot read {os.path.basename(member.name)}: {e}") from e


# everything else through 7-Zip's command line ------------------------------------------------------------
_SEVEN_ZIP_NAMES = ("7z", "7zz", "7za", "7zr")
_SEVEN_ZIP_FOLDERS = (r"C:\Program Files\7-Zip", r"C:\Program Files (x86)\7-Zip")


def find_seven_zip() -> Optional[str]:
    for name in _SEVEN_ZIP_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for folder in _SEVEN_ZIP_FOLDERS:
        for name in _SEVEN_ZIP_NAMES:
            candidate = os.path.join(folder, name + ".exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def _quiet() -> dict:
    """Run a tool without a console window and without waiting for a keyboard answer (a password prompt)."""
    kwargs: dict = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000                 # CREATE_NO_WINDOW
    return kwargs


def parse_listing(text: str) -> list:
    """The output of ``7z l -slt -ba``: blocks of ``Key = Value`` lines, one block per member."""
    out, block = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if block.get("Path") and "Physical Size" not in block:        # that block describes the archive itself
                out.append(block)
            block = {}
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            block[key.strip()] = value
    members = []
    for b in out:
        name = b["Path"].replace("\\", "/")
        attrs = b.get("Attributes", "")
        is_dir = b.get("Folder") == "+" or attrs.startswith("D") or " D" in (" " + attrs)
        try:
            size = int(b.get("Size") or 0)
        except ValueError:
            size = 0
        try:
            mtime = time.mktime(time.strptime(b.get("Modified", "")[:19], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, OverflowError):
            mtime = 0.0
        members.append(Member(name, is_dir, size, mtime, b.get("Encrypted") == "+", b["Path"]))
    return members


class ExternalBackend:
    label = "7-Zip"

    def __init__(self, exe: str) -> None:
        self.exe = exe

    def members(self, archive: str) -> list:
        try:
            done = subprocess.run([self.exe, "l", "-slt", "-ba", "-sccUTF-8", "-y", "--", archive], capture_output=True,
                                  timeout=LIST_TIMEOUT, **_quiet())
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ArchiveError(f"7-Zip could not list the archive: {e}") from e
        text = done.stdout.decode("utf-8", errors="replace")
        if done.returncode not in (0, 1):                      # 1 is a warning (a damaged tail, for example)
            reason = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise ArchiveError("7-Zip could not read the archive" + (": " + reason[-1] if reason else ""))
        return parse_listing(text)

    def open(self, archive: str, member: Member) -> BinaryIO:
        process = subprocess.Popen([self.exe, "x", "-so", "-y", "-spd", "-sccUTF-8", "--", archive, member.ref],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_quiet())
        return _ProcessStream(process, member.name)


class _ProcessStream:
    """Standard output of a 7-Zip run as a file: ends with an error when 7-Zip failed (a wrong or missing
    password, a damaged archive), instead of looking like an empty file."""

    def __init__(self, process: subprocess.Popen, name: str) -> None:
        self._p, self._name = process, name
        self._checked = False

    def read(self, n: int = -1) -> bytes:
        data = self._p.stdout.read(n) if n is not None and n >= 0 else self._p.stdout.read()
        if not data and (n is None or n != 0):
            self._check()
        return data

    def _check(self) -> None:
        if self._checked:
            return
        self._checked = True
        code = self._p.wait()
        if code not in (0, 1):
            reason = self._p.stderr.read().decode("utf-8", errors="replace").strip().splitlines()
            text = reason[-1] if reason else f"exit code {code}"
            if "password" in " ".join(reason).lower() or "encrypted" in " ".join(reason).lower():
                raise PermissionError(f"{self._name} is encrypted")
            raise ArchiveError(f"cannot read {self._name}: {text}")

    def __iter__(self):
        while True:
            chunk = self.read(1 << 16)
            if not chunk:
                return
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._p.poll() is None:
            self._p.kill()
        for pipe in (self._p.stdout, self._p.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        self._p.wait()


# choosing a reader -----------------------------------------------------------------------------------------
def _magic(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(8)
    except OSError:
        return b""


def kind_of(path: str) -> str:
    """What the file looks like: ``zip``, ``7z``, ``rar``, ``other`` (an archive type by its name), or ``""``."""
    if not os.path.isfile(path):
        return ""
    head = _magic(path)
    if head.startswith(b"PK") and zipfile.is_zipfile(path):
        return "zip"
    if head.startswith(SEVEN_ZIP_MAGIC):
        return "7z"
    if any(head.startswith(m) for m in RAR_MAGICS):
        return "rar"
    return "other" if path.lower().endswith(EXTERNAL_EXTENSIONS) else ""


def backend_for(path: str):
    """A reader that can open this file, or None."""
    kind = kind_of(path)
    if kind == "zip":
        return ZipBackend()
    if kind == "7z" and have_py7zr():
        return SevenZipBackend()
    if kind:
        exe = find_seven_zip()
        if exe:
            return ExternalBackend(exe)
    return None


def missing_reader(path: str) -> str:
    """For an archive no reader can open: what would. Empty when the file is no archive or can be opened."""
    kind = kind_of(path)
    if not kind or backend_for(path) is not None:
        return ""
    name = os.path.basename(path)
    if kind == "7z":
        return f"{name} is a 7z archive. Install the py7zr package (pip install py7zr) or 7-Zip to open it as a folder."
    return f"{name} is an archive Dossier can open with 7-Zip, which was not found. Install 7-Zip (7-zip.org) to open it as a folder."


def opens_by_name(path: str) -> bool:
    """Whether Enter opens this file as a folder: an archive by its name, and readable as one."""
    return path.lower().endswith(FOLDER_EXTENSIONS) and backend_for(path) is not None


def missing_reader_by_name(path: str) -> str:
    """``missing_reader`` for a file whose name says archive; empty for every other file."""
    return missing_reader(path) if path.lower().endswith(FOLDER_EXTENSIONS) else ""
