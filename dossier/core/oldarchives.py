"""Old compressed files that 7-Zip cannot open, for the viewer's grid: what each one is, and for the simple ones what it holds.

Every format here is known by its first bytes (a weak two-byte signature also needs the usual name). ARC and PAK (DOS), ZOO,
ACE, HA and CP/M's LBR are listed from their headers alone: name, size, packed size, method, date, CRC, and the entries an
archiver marked as deleted but left in the file (ZOO, LBR). Nothing is unpacked: their packing methods are many and old, and a
listing is what tells what a file holds and how old it is. The rest (StuffIt, Amiga DMS and LZX, SQZ, CP/M squeezed and
crunched files, Unix pack and compact) are named, with the program that would open them.

Docs: docs/reader-review-2026-11-11.md (the owner's choice A, 2026-11-11). Only the standard library; Qt-free. Every header
read is bounded by the file's size and a member count, so a damaged file ends the listing, never hangs it.
"""
from __future__ import annotations

import datetime as dt
import os
import struct

from .officedoc import DocumentError
from .officesheet import MAX_CELLS, Sheet, _Grid
from .sizefmt import human_size

MAX_MEMBERS = 100_000
MAX_READ = 512 * 1024 * 1024

# (name, platform and years, what opens it)
FORMATS = {
    "arc": ("ARC archive (SEA ARC or PKPAK)", "DOS, 1985-1990", "unar or The Unarchiver; arc and nomarch on Linux"),
    "pak": ("PAK archive (NoGate PAK, an ARC variant)", "DOS, 1988-1990", "unar or The Unarchiver"),
    "zoo": ("ZOO archive", "DOS, Unix, Amiga, 1986-1991", "unar or The Unarchiver; zoo on Linux"),
    "ace": ("ACE archive", "DOS and Windows, 1998-2007", "unar or The Unarchiver; unace (7-Zip dropped it)"),
    "ha": ("HA archive", "DOS, 1993-1995", "unar or The Unarchiver"),
    "lbr": ("LBR library", "CP/M, 1982-1990", "lbrate or unar"),
    "sit": ("StuffIt archive", "Classic Mac OS, 1987-2010", "unar or The Unarchiver"),
    "dms": ("DMS disk image (Disk Masher)", "Amiga, 1990s", "unar or xdms"),
    "lzx": ("LZX archive", "Amiga, 1995-1997", "unar or unlzx"),
    "sqz": ("SQZ archive (Squeeze It)", "DOS, 1991-1993", "unar"),
    "sq": ("Squeezed file (.?Q?)", "CP/M and DOS, 1981-1987", "unar or usq"),
    "crunch": ("Crunched file (.?Z?)", "CP/M and DOS, 1986-1990", "unar or uncr"),
    "lzhcrunch": ("LZH-crunched file (.?Y?)", "CP/M, 1990s", "unar or lbrate"),
    "pack": ("Packed file (Unix pack, .z)", "Unix, 1970s-1980s", "unar, or gzip -d (gzip still reads pack)"),
    "compact": ("Compacted file (Unix compact, .C)", "Unix, 1980s", "unar"),
}
LISTED = ("arc", "pak", "zoo", "ace", "ha", "lbr")


def kind_of(head: bytes, path: str) -> str:
    """The old format the first bytes (and for weak signatures the name) show, or an empty string."""
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    if head.startswith(b"ZOO ") and head[20:24] == b"\xdc\xa7\xc4\xfd":
        return "zoo"
    if head[7:14] == b"**ACE**":
        return "ace"
    if head.startswith((b"SIT!", b"StuffIt (c)1997")):
        return "sit"
    if head.startswith(b"DMS!"):
        return "dms"
    if head.startswith(b"LZX") and ext == ".lzx":
        return "lzx"
    if head.startswith(b"HLSQZ"):
        return "sqz"
    if head.startswith(b"HA") and ext == ".ha" and len(head) >= 4:
        return "ha"
    if head[:1] == b"\x1a" and len(head) > 2 and 1 <= head[1] <= 11 and ext in (".arc", ".ark", ".pak"):
        return "pak" if ext == ".pak" else "arc"
    if head[:1] == b"\x00" and head[1:12] == b" " * 11 and head[12:14] == b"\x00\x00" and ext == ".lbr":
        return "lbr"
    middle = ext[2:3] if len(ext) == 4 else ""
    if head.startswith(b"\x76\xff") and (middle == "q" or ext == ".sq"):
        return "sq"
    if head.startswith(b"\x76\xfe") and middle == "z":
        return "crunch"
    if head.startswith(b"\x76\xfd") and middle == "y":
        return "lzhcrunch"
    if head.startswith(b"\x1f\x1e") and ext == ".z":
        return "pack"
    if head.startswith(b"\x1f\xff") and ext == ".c":
        return "compact"
    return ""


