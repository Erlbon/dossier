"""A document's own record of where it came from, for the viewer's Info panel: author, last saved by, created, modified and printed
dates, revision, total editing time, the program, company and template. Read only; every value as the file stores it, times in UTC.

Office 2007 and later (.docx, .xlsx, .pptx): ``docProps/core.xml`` and ``docProps/app.xml``. OpenDocument: ``meta.xml``. EPUB: the
package file's Dublin Core metadata. Office 97 (.doc, .xls, .ppt): the SummaryInformation and DocumentSummaryInformation property
sets, through ``officedoc.Compound``. RTF: its ``\\info`` group. A PDF's are read by Qt on the viewer's side.

``properties(path)`` gives ``[(label, value)]`` (empty for a file kind without properties or a file that has none); it never raises.
Only the standard library; Qt-free.
"""
from __future__ import annotations

import datetime as dt
import re
import struct
import zipfile

from .forensic import filetime
from .officedoc import OLE_MAGIC, ZIP_MAGIC, Compound, DocumentError, _xml

CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
DC = "{http://purl.org/dc/elements/1.1/}"
DCTERMS = "{http://purl.org/dc/terms/}"
EP = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
META = "{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
OPF = "{http://www.idpf.org/2007/opf}"


def properties(path: str) -> list:
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head.startswith(OLE_MAGIC):
            return _ole(path)
        if head.startswith(b"{\\rt"):
            return _rtf(path)
        if head.startswith(ZIP_MAGIC):
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                if "docProps/core.xml" in names or "docProps/app.xml" in names:
                    return _ooxml(z)
                if "meta.xml" in names:
                    return _odf(z)
                if "META-INF/container.xml" in names:
                    return _epub(z)
    except (OSError, zipfile.BadZipFile, DocumentError, struct.error, IndexError, ValueError, KeyError):
        pass
    return []


def _when(text: str) -> str:
    """An ISO time as ``2026-11-11 14:30:05 UTC`` when it is in UTC (``Z``), else as stored."""
    text = (text or "").strip()
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)(?:\.\d+)?Z", text)
    return f"{m.group(1)} {m.group(2)} UTC" if m else text.replace("T", " ")


