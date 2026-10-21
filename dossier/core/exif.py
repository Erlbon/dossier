"""Read-only EXIF of a photo: camera, lens, exposure, date, place. Standard library only.

The EXIF block is a small TIFF file inside the picture (JPEG: the APP1 segment, PNG: the eXIf chunk, WebP: the EXIF chunk, TIFF: the
file itself). It is parsed here, for the viewer's information panel; nothing is written, and a damaged block gives what could be read
(never an error). ``Orientation`` is returned too, because a photo taken upright but stored sideways must be turned to be seen right.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
MAX_ENTRIES = 400
IFD0 = {0x010F: "Make", 0x0110: "Model", 0x0112: "Orientation", 0x0131: "Software", 0x0132: "Date modified", 0x013B: "Artist",
        0x8298: "Copyright", 0x010E: "Description"}
EXIF = {0x829A: "Exposure time", 0x829D: "Aperture", 0x8827: "ISO", 0x9003: "Date taken", 0x9004: "Date digitized",
        0x9201: "Shutter speed", 0x9204: "Exposure compensation", 0x9207: "Metering mode", 0x9209: "Flash", 0x920A: "Focal length",
        0xA002: "Width", 0xA003: "Height", 0xA405: "Focal length (35 mm)", 0xA434: "Lens", 0xA433: "Lens make",
        0xA402: "Exposure mode", 0xA403: "White balance", 0xA406: "Scene type"}
ORIENTATION = {1: "Normal", 2: "Mirrored", 3: "Rotated 180", 4: "Mirrored vertically", 5: "Mirrored, rotated 90 right",
               6: "Rotated 90 right", 7: "Mirrored, rotated 90 left", 8: "Rotated 90 left"}
ROTATE_DEGREES = {1: 0, 2: 0, 3: 180, 4: 180, 5: 90, 6: 90, 7: 270, 8: 270}      # clockwise, to see the photo upright


@dataclass
class Exif:
    fields: list = field(default_factory=list)       # (group, label, text) in display order
    orientation: int = 1
    error: str = ""

    def get(self, label: str, default: str = "") -> str:
        return next((v for _g, k, v in self.fields if k == label), default)


def find_block(data: bytes) -> bytes:
    """The TIFF-formatted EXIF block inside a JPEG, PNG, WebP or TIFF file's bytes (empty when there is none)."""
    if data[:2] == b"\xff\xd8":                                       # JPEG: segments marker, length, payload
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker = data[pos + 1]
            if marker == 0xD9 or marker == 0xDA:                      # end of image / start of the picture data
                break
            length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\x00\x00":
                return data[pos + 10:pos + 2 + length]
            pos += 2 + length
        return b""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        pos = 8
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == b"eXIf":
                return data[pos + 8:pos + 8 + length]
            pos += 12 + length
        return b""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        pos = 12
        while pos + 8 <= len(data):
            kind, length = struct.unpack("<4sI", data[pos:pos + 8])
            if kind == b"EXIF":
                body = data[pos + 8:pos + 8 + length]
                return body[6:] if body[:6] == b"Exif\x00\x00" else body
            pos += 8 + length + (length & 1)
        return b""
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return data
    return b""


def _rational(a: int, b: int) -> float:
    return a / b if b else 0.0


def _values(tiff: bytes, order: str, kind: int, count: int, offset_or_value: bytes, pos: int) -> list:
    size = TYPE_SIZES.get(kind, 0) * count
    if not size or count > 4096:
        return []
    raw = offset_or_value if size <= 4 else tiff[struct.unpack(order + "I", offset_or_value)[0]:][:size]
    if len(raw) < size:
        return []
    if kind in (1, 7):
        return list(raw[:count])
    if kind == 2:
        return [raw[:count].split(b"\x00")[0].decode("utf-8", "replace").strip()]
    if kind == 3:
        return list(struct.unpack(order + f"{count}H", raw[:size]))
    if kind == 4:
        return list(struct.unpack(order + f"{count}I", raw[:size]))
    if kind == 9:
        return list(struct.unpack(order + f"{count}i", raw[:size]))
    pairs = struct.unpack(order + f"{count * 2}{'I' if kind == 5 else 'i'}", raw[:size])
    return [_rational(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)]


