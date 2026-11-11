"""Structured listings of small system files for the viewer's grid, the way a forensic tool shows them: Windows shortcuts (.lnk),
Recycle Bin records ($I files) and property lists (.plist). Read only; each field as it is stored, times in UTC.

``.lnk`` (Microsoft's MS-SHLLINK): the target's path (from the link info, else rebuilt from the shell item list), arguments,
working folder, icon, the target's own times and size when the link was made, the drive's type, label and serial number, the
network share, and from the tracker block the machine's NetBIOS name and the MAC address and time inside the object ids.
``$I``: the deleted file's original path, size and deletion time, and whether its ``$R`` copy is still beside it.
``.plist``: XML or binary, flattened to Key path / Type / Value rows.

Only the standard library; Qt-free. Every read is bounded: a damaged file is an error in words, never a hang.
"""
from __future__ import annotations

import datetime as dt
import os
import plistlib
import struct
import uuid

from .officedoc import DocumentError, PROLOG, unsafe_xml
from .officesheet import MAX_CELLS, Sheet, _Grid
from .sizefmt import human_size

LNK_MAGIC = b"\x4c\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"
BPLIST_MAGIC = b"bplist00"
MAX_SMALL = 16 * 1024 * 1024
MAX_PLIST = 64 * 1024 * 1024


def kind_of(head: bytes, path: str) -> str:
    """``lnk``, ``recycle`` or ``plist`` when the first bytes (and for $I and XML plists the name) say so, else an empty string."""
    name = os.path.basename(path).lower()
    if head.startswith(LNK_MAGIC):
        return "lnk"
    if name.startswith("$i") and len(head) >= 24 and head[:8] in (struct.pack("<Q", 1), struct.pack("<Q", 2)):
        return "recycle"
    if head.startswith(BPLIST_MAGIC):
        return "plist"
    if name.endswith(".plist") and (b"<plist" in head[:2048] or b"<!DOCTYPE plist" in head[:2048]):
        return "plist"
    return ""


