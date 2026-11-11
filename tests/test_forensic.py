"""Forensic listings (core/forensic.py: shortcuts, Recycle Bin records, property lists) and document properties
(core/docprops.py), docs/reader-review-2026-11-11.md cards 14, 15, 17 and 18. Every test file is built here: a real shortcut
carries the maker's machine name and MAC address, and a real Office file the name of whoever saved it last."""
import datetime as dt
import plistlib
import struct
import uuid
import zipfile

import pytest

from dossier.core import docprops, forensic, officesheet as osh, viewmodes as vm
from dossier.core.officedoc import DocumentError

FILETIME_2024 = (dt.datetime(2024, 11, 11, 14, 30, 5, tzinfo=dt.timezone.utc)
                 - dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)) // dt.timedelta(microseconds=1) * 10


def fields(book, sheet=0):
    return {r[0]: r[1] for r in book.sheets[sheet].rows[1:]}


# shortcuts --------------------------------------------------------------------------------------------------------------------------
def shell_item_file(short: str, long: str) -> bytes:
    """A file entry shell item with a version 9 0xBEEF0004 block holding the long name (as Windows 10 writes it)."""
    # after the size: type, a spare byte, file size, DOS date, attributes; the short name at offset 14 of the item
    head = bytes([0x32, 0]) + b"\x00" * 4 + b"\x00" * 4 + b"\x00\x00" + short.encode() + b"\x00"
    if len(head) % 2:
        head += b"\x00"
    long_bytes = long.encode("utf-16-le") + b"\x00\x00"
    block_body = struct.pack("<HHI", 0, 9, 0xBEEF0004) + b"\x00" * (46 - 8) + long_bytes + b"\x00\x00"
    block = struct.pack("<H", len(block_body)) + block_body[2:]
    item = head + block
    return struct.pack("<H", len(item) + 2) + item


def make_lnk(path, with_info=True):
    flags = 0x1 | 0x4 | 0x10 | 0x20 | 0x80 | (0x2 if with_info else 0)
    header = (struct.pack("<I", 0x4C) + forensic.LNK_MAGIC[4:20]
              + struct.pack("<IIQQQIiIH", flags, 0x20, FILETIME_2024, FILETIME_2024, FILETIME_2024, 12345, 0, 1, 0) + b"\x00" * 10)
    drive = struct.pack("<H", 25) + bytes([0x2F]) + b"C:\\" + b"\x00" * 19
    items = (struct.pack("<H", 20) + bytes([0x1F, 0x50]) + uuid.UUID("20d04fe0-3aea-1069-a2d8-08002b30309d").bytes_le
             + drive + shell_item_file("VRAKKA~1.TXT", "Vrakkart 1910.txt") + b"\x00\x00")
    id_list = struct.pack("<H", len(items)) + items
    info = b""
    if with_info:
        volume = struct.pack("<IIII", 0x10 + 8, 3, 0xCA88EA30, 0x10) + b"Data\x00\x00\x00\x00"
        base = b"D:\\Vrak\\Vrakkart 1910.txt\x00"
        header_size = 0x1C
        vol_off = header_size
        base_off = vol_off + len(volume)
        suffix_off = base_off + len(base)
        body = volume + base + b"\x00"
        info = struct.pack("<IIIIIII", header_size + len(body), header_size, 1, vol_off, base_off, 0, suffix_off) + body
    def s(text):
        return struct.pack("<H", len(text)) + text.encode("utf-16-le")
    strings = s("Wreck chart") + s("D:\\Vrak") + s("--open map")
    machine = b"WRECKPC" + b"\x00" * 9
    file_droid = uuid.UUID(fields=(0x12345678, 0x1234, 0x11EF, 0x80, 0x01, 0x001122334455))       # version 1: MAC + time
    vol_droid = uuid.uuid4()
    tracker = (struct.pack("<IIII", 0x60, 0xA0000003, 0x58, 0) + machine + vol_droid.bytes_le + file_droid.bytes_le
               + vol_droid.bytes_le + file_droid.bytes_le)
    path.write_bytes(header + id_list + info + strings + tracker + b"\x00\x00\x00\x00")
    return str(path)