def _minutes(n: int) -> str:
    if n <= 0:
        return ""
    h, m = divmod(n, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def _text(root, tag: str) -> str:
    el = root.find(tag) if root is not None else None
    return (el.text or "").strip() if el is not None else ""


def _ooxml(z: zipfile.ZipFile) -> list:
    core = _xml(z, "docProps/core.xml")
    app = _xml(z, "docProps/app.xml")
    total = _text(app, EP + "TotalTime")
    rows = [("Title", _text(core, DC + "title")), ("Subject", _text(core, DC + "subject")),
            ("Author", _text(core, DC + "creator")), ("Last saved by", _text(core, CP + "lastModifiedBy")),
            ("Created", _when(_text(core, DCTERMS + "created"))), ("Modified", _when(_text(core, DCTERMS + "modified"))),
            ("Last printed", _when(_text(core, CP + "lastPrinted"))), ("Revision", _text(core, CP + "revision")),
            ("Total editing time", _minutes(int(total)) if total.isdigit() else total),
            ("Keywords", _text(core, CP + "keywords")), ("Comments", _text(core, DC + "description")),
            ("Category", _text(core, CP + "category")), ("Status", _text(core, CP + "contentStatus")),
            ("Company", _text(app, EP + "Company")), ("Manager", _text(app, EP + "Manager")),
            ("Template", _text(app, EP + "Template")),
            ("Program", " ".join(x for x in (_text(app, EP + "Application"), _text(app, EP + "AppVersion")) if x)),
            ("Pages", _text(app, EP + "Pages")), ("Words", _text(app, EP + "Words")), ("Slides", _text(app, EP + "Slides")),
            ("Hidden slides", _text(app, EP + "HiddenSlides"))]
    return [(k, v) for k, v in rows if v]


def _duration(text: str) -> str:
    """An ISO 8601 duration (``P1DT2H3M4S``) as hours and minutes."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", (text or "").strip())
    if not m:
        return text or ""
    days, hours, mins = (int(g or 0) for g in m.groups()[:3])
    return _minutes(days * 1440 + hours * 60 + mins) or ("under a minute" if m.group(4) else "")


def _odf(z: zipfile.ZipFile) -> list:
    meta = _xml(z, "meta.xml")
    m = meta.find(OFFICE + "meta") if meta is not None else None
    stats = m.find(META + "document-statistic") if m is not None else None
    rows = [("Title", _text(m, DC + "title")), ("Subject", _text(m, DC + "subject")),
            ("Author", _text(m, META + "initial-creator")), ("Last saved by", _text(m, DC + "creator")),
            ("Created", _when(_text(m, META + "creation-date"))), ("Modified", _when(_text(m, DC + "date"))),
            ("Last printed", _when(_text(m, META + "print-date"))), ("Printed by", _text(m, META + "printed-by")),
            ("Revision", _text(m, META + "editing-cycles")), ("Total editing time", _duration(_text(m, META + "editing-duration"))),
            ("Keywords", ", ".join((k.text or "") for k in m.findall(META + "keyword")) if m is not None else ""),
            ("Comments", _text(m, DC + "description")), ("Program", _text(m, META + "generator")),
            ("Pages", stats.get(META + "page-count", "") if stats is not None else ""),
            ("Words", stats.get(META + "word-count", "") if stats is not None else "")]
    template = m.find(META + "template") if m is not None else None
    if template is not None:
        rows.append(("Template", template.get("{http://www.w3.org/1999/xlink}href", "")))
    return [(k, v) for k, v in rows if v]


def _epub(z: zipfile.ZipFile) -> list:
    container = _xml(z, "META-INF/container.xml")
    opf_path = next((e.get("full-path") for e in (container.iter() if container is not None else [])
                     if e.tag.endswith("rootfile") and e.get("full-path")), "")
    opf = _xml(z, opf_path) if opf_path else None
    md = opf.find(OPF + "metadata") if opf is not None else None
    if md is None:
        return []
    rows = []
    for tag, label in (("title", "Title"), ("creator", "Author"), ("contributor", "Contributor"), ("publisher", "Publisher"),
                       ("date", "Date"), ("language", "Language"), ("identifier", "Identifier"), ("subject", "Subject"),
                       ("rights", "Rights"), ("source", "Source")):
        for el in md.findall(DC + tag):
            if (el.text or "").strip():
                rows.append((label, el.text.strip()))
    for el in md.findall(OPF + "meta"):
        if el.get("property") == "dcterms:modified" and (el.text or "").strip():
            rows.append(("Modified", _when(el.text)))
    rows.append(("EPUB version", opf.get("version", "")))
    return [(k, v) for k, v in rows if v]


# Office 97 property sets ----------------------------------------------------------------------------------------------------------
SUMMARY = {2: "Title", 3: "Subject", 4: "Author", 5: "Keywords", 6: "Comments", 7: "Template", 8: "Last saved by",
           9: "Revision", 10: "Total editing time", 11: "Last printed", 12: "Created", 13: "Modified", 14: "Pages",
           15: "Words", 18: "Program"}
DOC_SUMMARY = {2: "Category", 14: "Manager", 15: "Company"}


def _property_set(data: bytes) -> dict:
    """Property id -> value of the first section of a property set stream (strings, numbers and times)."""
    if len(data) < 48:
        return {}
    offset, = struct.unpack_from("<I", data, 44)
    _size, count = struct.unpack_from("<II", data, offset)
    entries = [struct.unpack_from("<II", data, offset + 8 + 8 * i) for i in range(min(count, 512))]
    codepage = "cp1252"
    out = {}
    for pid, off in entries:
        pos = offset + off
        vt, = struct.unpack_from("<H", data, pos)
        if pid == 1 and vt == 2:
            cp = struct.unpack_from("<h", data, pos + 4)[0] & 0xFFFF
            codepage = "utf-8" if cp == 65001 else "utf-16-le" if cp == 1200 else f"cp{cp}"
    for pid, off in entries:
        pos = offset + off
        vt, = struct.unpack_from("<H", data, pos)
        if vt == 30:                                     # a string in the set's code page
            n, = struct.unpack_from("<I", data, pos + 4)
            try:
                out[pid] = data[pos + 8:pos + 8 + n].decode(codepage, "replace").rstrip("\x00")
            except LookupError:
                out[pid] = data[pos + 8:pos + 8 + n].decode("cp1252", "replace").rstrip("\x00")
        elif vt == 31:                                   # a UTF-16 string
            n, = struct.unpack_from("<I", data, pos + 4)
            out[pid] = data[pos + 8:pos + 8 + 2 * n].decode("utf-16-le", "replace").rstrip("\x00")
        elif vt == 3:
            out[pid] = struct.unpack_from("<i", data, pos + 4)[0]
        elif vt == 2:
            out[pid] = struct.unpack_from("<h", data, pos + 4)[0]
        elif vt == 64:
            out[pid] = ("filetime", struct.unpack_from("<Q", data, pos + 4)[0])
    return out


def _ole(path: str) -> list:
    rows = []
    with Compound(path) as cf:
        summary = _property_set(cf.stream("\x05SummaryInformation")) if cf.has("\x05SummaryInformation") else {}
        doc_summary = (_property_set(cf.stream("\x05DocumentSummaryInformation"))
                       if cf.has("\x05DocumentSummaryInformation") else {})
    for pid, label in SUMMARY.items():
        v = summary.get(pid)
        if isinstance(v, tuple):
            v = _minutes(v[1] // 600_000_000) if pid == 10 else filetime(v[1])
        if v not in (None, "", 0):
            rows.append((label, str(v)))
    for pid, label in DOC_SUMMARY.items():
        v = doc_summary.get(pid)
        if v:
            rows.append((label, str(v)))
    return rows


# RTF -------------------------------------------------------------------------------------------------------------------------------
def _rtf(path: str) -> list:
    with open(path, "rb") as f:
        head = f.read(256 * 1024)
    start = head.find(b"{\\info")
    if start < 0:
        return []
    depth, end = 0, start
    while end < len(head):                               # to the brace that closes {\info ...}, past the groups inside it
        c = head[end:end + 1]
        if c == b"\\":
            end += 2
            continue
        depth += 1 if c == b"{" else -1 if c == b"}" else 0
        end += 1
        if depth == 0:
            break
    info = head[start:end]

    def field(name: bytes) -> str:
        f = re.search(rb"\{\\" + name + rb" ([^{}]*)\}", info)
        return f.group(1).decode("cp1252", "replace").strip() if f else ""

    def stamp(name: bytes) -> str:
        f = re.search(rb"\{\\" + name + rb"((?:\\[a-z]+\d+)+)\}", info)
        if not f:
            return ""
        parts = dict((k.decode(), int(v)) for k, v in re.findall(rb"\\([a-z]+)(\d+)", f.group(1)))
        try:
            return dt.datetime(parts.get("yr", 1), parts.get("mo", 1), parts.get("dy", 1), parts.get("hr", 0),
                               parts.get("min", 0)).strftime("%Y-%m-%d %H:%M (local time of the writer)")
        except ValueError:
            return ""

    def number(name: bytes) -> str:
        f = re.search(rb"\\" + name + rb"(\d+)", info)
        return f.group(1).decode() if f else ""

    edmins = number(b"edmins")
    rows = [("Title", field(b"title")), ("Subject", field(b"subject")), ("Author", field(b"author")),
            ("Last saved by", field(b"operator")), ("Company", field(b"company")), ("Created", stamp(b"creatim")),
            ("Modified", stamp(b"revtim")), ("Last printed", stamp(b"printim")), ("Revision", number(b"version")),
            ("Total editing time", _minutes(int(edmins)) if edmins else ""), ("Pages", number(b"nofpages")),
            ("Words", number(b"nofwords"))]
    return [(k, v) for k, v in rows if v]
