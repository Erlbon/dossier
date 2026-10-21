"""Loading and saving a text file for the notepad without changing what the user did not touch.

What survives a load and a save: the encoding, the byte-order mark, and the kind of line break
(Windows, Unix or old Mac). The text is edited with plain ``\\n`` line breaks and converted back on
save. Saving writes a temporary file beside the original and replaces it, so a failed save never
leaves a half-written file, and it refuses when the file changed on disk since it was loaded unless
told to go ahead.
"""
from __future__ import annotations

import codecs
import os
from dataclasses import dataclass, replace
from typing import Optional

from .fsretry import replace_with_retry
from .platform import longpath
from .textview import AUTO, detect_encoding, looks_binary

MAX_EDIT_BYTES = 10 * 1024 * 1024
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"),
)


class FileTooLarge(Exception):
    """Over the editing cap; open it in the viewer or an external editor."""


class BinaryFile(Exception):
    """Zero bytes in something that is not wide text: probably not a text file."""


class EncodingProblem(Exception):
    """The text cannot be written in the file's encoding (a character it has no code for)."""

    def __init__(self, message: str, position: int = -1, char: str = "") -> None:
        super().__init__(message)
        self.position = position
        self.char = char


class FileChangedOnDisk(Exception):
    """Another program changed the file after it was opened here."""


@dataclass(frozen=True)
class Document:
    path: str
    text: str                  # line breaks are \n
    encoding: str
    bom: bytes = b""
    eol: str = "\n"            # what to write back: \r\n, \n or \r
    mixed_eol: bool = False    # the file had more than one kind
    size: int = 0
    mtime_ns: int = 0


def _split_bom(data: bytes) -> tuple:
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return bom, enc, data[len(bom):]
    return b"", "", data


def _dominant_eol(text: str) -> tuple:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    kinds = [(crlf, "\r\n"), (lf, "\n"), (cr, "\r")]
    used = [k for k in kinds if k[0] > 0]
    if not used:
        return "\n", False
    return max(used)[1], len(used) > 1


def load_document(path: str, encoding: str = AUTO, max_bytes: int = MAX_EDIT_BYTES) -> Document:
    real = longpath(path)
    st = os.stat(real)
    if st.st_size > max_bytes:
        raise FileTooLarge(f"{st.st_size // (1024 * 1024)} MB is over the {max_bytes // (1024 * 1024)} MB editing limit")
    with open(real, "rb") as f:
        data = f.read()
    bom, bom_enc, body = _split_bom(data)
    if encoding != AUTO:
        enc = encoding
    elif bom_enc:
        enc = bom_enc
    else:
        guess = detect_encoding(body[:65536])
        enc = {"utf-16": "utf-16-le", "utf-32": "utf-32-le"}.get(guess, guess)
    if not enc.startswith(("utf-16", "utf-32")) and looks_binary(body, enc):
        raise BinaryFile("This looks like a binary file")
    try:
        text = body.decode(enc)
    except UnicodeDecodeError:
        if encoding != AUTO:
            raise EncodingProblem(f"The file is not valid {encoding}") from None
        enc = "windows-1252"
        try:
            text = body.decode(enc)
        except UnicodeDecodeError:
            enc = "iso-8859-1"                    # takes every byte, so nothing is ever lost
            text = body.decode(enc)
    if bom and enc != bom_enc:
        bom = b""                                  # the user forced another encoding: that BOM no longer applies
    eol, mixed = _dominant_eol(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return Document(path, text, enc, bom, eol, mixed, st.st_size, st.st_mtime_ns)


def encode_text(doc: Document, text: str) -> bytes:
    """The bytes to write for ``text``: line breaks restored, BOM first, strictly encoded."""
    out = text.replace("\n", doc.eol) if doc.eol != "\n" else text
    try:
        return doc.bom + out.encode(doc.encoding)
    except UnicodeEncodeError as e:
        raise EncodingProblem(f"'{out[e.start]}' cannot be written in {doc.encoding}", e.start, out[e.start]) from None


def save_document(doc: Document, text: str, *, force: bool = False) -> Document:
    """Write ``text`` over the file. Returns the document as it now is on disk."""
    real = longpath(doc.path)
    if not force:
        try:
            st = os.stat(real)
        except FileNotFoundError:
            st = None
        if st is not None and (st.st_size != doc.size or st.st_mtime_ns != doc.mtime_ns):
            raise FileChangedOnDisk("The file was changed by another program after you opened it")
    payload = encode_text(doc, text)
    temp = real + ".dossier-save"
    try:
        with open(temp, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(temp, os.stat(real).st_mode)
        except OSError:
            pass
        replace_with_retry(temp, real)               # a virus scanner may hold the new file for a moment
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    st = os.stat(real)
    return replace(doc, text=text, size=st.st_size, mtime_ns=st.st_mtime_ns)


def convert_eol(doc: Document, eol: str) -> Document:
    """The same document that will be written with another kind of line break."""
    return replace(doc, eol=eol, mixed_eol=False)