def _read_ifd(tiff: bytes, order: str, offset: int) -> dict:
    """``{tag: values}`` of one directory; a truncated directory gives the entries that are whole."""
    out: dict = {}
    if offset <= 0 or offset + 2 > len(tiff):
        return out
    n = min(struct.unpack(order + "H", tiff[offset:offset + 2])[0], MAX_ENTRIES)
    for i in range(n):
        at = offset + 2 + i * 12
        if at + 12 > len(tiff):
            break
        tag, kind, count = struct.unpack(order + "HHI", tiff[at:at + 8])
        try:
            out[tag] = _values(tiff, order, kind, count, tiff[at + 8:at + 12], at)
        except (struct.error, IndexError):
            continue
    return out


def _fraction(x: float) -> str:
    if x >= 1 or x <= 0:
        return f"{x:g} s"
    return f"1/{round(1 / x)} s"


def _gps(coords: list, ref: str) -> float:
    if len(coords) < 3:
        return 0.0
    value = coords[0] + coords[1] / 60 + coords[2] / 3600
    return -value if ref in ("S", "W") else value


def parse(tiff: bytes) -> Exif:
    result = Exif()
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        result.error = "no EXIF block"
        return result
    order = "<" if tiff[:2] == b"II" else ">"
    try:
        ifd0 = _read_ifd(tiff, order, struct.unpack(order + "I", tiff[4:8])[0])
        exif = _read_ifd(tiff, order, (ifd0.get(0x8769) or [0])[0])
        gps = _read_ifd(tiff, order, (ifd0.get(0x8825) or [0])[0])
    except struct.error:
        result.error = "damaged EXIF block"
        return result
    first = lambda d, tag: (d.get(tag) or [None])[0]                                  # noqa: E731
    result.orientation = int(first(ifd0, 0x0112) or 1) if first(ifd0, 0x0112) in ORIENTATION else 1
    camera = " ".join(x for x in (first(ifd0, 0x010F), first(ifd0, 0x0110)) if x)
    if camera:
        result.fields.append(("Camera", "Camera", camera))
    for tag, label in IFD0.items():
        v = first(ifd0, tag)
        if v in (None, "") or tag in (0x010F, 0x0110):
            continue
        result.fields.append(("Camera", label, ORIENTATION.get(v, str(v)) if tag == 0x0112 else str(v)))
    for tag, label in EXIF.items():
        v = first(exif, tag)
        if v in (None, ""):
            continue
        text = {0x829A: _fraction, 0x829D: lambda x: f"f/{x:g}", 0x920A: lambda x: f"{x:g} mm", 0x9201: lambda x: f"{x:g} EV"}.get(tag, str)
        group = "Date" if "Date" in label else "Picture" if tag in (0xA002, 0xA003) else "Exposure"
        result.fields.append((group, label, text(v) if isinstance(v, (int, float)) or tag in (0x829A,) else str(v)))
    lat, lon = gps.get(0x0002), gps.get(0x0004)
    if lat and lon:
        la, lo = _gps(lat, (first(gps, 0x0001) or "N")), _gps(lon, (first(gps, 0x0003) or "E"))
        result.fields.append(("Place", "GPS", f"{la:.5f}, {lo:.5f}"))
    return result


def read_exif(path: str) -> Exif:
    """The EXIF of the picture file at ``path`` (an empty ``Exif`` with an ``error`` text when there is none). Never raises."""
    try:
        with open(path, "rb") as f:
            data = f.read(8 * 1024 * 1024)
    except OSError as e:
        return Exif(error=str(e.strerror or e))
    block = find_block(data)
    if not block:
        return Exif(error="no EXIF block")
    try:
        return parse(block)
    except Exception as e:   # noqa: BLE001 -- a damaged block is a per-file note, never a crash
        return Exif(error=f"could not read the EXIF block: {e}")