def test_a_shortcut_gives_its_target_the_targets_times_the_drive_and_the_machine_it_was_made_on(tmp_path):
    lnk = make_lnk(tmp_path / "Vrakkart.lnk")
    book = osh.read_workbook(lnk)
    assert book.kind == "Windows shortcut"
    f = fields(book)
    assert f["Target"] == "D:\\Vrak\\Vrakkart 1910.txt"
    assert f["Target from the item list"] == "C:\\Vrakkart 1910.txt"          # the item list says otherwise: both shown
    assert f["Arguments"] == "--open map" and f["Working folder"] == "D:\\Vrak" and f["Description"] == "Wreck chart"
    assert f["Target modified"] == "2024-11-11 14:30:05 UTC" and f["Target size"] == "12.1 K (12,345 bytes)"
    assert f["Drive type"] == "fixed" and f["Drive serial number"] == "CA88-EA30" and f["Drive label"] == "Data"
    assert f["Machine (NetBIOS name)"] == "WRECKPC"
    assert f["MAC address in the file's object id"] == "00:11:22:33:44:55"
    assert f["Time in the file's object id"].endswith("UTC")
    assert vm.mode_for(lnk) == "sheet" and not vm.opens_in_viewer(lnk, "viewer")      # Enter still runs the target


def test_a_shortcut_without_link_info_takes_its_target_from_the_item_list(tmp_path):
    f = fields(osh.read_workbook(make_lnk(tmp_path / "x.lnk", with_info=False)))
    assert f["Target"] == "C:\\Vrakkart 1910.txt" and "Target from the item list" not in f
    (tmp_path / "cut.lnk").write_bytes(open(tmp_path / "x.lnk", "rb").read()[:90])
    with pytest.raises(DocumentError):
        osh.read_workbook(str(tmp_path / "cut.lnk"))


# Recycle Bin ------------------------------------------------------------------------------------------------------------------------
def test_recycle_bin_records_of_both_versions_and_whether_the_copy_is_still_there(tmp_path):
    path = "C:\\Users\\someone\\Documents\\Vrakkart 1910.docx"
    v2 = tmp_path / "$IAB12CD.docx"
    v2.write_bytes(struct.pack("<QQQI", 2, 54321, FILETIME_2024, len(path) + 1) + (path + "\x00").encode("utf-16-le"))
    (tmp_path / "$RAB12CD.docx").write_bytes(b"x")
    f = fields(osh.read_workbook(str(v2)))
    assert f["Original path"] == path and f["Original name"] == "Vrakkart 1910.docx"
    assert f["Deleted"] == "2024-11-11 14:30:05 UTC" and "54,321 bytes" in f["Size"]
    assert "beside this record" in f["The deleted file's copy"] and "version 2" in f["Record format"]
    v1 = tmp_path / "$IZZ.txt"
    v1.write_bytes(struct.pack("<QQQ", 1, 10, FILETIME_2024) + "D:\\a.txt".encode("utf-16-le").ljust(520, b"\x00"))
    f1 = fields(osh.read_workbook(str(v1)))
    assert f1["Original path"] == "D:\\a.txt" and "not here" in f1["The deleted file's copy"]
    other = tmp_path / "$Inot-a-record.txt"
    other.write_text("just a file whose name starts with $I")
    assert vm.mode_for(str(other)) == "text"


# property lists ---------------------------------------------------------------------------------------------------------------------
PLIST = {"Name": "Vrakkart", "Count": 3, "Ratio": 0.5, "On": True, "When": dt.datetime(2024, 11, 11, 14, 30, 5),
         "Blob": b"\x01\x02\x03", "Items": ["a", {"Deep": 1}]}