def filetime(value: int) -> str:
    """A Windows FILETIME (100 ns since 1601) as ``2026-11-11 14:30:05 UTC``; 0 means not set."""
    if not value or value >= 0x7FFFFFFFFFFFFFFF:
        return ""
    try:
        return (dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=value // 10)).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
    except OverflowError:
        return f"(out of range: {value})"


def _fields_sheet(name: str, rows: list) -> Sheet:
    grid = _Grid([MAX_CELLS])
    grid.put(0, 0, "Field")
    grid.put(0, 1, "Value")
    r = 1
    for field, value in rows:
        if value not in ("", None):
            grid.put(r, 0, field)
            grid.put(r, 1, str(value))
            r += 1
    return Sheet(name, grid.rows(), grid.cut)


def _read(path: str, cap: int) -> bytes:
    with open(path, "rb") as f:
        data = f.read(cap + 1)
    if len(data) > cap:
        raise DocumentError("The file is too big to be one of these")
    return data


# .lnk ------------------------------------------------------------------------------------------------------------------------------
DRIVE_TYPES = {0: "unknown", 1: "no root folder", 2: "removable", 3: "fixed", 4: "network", 5: "CD/DVD", 6: "RAM disk"}
SHOW = {1: "normal", 3: "maximized", 7: "minimized"}
ROOT_FOLDERS = {"20d04fe0-3aea-1069-a2d8-08002b30309d": "This PC", "450d8fba-ad25-11d0-98a8-0800361b1103": "Documents",
                "208d2c60-3aea-1069-a2d7-08002b30309d": "Network", "59031a47-3f72-44a7-89c5-5595fe6b30ee": "User folder",
                "21ec2020-3aea-1069-a2dd-08002b30309d": "Control Panel", "645ff040-5081-101b-9f08-00aa002f954e": "Recycle Bin"}
FLAG_NAMES = ((0x1, "item list"), (0x2, "link info"), (0x4, "description"), (0x8, "relative path"), (0x10, "working folder"),
              (0x20, "arguments"), (0x40, "icon"), (0x80, "Unicode"), (0x200, "environment path"), (0x2000, "run as administrator"),
              (0x100000, "no link tracking"))
ATTRIBUTES = ((0x1, "read-only"), (0x2, "hidden"), (0x4, "system"), (0x10, "folder"), (0x20, "archive"), (0x100, "temporary"),
              (0x800, "compressed"), (0x4000, "encrypted"))


def _cstr(data: bytes, pos: int, wide: bool = False, limit: int = 4096) -> str:
    if pos <= 0 or pos >= len(data):
        return ""
    if wide:
        end = pos
        while end + 1 < len(data) and end - pos < limit * 2 and data[end:end + 2] != b"\x00\x00":
            end += 2
        return data[pos:end].decode("utf-16-le", "replace")
    end = data.find(b"\x00", pos, pos + limit)
    return data[pos:end if end >= 0 else pos + limit].decode("cp1252", "replace")


def _id_list_path(items: bytes) -> str:
    """The target's path rebuilt from the shell item list, for links that have no link info (only the common item kinds)."""
    parts = []
    pos = 0
    while pos + 2 <= len(items):
        size, = struct.unpack_from("<H", items, pos)
        if size < 3 or pos + size > len(items):
            break
        item = items[pos:pos + size]
        kind = item[2]
        if kind == 0x1F and size >= 20:                             # a root folder by its class id
            parts.append(ROOT_FOLDERS.get(str(uuid.UUID(bytes_le=item[4:20])), "{" + str(uuid.UUID(bytes_le=item[4:20])) + "}"))
        elif kind & 0x70 == 0x20:                                   # a drive
            parts.append(_cstr(item, 3, limit=16).rstrip("\\"))
        elif kind & 0x70 == 0x30 and size > 14:                     # a file or folder: the long name in its 0xBEEF0004 block
            name = _cstr(item, 14, limit=260)
            sig = item.find(b"\x04\x00\xef\xbe")
            if sig >= 4:
                block = sig - 4
                version, = struct.unpack_from("<H", item, block + 2)
                off = 18 + (18 if version >= 7 else 0) + (2 if version >= 3 else 0) + (4 if version >= 9 else 0) + (4 if version >= 8 else 0)
                long_name = _cstr(item, block + off, wide=True, limit=260)
                if long_name:
                    name = long_name
            parts.append(name)
        pos += size
    if parts and parts[0] == "This PC":
        parts = parts[1:]
    return "\\".join(p for p in parts if p)


def _uuid_facts(raw: bytes) -> tuple:
    """(MAC address, time) inside a version 1 UUID (the object ids Windows gives a link's target), else empty strings."""
    u = uuid.UUID(bytes_le=raw)
    if u.version != 1:
        return "", ""
    mac = ":".join(f"{b:02x}" for b in u.node.to_bytes(6, "big"))
    when = dt.datetime(1582, 10, 15, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=u.time // 10)
    return mac, when.strftime("%Y-%m-%d %H:%M:%S UTC")


def lnk_sheets(path: str) -> list:
    data = _read(path, MAX_SMALL)
    if not data.startswith(LNK_MAGIC) or len(data) < 0x4C:
        raise DocumentError("This is not a Windows shortcut inside, whatever its name says")
    try:
        return [_fields_sheet("Shortcut", _lnk_rows(data))]
    except (struct.error, IndexError, ValueError) as e:
        raise DocumentError("The shortcut is damaged") from e


def _lnk_rows(data: bytes) -> list:
    flags, attrs, created, accessed, written, size, icon_index, show = struct.unpack_from("<IIQQQIiI", data, 0x14)
    rows: list = []
    pos = 0x4C
    id_path = ""
    if flags & 0x1:
        n, = struct.unpack_from("<H", data, pos)
        id_path = _id_list_path(data[pos + 2:pos + 2 + n])
        pos += 2 + n
    local = network = suffix = ""
    volume: dict = {}
    if flags & 0x2:
        info_size, header_size, info_flags, vol_off, base_off, net_off, suffix_off = struct.unpack_from("<IIIIIII", data, pos)
        info = data[pos:pos + info_size]
        base_u = suffix_u = 0
        if header_size >= 0x24:
            base_u, suffix_u = struct.unpack_from("<II", info, 0x1C)
        if info_flags & 0x1 and vol_off:
            v_size, drive, serial, label_off = struct.unpack_from("<IIII", info, vol_off)
            label = (_cstr(info, vol_off + struct.unpack_from("<I", info, vol_off + 16)[0], wide=True) if label_off == 0x14
                     else _cstr(info, vol_off + label_off))
            volume = {"type": DRIVE_TYPES.get(drive, str(drive)), "serial": f"{serial >> 16:04X}-{serial & 0xFFFF:04X}", "label": label}
            local = _cstr(info, base_u, wide=True) if base_u else _cstr(info, base_off)
        if info_flags & 0x2 and net_off:
            _s, _f, name_off, device_off, _prov = struct.unpack_from("<IIIII", info, net_off)
            network = _cstr(info, net_off + name_off)
            device = _cstr(info, net_off + device_off) if device_off else ""
            if device:
                network = f"{network} (as {device})"
        suffix = _cstr(info, suffix_u, wide=True) if suffix_u else _cstr(info, suffix_off)
        pos += info_size
    strings = {}
    wide = bool(flags & 0x80)
    for bit, key in ((0x4, "description"), (0x8, "relative"), (0x10, "workdir"), (0x20, "arguments"), (0x40, "icon")):
        if flags & bit:
            count, = struct.unpack_from("<H", data, pos)
            raw = data[pos + 2:pos + 2 + count * (2 if wide else 1)]
            strings[key] = raw.decode("utf-16-le" if wide else "cp1252", "replace")
            pos += 2 + len(raw)
    extra: list = []
    env_target = known = machine = ""
    while pos + 8 <= len(data):
        block_size, signature = struct.unpack_from("<II", data, pos)
        if block_size < 8 or pos + block_size > len(data):
            break
        block = data[pos:pos + block_size]
        if signature == 0xA0000003 and block_size >= 0x60:          # tracker: the machine and the object ids
            # 0x10 machine name; 0x20 volume and 0x30 file object ids (Droid); 0x40 and 0x50 the ids they were born with
            machine = _cstr(block, 0x10, limit=16)
            mac, when = _uuid_facts(block[0x30:0x40])
            birth_mac, _birth_when = _uuid_facts(block[0x50:0x60])
            extra += [("Machine (NetBIOS name)", machine), ("MAC address in the file's object id", mac),
                      ("Time in the file's object id", when)]
            if birth_mac and birth_mac != mac:
                extra.append(("MAC address in the birth object id", birth_mac))
            extra += [("Volume object id", "{" + str(uuid.UUID(bytes_le=block[0x20:0x30])) + "}"),
                      ("File object id", "{" + str(uuid.UUID(bytes_le=block[0x30:0x40])) + "}")]
        elif signature in (0xA0000001, 0xA0000007) and block_size >= 0x314:   # environment path (target or icon)
            target = _cstr(block, 0x10C, wide=True, limit=260) or _cstr(block, 8, limit=260)
            if signature == 0xA0000001:
                env_target = target
            else:
                extra.append(("Icon (with variables)", target))
        elif signature == 0xA000000B and block_size >= 0x1C:          # a known folder
            known = "{" + str(uuid.UUID(bytes_le=block[8:24])) + "}"
        pos += block_size
    target = local + suffix if local else (network + ("\\" + suffix if suffix else "") if network else "") or env_target or id_path
    rows += [("Target", target),
             ("Target with variables", env_target if env_target and env_target != target else ""),
             ("Target from the item list", id_path if id_path and id_path != target else ""),
             ("Arguments", strings.get("arguments", "")), ("Working folder", strings.get("workdir", "")),
             ("Relative path", strings.get("relative", "")), ("Description", strings.get("description", "")),
             ("Icon", strings.get("icon", "") + (f",{icon_index}" if strings.get("icon") and icon_index else "")),
             ("Target created", filetime(created)), ("Target modified", filetime(written)), ("Target accessed", filetime(accessed)),
             ("Target size", f"{human_size(size)} ({size:,} bytes)" if size else ""),
             ("Target attributes", ", ".join(n for bit, n in ATTRIBUTES if attrs & bit)),
             ("Drive type", volume.get("type", "")), ("Drive serial number", volume.get("serial", "")),
             ("Drive label", volume.get("label", "")), ("Network share", network),
             ("Known folder", known), ("Window", SHOW.get(show, str(show)))]
    rows += extra
    rows.append(("Parts present", ", ".join(n for bit, n in FLAG_NAMES if flags & bit)))
    return rows


# $I (Recycle Bin) ------------------------------------------------------------------------------------------------------------------
def recycle_sheets(path: str) -> list:
    data = _read(path, 1024 * 1024)
    if len(data) < 24:
        raise DocumentError("The Recycle Bin record is cut short")
    version, size, deleted = struct.unpack_from("<QQQ", data, 0)
    if version == 1:
        original = _cstr(data, 24, wide=True, limit=260)
    elif version == 2:
        count, = struct.unpack_from("<I", data, 24)
        original = data[28:28 + 2 * count].decode("utf-16-le", "replace").rstrip("\x00")
    else:
        raise DocumentError("This is not a Recycle Bin record inside, whatever its name says")
    folder, name = os.path.split(path)
    copy = "$R" + name[2:]
    present = os.path.exists(os.path.join(folder, copy))
    return [_fields_sheet("Deleted file", [
        ("Original path", original), ("Original name", original.replace("/", "\\").rsplit("\\", 1)[-1]),
        ("Size", f"{human_size(size)} ({size:,} bytes)"), ("Deleted", filetime(deleted)),
        ("The deleted file's copy", f"{copy} ({'beside this record' if present else 'not here: emptied or restored'})"),
        ("Record format", "Windows 10 and later (version 2)" if version == 2 else "Windows Vista to 8.1 (version 1)")])]


# .plist ----------------------------------------------------------------------------------------------------------------------------
def _plist_value(v) -> tuple:
    if isinstance(v, bool):
        return "boolean", "true" if v else "false"
    if isinstance(v, int):
        return "integer", str(v)
    if isinstance(v, float):
        return "real", repr(v)
    if isinstance(v, dt.datetime):
        when = v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
        return "date", when.strftime("%Y-%m-%d %H:%M:%S UTC")
    if isinstance(v, (bytes, bytearray)):
        note = " (a binary plist inside)" if bytes(v).startswith(BPLIST_MAGIC) else ""
        return "data", f"{len(v):,} bytes{note}: {bytes(v[:32]).hex(' ')}" + (" ..." if len(v) > 32 else "")
    if isinstance(v, plistlib.UID):
        return "UID", str(v.data)
    return "string", str(v)


def plist_sheets(path: str) -> list:
    data = _read(path, MAX_PLIST)
    if not data.startswith(BPLIST_MAGIC) and unsafe_xml(data[:PROLOG]):
        raise DocumentError("The property list defines its own XML entities, which Apple's tools never write; not read")
    try:
        root = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError,
            struct.error) as e:
        raise DocumentError(f"The property list is damaged: {e}") from e
    grid = _Grid([MAX_CELLS])
    for c, head in enumerate(("Key path", "Type", "Value")):
        grid.put(0, c, head)
    row = [1]
    seen: set = set()

    def walk(value, key: str, depth: int) -> None:
        if row[0] > 1_000_000 or depth > 200:
            grid.cut = True
            return
        if isinstance(value, dict):
            if id(value) in seen:
                return
            seen.add(id(value))
            grid.put(row[0], 0, key or "(top)")
            grid.put(row[0], 1, "dictionary")
            grid.put(row[0], 2, f"{len(value):,} keys")
            row[0] += 1
            for k, v in value.items():
                walk(v, f"{key}/{k}" if key else str(k), depth + 1)
        elif isinstance(value, list):
            if id(value) in seen:
                return
            seen.add(id(value))
            grid.put(row[0], 0, key or "(top)")
            grid.put(row[0], 1, "array")
            grid.put(row[0], 2, f"{len(value):,} items")
            row[0] += 1
            for i, v in enumerate(value):
                walk(v, f"{key}[{i}]", depth + 1)
        else:
            kind, text = _plist_value(value)
            grid.put(row[0], 0, key or "(top)")
            grid.put(row[0], 1, kind)
            grid.put(row[0], 2, text)
            row[0] += 1

    walk(root, "", 0)
    return [Sheet("Property list", grid.rows(), grid.cut)]