def dos_time(date: int, time_: int) -> str:
    if not date:
        return ""
    try:
        return dt.datetime(1980 + (date >> 9), (date >> 5) & 15, date & 31, time_ >> 11, (time_ >> 5) & 63,
                           min(59, (time_ & 31) * 2)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return f"(not a date: {date:04x} {time_:04x})"


def _name(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("cp437", "replace")


def old_archive_sheets(path: str) -> list:
    with open(path, "rb") as f:
        head = f.read(64)
    kind = kind_of(head, path)
    if not kind:
        raise DocumentError("This is not an old archive Dossier knows")
    title, era, opener = FORMATS[kind]
    size = os.path.getsize(path)
    members: list = []
    problem = ""
    if kind in LISTED:
        with open(path, "rb") as f:
            data = f.read(MAX_READ)
        try:
            {"arc": _arc, "pak": _arc, "zoo": _zoo, "ace": _ace, "ha": _ha, "lbr": _lbr}[kind](data, members)   # fills as it reads
        except (struct.error, IndexError, ValueError) as e:
            problem = f"The listing stops where the file is damaged ({e})"
    info = [("Format", title), ("Platform and years", era),
            ("Members", f"{len(members):,}" if kind in LISTED else "not listed: Dossier names this kind only"),
            ("Deleted entries still in the file", str(sum(1 for m in members if m.get("deleted")))
             if any(m.get("deleted") for m in members) else ""),
            ("Size", f"{human_size(size)} ({size:,} bytes)"),
            ("Unpacked by", opener + " (Dossier and 7-Zip cannot unpack it)"), ("Listing", problem)]
    grid = _Grid([MAX_CELLS])
    for r, (field, value) in enumerate([("Field", "Value")] + [(f, v) for f, v in info if v]):
        grid.put(r, 0, field)
        grid.put(r, 1, value)
    info_sheet = Sheet("Info", grid.rows(), grid.cut)
    if kind not in LISTED:
        return [info_sheet]
    files = _Grid([MAX_CELLS])
    for c, head_name in enumerate(("Name", "Size", "Packed", "Method", "Date", "CRC", "Note")):
        files.put(0, c, head_name)
    for r, m in enumerate(members, start=1):
        files.put(r, 0, m["name"])
        files.put(r, 1, str(m.get("size", "")))
        files.put(r, 2, str(m.get("packed", "")))
        files.put(r, 3, m.get("method", ""))
        files.put(r, 4, m.get("date", ""))
        files.put(r, 5, m.get("crc", ""))
        files.put(r, 6, "deleted" if m.get("deleted") else m.get("note", ""))
    return [Sheet("Files", files.rows(), files.cut), info_sheet]


# ARC and PAK -----------------------------------------------------------------------------------------------------------------------
ARC_METHODS = {1: "stored (old)", 2: "stored", 3: "packed", 4: "squeezed", 5: "crunched (old)", 6: "crunched (old, packed)",
               7: "crunched (faster)", 8: "crunched", 9: "squashed", 10: "crushed (PAK)", 11: "distilled (PAK)"}


def _arc(data: bytes, out: list) -> list:
    folders: list = []
    pos = 0
    while pos + 2 <= len(data) and len(out) < MAX_MEMBERS:
        if data[pos] != 0x1A:
            break
        method = data[pos + 1]
        if method == 0:                                    # the end of the archive (or of a subfolder's archive)
            if folders:
                folders.pop()
                pos += 2
                continue
            break
        if method == 31:                                   # ARC 7: the end of a subfolder
            if folders:
                folders.pop()
            pos += 2
            continue
        name = _name(data[pos + 2:pos + 15])
        packed, date, time_, crc = struct.unpack_from("<IHHH", data, pos + 15)
        if method == 1:
            original, header = packed, 25
        else:
            original, = struct.unpack_from("<I", data, pos + 25)
            header = 29
        prefix = "/".join(folders)
        if method == 30:                                   # ARC 7: a subfolder; its members follow inside it
            out.append({"name": (prefix + "/" if prefix else "") + name + "/", "method": "folder", "date": dos_time(date, time_)})
            folders.append(name)
            pos += header
            continue
        if method >= 20:                                   # PAK: a comment or other information block
            pos += header + packed
            continue
        out.append({"name": (prefix + "/" if prefix else "") + name, "size": original, "packed": packed,
                    "method": ARC_METHODS.get(method, f"method {method}"), "date": dos_time(date, time_), "crc": f"{crc:04X}"})
        pos += header + packed
    return out


# ZOO -------------------------------------------------------------------------------------------------------------------------------
ZOO_METHODS = {0: "stored", 1: "LZW", 2: "LZH"}


def _zoo(data: bytes, out: list) -> list:
    pos, = struct.unpack_from("<I", data, 24)
    seen: set = set()
    while 0 < pos < len(data) and pos not in seen and len(out) < MAX_MEMBERS:
        seen.add(pos)
        if data[pos:pos + 4] != b"\xdc\xa7\xc4\xfd":
            break
        kind, method, nxt, _offset, date, time_, crc, original, packed = struct.unpack_from("<BBIIHHHII", data, pos + 4)
        if nxt == 0:                                       # the closing dummy entry
            break
        deleted = data[pos + 30]
        name = _name(data[pos + 38:pos + 51])
        if kind == 2 and pos + 58 <= len(data):
            name_len, dir_len = data[pos + 56], data[pos + 57]
            long_name = _name(data[pos + 58:pos + 58 + name_len]) if name_len else ""
            folder = _name(data[pos + 58 + name_len:pos + 58 + name_len + dir_len]) if dir_len else ""
            name = (folder.rstrip("/") + "/" if folder else "") + (long_name or name)
        out.append({"name": name, "size": original, "packed": packed, "method": ZOO_METHODS.get(method, f"method {method}"),
                    "date": dos_time(date, time_), "crc": f"{crc:04X}", "deleted": bool(deleted)})
        pos = nxt
    return out


# ACE -------------------------------------------------------------------------------------------------------------------------------
ACE_METHODS = {0: "stored", 1: "LZ77 (ACE 1)", 2: "blocked (ACE 2)"}


def _ace(data: bytes, out: list) -> list:
    _crc, size = struct.unpack_from("<HH", data, 0)
    pos = 4 + size                                         # past the archive header
    while pos + 7 <= len(data) and len(out) < MAX_MEMBERS:
        _crc, size, kind, flags = struct.unpack_from("<HHBH", data, pos)
        body = pos + 4
        packed = 0
        if kind in (1, 3):                                 # a file, 32-bit or 64-bit sizes
            wide = kind == 3
            fmt = "<QQ" if wide else "<II"
            packed, original = struct.unpack_from(fmt, data, body + 3)
            p = body + 3 + struct.calcsize(fmt)
            ftime, _attr, crc32, tech = struct.unpack_from("<IIII", data, p)
            name_len, = struct.unpack_from("<H", data, p + 18)
            name = data[p + 20:p + 20 + name_len].decode("cp437", "replace").replace("\\", "/")
            out.append({"name": name, "size": original, "packed": packed, "method": ACE_METHODS.get(tech & 0xFF, f"method {tech & 0xFF}"),
                        "date": dos_time(ftime >> 16, ftime & 0xFFFF), "crc": f"{crc32:08X}",     # as stored
                        "note": "password" if flags & 0x4000 else ""})
        elif flags & 0x1:                                  # another block with data after its header
            packed, = struct.unpack_from("<I", data, body + 3)
        if size == 0:
            break
        pos = body + size + packed
    return out


# HA --------------------------------------------------------------------------------------------------------------------------------
HA_METHODS = {0: "stored", 1: "ASC", 2: "HSC", 14: "folder", 15: "special"}


def _ha(data: bytes, out: list) -> list:
    count, = struct.unpack_from("<H", data, 2)
    pos = 4
    for _ in range(min(count, MAX_MEMBERS)):
        if pos + 17 > len(data):
            break
        kind = data[pos]
        packed, original, crc, mtime = struct.unpack_from("<IIII", data, pos + 1)
        p = pos + 17
        end = data.index(b"\x00", p)
        folder = data[p:end].replace(b"\xff", b"/").decode("cp437", "replace")       # 0xFF separates folders
        p = end + 1
        end = data.index(b"\x00", p)
        name = data[p:end].decode("cp437", "replace")
        p = end + 1
        machine_len = data[p]
        p += 1 + machine_len
        when = dt.datetime.fromtimestamp(mtime, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if mtime else ""
        method = kind & 0x0F
        out.append({"name": (folder.rstrip("/") + "/" if folder else "") + name + ("/" if method == 14 else ""), "size": original,
                    "packed": packed, "method": HA_METHODS.get(method, f"method {method}"), "date": when, "crc": f"{crc:08X}"})
        pos = p + packed
    return out


# CP/M LBR --------------------------------------------------------------------------------------------------------------------------
def _cpm_date(days: int) -> str:
    return (dt.date(1977, 12, 31) + dt.timedelta(days=days)).isoformat() if days else ""


def _lbr(data: bytes, out: list) -> list:
    sectors, = struct.unpack_from("<H", data, 14)          # the directory's own length, in 128-byte sectors
    for i in range(1, min(sectors * 4, MAX_MEMBERS)):
        entry = data[i * 32:i * 32 + 32]
        if len(entry) < 32 or entry[0] == 0xFF:
            continue
        name = entry[1:9].decode("ascii", "replace").rstrip()
        ext = entry[9:12].decode("ascii", "replace").rstrip()
        if not name.strip():
            continue
        index, length, crc, created, changed = struct.unpack_from("<HHHHH", entry, 12)
        pad = entry[26]
        out.append({"name": name + ("." + ext if ext else ""), "size": max(0, length * 128 - pad), "packed": length * 128,
                    "method": "stored", "date": _cpm_date(changed or created), "crc": f"{crc:04X}",
                    "deleted": entry[0] == 0xFE, "note": f"sector {index}"})
    return out