@pytest.mark.parametrize("fmt", [plistlib.FMT_BINARY, plistlib.FMT_XML])
def test_a_property_list_is_flattened_to_key_paths_types_and_values(tmp_path, fmt):
    path = tmp_path / ("x.plist" if fmt == plistlib.FMT_XML else "noext")
    path.write_bytes(plistlib.dumps(PLIST, fmt=fmt))
    book = osh.read_workbook(str(path))
    assert book.kind == "Property list"
    rows = {r[0]: (r[1], r[2]) for r in book.sheets[0].rows[1:]}
    assert rows["(top)"] == ("dictionary", "7 keys")
    assert rows["Name"] == ("string", "Vrakkart") and rows["Count"] == ("integer", "3") and rows["On"] == ("boolean", "true")
    assert rows["When"] == ("date", "2024-11-11 14:30:05 UTC") and rows["Blob"] == ("data", "3 bytes: 01 02 03")
    assert rows["Items"] == ("array", "2 items") and rows["Items[1]/Deep"] == ("integer", "1")
    assert vm.opens_in_viewer(str(path), "viewer") == (fmt == plistlib.FMT_XML)       # an XML plist is text: it stays


def test_a_hostile_or_broken_property_list_is_an_error(tmp_path):
    bomb = tmp_path / "b.plist"
    bomb.write_bytes(b'<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY a "aaaa">]><plist><string>&a;</string></plist>')
    with pytest.raises(DocumentError):
        osh.read_workbook(str(bomb))
    broken = tmp_path / "c.plist"
    broken.write_bytes(b"bplist00" + b"\xff" * 40)
    with pytest.raises(DocumentError):
        osh.read_workbook(str(broken))


# document properties ----------------------------------------------------------------------------------------------------------------
def test_office_2007_properties_author_last_saved_by_dates_and_editing_time(tmp_path):
    path = tmp_path / "a.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>")
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
                   "<dc:creator>Ola Nordmann</dc:creator><cp:lastModifiedBy>Kari</cp:lastModifiedBy><cp:revision>7</cp:revision>"
                   "<dcterms:created>2024-11-11T14:30:05Z</dcterms:created><cp:lastPrinted>2024-11-12T08:00:00Z</cp:lastPrinted>"
                   "</cp:coreProperties>")
        z.writestr("docProps/app.xml", '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                   "<TotalTime>135</TotalTime><Company>Sjøkart AS</Company><Application>Microsoft Office Word</Application>"
                   "<Template>Normal.dotm</Template></Properties>")
    p = dict(docprops.properties(str(path)))
    assert p["Author"] == "Ola Nordmann" and p["Last saved by"] == "Kari" and p["Revision"] == "7"
    assert p["Created"] == "2024-11-11 14:30:05 UTC" and p["Last printed"] == "2024-11-12 08:00:00 UTC"
    assert p["Total editing time"] == "2 h 15 min" and p["Company"] == "Sjøkart AS" and p["Template"] == "Normal.dotm"


def test_opendocument_epub_and_rtf_properties(tmp_path):
    odt = tmp_path / "a.odt"
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("content.xml", "<x/>")
        z.writestr("meta.xml", '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   "<office:meta><meta:initial-creator>Ola</meta:initial-creator><dc:creator>Kari</dc:creator>"
                   "<meta:editing-duration>PT1H5M3S</meta:editing-duration><meta:editing-cycles>4</meta:editing-cycles>"
                   "<meta:generator>LibreOffice/24.8</meta:generator></office:meta></office:document-meta>")
    p = dict(docprops.properties(str(odt)))
    assert p["Author"] == "Ola" and p["Last saved by"] == "Kari" and p["Total editing time"] == "1 h 5 min"
    assert p["Revision"] == "4" and p["Program"] == "LibreOffice/24.8"
    from tests.test_readers import make_epub
    epub = make_epub(tmp_path / "b.epub", metadata='<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Vrak</dc:title>'
                                                   "<dc:creator>Ola</dc:creator><dc:publisher>Forlag</dc:publisher></metadata>")
    p = dict(docprops.properties(epub))
    assert p["Title"] == "Vrak" and p["Author"] == "Ola" and p["Publisher"] == "Forlag"
    rtf = tmp_path / "c.rtf"
    rtf.write_bytes(b"{\\rtf1{\\info{\\title Vrak}{\\author Ola}{\\operator Kari}{\\creatim\\yr2024\\mo11\\dy11\\hr14\\min30}"
                    b"\\version3\\edmins75}text}")
    p = dict(docprops.properties(str(rtf)))
    assert p["Title"] == "Vrak" and p["Author"] == "Ola" and p["Last saved by"] == "Kari"
    assert p["Created"].startswith("2024-11-11 14:30") and p["Revision"] == "3" and p["Total editing time"] == "1 h 15 min"


