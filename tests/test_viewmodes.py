"""Which viewer a file gets, the EXIF of a photo, the hex file reader and the safe Markdown rules (core)."""
import os
import struct

import pytest

from dossier.core import exif as ex
from dossier.core import hexview as hv
from dossier.core import markdownsafe as ms
from dossier.core import viewmodes as vm
from dossier.core.progress import CancelToken, Cancelled

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


def write(path, data):
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return str(path)


# which viewer ---------------------------------------------------------------------------------------------------------------------
def test_a_picture_is_known_by_its_first_bytes_not_its_name(tmp_path):
    assert vm.mode_for(write(tmp_path / "photo.dat", JPEG)) == "image"
    assert vm.mode_for(write(tmp_path / "x.png", PNG)) == "image"
    assert vm.image_kind(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp" and vm.image_kind(b"GIF89a....") == "gif"
    assert vm.image_kind(b"BM" + b"\x00" * 20, "a.bmp") == "bmp" and vm.image_kind(b"BM" + b"\x00" * 20, "notes.txt") == ""
    assert vm.mode_for(write(tmp_path / "fake.jpg", "just some text\n")) == "text"           # named like a picture, is not one


def test_text_markdown_and_binary_files_get_their_own_modes(tmp_path):
    assert vm.mode_for(write(tmp_path / "a.txt", "hello\nworld\n")) == "text"
    assert vm.mode_for(write(tmp_path / "README.MD", "# Title\n")) == "markdown"
    assert vm.mode_for(write(tmp_path / "notes.markdown", "# Title\n")) == "markdown"
    assert vm.mode_for(write(tmp_path / "prog.bin", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00" * 10)) == "hex"
    assert vm.mode_for(write(tmp_path / "wide.txt", "hello world".encode("utf-16"))) == "text"       # UTF-16 text is text
    assert vm.mode_for(write(tmp_path / "empty.dat", b"")) == "text"
    assert vm.mode_for(str(tmp_path / "missing.bin")) == "text"
    assert vm.mode_for(write(tmp_path / "bin.md", b"\x00\x01\x02" * 50)) == "hex"                   # content wins over the name


def test_every_file_can_be_seen_in_the_other_sensible_modes(tmp_path):
    assert vm.modes_for(write(tmp_path / "a.png", PNG)) == ["image", "hex"]
    assert vm.modes_for(write(tmp_path / "a.md", "x")) == ["markdown", "text", "hex"]
    assert vm.modes_for(write(tmp_path / "a.txt", "x")) == ["text", "hex"]
    assert vm.modes_for(write(tmp_path / "a.bin", b"\x00" * 40)) == ["hex", "text"]


def test_the_pictures_of_a_folder_are_counted_in_natural_order():
    names = ["img10.jpg", "notes.txt", "img2.JPG", "Img1.png", "movie.mp4", "scan.tif"]
    assert vm.image_siblings(names) == ["Img1.png", "img2.JPG", "img10.jpg", "scan.tif"]
    assert vm.is_image_name("C:/x/A.JPEG") and not vm.is_image_name("a.txt")


# EXIF -----------------------------------------------------------------------------------------------------------------------------
def tiff(ifd0: list, exif: list = (), gps: list = (), order="<") -> bytes:
    """A small TIFF with the given entries (tag, type, values); out-of-line values go after the directories."""
    P = lambda fmt, *a: struct.pack(order + fmt, *a)           # noqa: E731
    blocks = []
    directories = {"ifd0": list(ifd0), "exif": list(exif), "gps": list(gps)}
    if exif:
        directories["ifd0"].append((0x8769, 4, ["exif"]))
    if gps:
        directories["ifd0"].append((0x8825, 4, ["gps"]))
    offsets = {}
    pos = 8
    for name in ("ifd0", "exif", "gps"):
        offsets[name] = pos
        pos += 2 + 12 * len(directories[name]) + 4
    out = bytearray(b"II*\x00" if order == "<" else b"MM\x00*")
    out += P("I", offsets["ifd0"])
    extra = bytearray()
    for name in ("ifd0", "exif", "gps"):
        entries = sorted(directories[name], key=lambda e: e[0])
        out += P("H", len(entries))
        for tag, kind, values in entries:
            if values and values[0] in offsets:
                raw, count = P("I", offsets[values[0]]), 1
            elif kind == 2:
                data = (values[0] + "\x00").encode()
                count = len(data)
                raw = data.ljust(4, b"\x00") if len(data) <= 4 else None
                if raw is None:
                    raw = P("I", pos + len(extra))
                    extra += data
            elif kind == 3:
                count, raw = len(values), b"".join(P("H", v) for v in values).ljust(4, b"\x00")
            elif kind == 4:
                count, raw = len(values), P("I", values[0])
            else:                                               # rationals: always out of line
                count = len(values)
                raw = P("I", pos + len(extra))
                for a, b in values:
                    extra += P("II", a, b)
            out += P("HHI", tag, kind, count) + raw
        out += P("I", 0)
    return bytes(out) + bytes(extra)


def as_jpeg(block: bytes) -> bytes:
    payload = b"Exif\x00\x00" + block
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xda\x00\x02\xff\xd9"


def sample_block(order="<"):
    return tiff([(0x010F, 2, ["Canon"]), (0x0110, 2, ["EOS R6"]), (0x0112, 3, [6])],
                [(0x829A, 5, [(1, 250)]), (0x829D, 5, [(28, 10)]), (0x8827, 3, [400]), (0x9003, 2, ["2024:05:17 10:30:00"]),
                 (0x920A, 5, [(85, 1)]), (0xA434, 2, ["RF85mm F1.2"])],
                [(0x0001, 2, ["N"]), (0x0002, 5, [(59, 1), (54, 1), (30, 1)]), (0x0003, 2, ["E"]), (0x0004, 5, [(10, 1), (45, 1), (0, 1)])],
                order)


@pytest.mark.parametrize("order", ["<", ">"])
def test_the_exif_of_a_photo_is_read_in_either_byte_order(tmp_path, order):
    path = write(tmp_path / "p.jpg", as_jpeg(sample_block(order)))
    e = ex.read_exif(path)
    assert not e.error and e.orientation == 6 and ex.ROTATE_DEGREES[e.orientation] == 90
    assert e.get("Camera") == "Canon EOS R6" and e.get("Exposure time") == "1/250 s" and e.get("Aperture") == "f/2.8"
    assert e.get("ISO") == "400" and e.get("Date taken") == "2024:05:17 10:30:00" and e.get("Focal length") == "85 mm"
    assert e.get("Lens") == "RF85mm F1.2" and e.get("Orientation") == "Rotated 90 right"
    assert e.get("GPS") == "59.90833, 10.75000"                                   # north and east: positive


def test_exif_in_a_png_a_webp_and_a_tiff_and_the_south_west_of_the_world(tmp_path):
    block = sample_block()
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4s", len(block), b"eXIf") + block + b"\x00\x00\x00\x00"
    webp = b"RIFF" + struct.pack("<I", 0) + b"WEBP" + b"EXIF" + struct.pack("<I", len(block)) + block
    for name, data in (("a.png", png), ("a.webp", webp), ("a.tif", block)):
        assert ex.read_exif(write(tmp_path / name, data)).get("Camera") == "Canon EOS R6", name
    south = tiff([], [], [(0x0001, 2, ["S"]), (0x0002, 5, [(33, 1), (51, 1), (0, 1)]), (0x0003, 2, ["W"]), (0x0004, 5, [(18, 1), (25, 1), (0, 1)])])
    assert ex.parse(south).get("GPS") == "-33.85000, -18.41667"


def test_a_photo_without_exif_or_with_a_damaged_block_is_a_note_not_an_error(tmp_path):
    assert ex.read_exif(write(tmp_path / "plain.jpg", JPEG)).error == "no EXIF block"
    assert ex.read_exif(str(tmp_path / "missing.jpg")).error
    cut = sample_block()[:30]
    got = ex.read_exif(write(tmp_path / "cut.jpg", as_jpeg(cut)))
    assert got.orientation in range(1, 9)                                          # whatever could be read, no exception
    assert ex.parse(b"II*\x00\xff\xff\xff\x7f").fields == []
    assert ex.parse(b"junk").error


# hex ------------------------------------------------------------------------------------------------------------------------------
def test_rows_are_read_on_demand_and_formatted(tmp_path):
    data = bytes(range(256)) * 3 + b"end"
    h = hv.HexFile(write(tmp_path / "f.bin", data))
    try:
        assert h.size == 771 and h.rows == 49 and h.row(0) == bytes(range(16)) and h.row(48) == data[768:]
        assert h.read(-1, 5) == b"" and h.read(771, 5) == b"" and h.read(768, 100) == b"end"
        off, hexes, text = hv.format_row(16, data[16:32])
        assert off == "00000010" and hexes.startswith("10 11 12 13 14 15 16 17  18 19") and text == "................"
        off, hexes, text = hv.format_row(768, b"end")
        assert hexes.startswith("65 6E 64") and text == "end" and len(hexes) == len(hv.format_row(0, bytes(16))[1])
        assert hv.offset_digits(5) == 8 and hv.offset_digits(2 ** 40) == 10
    finally:
        h.close()


def test_the_search_goes_forward_back_and_around_and_can_ignore_case(tmp_path):
    data = b"..Hello....hello....HELLO.."
    h = hv.HexFile(write(tmp_path / "s.bin", data))
    try:
        assert h.find(b"Hello", 0) == 2 and h.find(b"hello", 0) == 11 and h.find(b"hello", 0, ignore_case=True) == 2
        assert h.find(b"hello", 12, ignore_case=True) == 20
        assert h.find(b"HELLO", 5) == 20 and h.find(b"HELLO", 21) == 20                      # wrapped around to the start
        assert h.find(b"HELLO", 21, wrap=False) == -1
        assert h.find(b"Hello", 20, forward=False) == 2 and h.find(b"hello", 12, forward=False, ignore_case=True) == 11
        assert h.find(b"Hello", 1, forward=False) == 2                                       # wrapped around to the end
        assert h.find(b"nothing", 0) == -1 and h.find(b"", 0) == -1
    finally:
        h.close()


def test_a_match_across_two_blocks_is_found_and_a_cancel_stops_the_search(tmp_path, monkeypatch):
    monkeypatch.setattr(hv, "CHUNK", 16)
    data = b"A" * 14 + b"NEEDLE" + b"B" * 40
    h = hv.HexFile(write(tmp_path / "x.bin", data))
    try:
        assert h.find(b"NEEDLE", 0) == 14 and h.find(b"NEEDLE", 30, forward=False) == 14
        token = CancelToken()
        token.cancel()
        with pytest.raises(Cancelled):
            h.find(b"nope", 0, cancel=token)
    finally:
        h.close()


def test_what_a_person_types_becomes_bytes_and_the_inspector_reads_numbers():
    assert hv.parse_hex("DE AD be ef") == b"\xde\xad\xbe\xef" and hv.parse_hex("0xDEADBEEF") == b"\xde\xad\xbe\xef"
    assert hv.parse_hex("de,ad") == b"\xde\xad"
    assert hv.parse_hex("DEA") is None and hv.parse_hex("hello") is None and hv.parse_hex("") is None
    got = dict(hv.inspect(b"\x01\x02\x03\x04\x00\x00\x00\x00"))
    assert got["8-bit"].startswith("1") and got["16-bit"].startswith("513") and got["32-bit"].startswith("67305985")
    assert hv.inspect(b"") == [] and [k for k, _v in hv.inspect(b"\xff")] == ["8-bit"] and "signed -1" in hv.inspect(b"\xff")[0][1]


# Markdown -------------------------------------------------------------------------------------------------------------------------
def test_raw_html_becomes_text_but_code_and_autolinks_are_left_alone():
    text = "# T\n\n<script>alert(1)</script> and <b>bold</b>\n\n`<b>in code</b>` and <https://example.com/x>\n\n```html\n<div>block</div>\n```\n\nend <i>x</i>"
    out = ms.escape_html(text)
    assert "&lt;script>" in out and "&lt;b>bold" in out and "&lt;i>x" in out
    assert "`<b>in code</b>`" in out and "<div>block</div>" in out and "<https://example.com/x>" in out
    assert ms.escape_html("no html here") == "no html here" and ms.escape_html("") == ""


def test_links_are_limited_to_the_web_mail_and_paths_on_this_computer(tmp_path):
    base = str(tmp_path)
    assert ms.classify_link("https://example.com/a?b=1") == ("web", "https://example.com/a?b=1")
    assert ms.classify_link("HTTP://example.com")[0] == "web" and ms.classify_link("mailto:me@example.com")[0] == "mail"
    for refused in ("javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://host/file", "vbscript:x", "file://server/share/x", "", "   "):
        assert ms.classify_link(refused, base) == ("", ""), refused
    kind, target = ms.classify_link("docs/other%20file.md", base)
    assert kind == "file" and target == os.path.normpath(os.path.join(base, "docs", "other file.md"))
    assert ms.classify_link("#heading-two") == ("anchor", "heading-two")
    assert ms.classify_link("C:\\Users\\me\\a.txt", base)[0] == "file"
    assert ms.classify_link("file:///C:/Users/me/a.txt")[1].endswith("a.txt")
    assert ms.local_target("x.md", base) and ms.local_target("https://x.y", base) is None


def test_a_big_file_is_not_rendered():
    assert not ms.too_big(256 * 1024) and ms.too_big(256 * 1024 + 1)