def property_set(props: dict) -> bytes:
    """A SummaryInformation stream: one section, code page 1252, the given (pid -> str | int | ('filetime', n)) values."""
    values = []
    for pid, v in [(1, 1252)] + list(props.items()):
        if pid == 1:
            values.append((pid, struct.pack("<HHh", 2, 0, v) + b"\x00\x00"))
        elif isinstance(v, tuple):
            values.append((pid, struct.pack("<HHQ", 64, 0, v[1])))
        elif isinstance(v, int):
            values.append((pid, struct.pack("<HHi", 3, 0, v)))
        else:
            raw = v.encode("cp1252") + b"\x00"
            raw += b"\x00" * (-len(raw) % 4)
            values.append((pid, struct.pack("<HHI", 30, 0, len(raw)) + raw))
    table_size = 8 + 8 * len(values)
    offsets, body, pos = [], b"", table_size
    for pid, raw in values:
        offsets.append(struct.pack("<II", pid, pos))
        body += raw
        pos += len(raw)
    section = struct.pack("<II", table_size + len(body), len(values)) + b"".join(offsets) + body
    header = struct.pack("<HHI", 0xFFFE, 0, 0) + b"\x00" * 16 + struct.pack("<I", 1)
    return header + uuid.UUID("f29f85e0-4ff9-1068-ab91-08002b27b3d9").bytes_le + struct.pack("<I", 48) + section


def make_cfb(path, streams: dict) -> str:
    """A minimal Office 97 container: 512-byte sectors, one FAT sector, one directory sector, every stream padded to 4096 bytes
    (so none lives in the mini stream)."""
    end, free, fat_sect = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
    fat = [fat_sect, end]
    data = b""
    entries = []
    next_sector = 2
    for name, raw in streams.items():
        raw = raw.ljust(max(4096, (len(raw) + 511) // 512 * 512), b"\x00")
        count = len(raw) // 512
        fat += [next_sector + i + 1 for i in range(count - 1)] + [end]
        entries.append((name, next_sector, len(raw)))
        next_sector += count
        data += raw
    def entry(name, kind, left, right, child, start, size):
        n = (name + "\x00").encode("utf-16-le")
        return (n.ljust(64, b"\x00") + struct.pack("<HBB", len(n), kind, 1) + struct.pack("<III", left, right, child)
                + b"\x00" * 36 + struct.pack("<IQ", start, size))
    directory = entry("Root Entry", 5, free, free, 1, end, 0)
    for i, (name, start, size) in enumerate(entries, 1):
        directory += entry(name, 2, free, i + 1 if i < len(entries) else free, free, start, size)
    directory = directory.ljust(512, b"\x00")
    header = (forensic.LNK_MAGIC[:0] + b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
              + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
              + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, end, 0, end, 0) + struct.pack("<I", 0) + b"\xff" * 432)
    fat_bytes = struct.pack("<%dI" % len(fat), *fat).ljust(512, b"\xff")
    path.write_bytes(header + fat_bytes + directory + data)
    return str(path)


def test_office_97_property_sets_are_read_from_the_container(tmp_path):
    summary = property_set({4: "Ola Nordmann", 8: "Kari", 9: "12", 10: ("filetime", 95 * 600_000_000),
                            12: ("filetime", FILETIME_2024), 18: "Microsoft Office Word", 14: 3})
    doc = make_cfb(tmp_path / "a.doc", {"WordDocument": b"\xec\xa5" + b"\x00" * 100, "\x05SummaryInformation": summary})
    p = dict(docprops.properties(doc))
    assert p["Author"] == "Ola Nordmann" and p["Last saved by"] == "Kari" and p["Revision"] == "12"
    assert p["Total editing time"] == "1 h 35 min" and p["Created"] == "2024-11-11 14:30:05 UTC"
    assert p["Program"] == "Microsoft Office Word" and p["Pages"] == "3"
    assert docprops.properties(str(tmp_path / "missing.doc")) == []                   # never raises
