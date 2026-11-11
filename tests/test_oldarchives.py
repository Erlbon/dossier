"""Old compressed files 7-Zip cannot open (core/oldarchives.py): named by their first bytes, and ARC/PAK, ZOO, ACE, HA and LBR
listed from their headers. The test files are built here from the published header layouts; no real 1980s archive is in the
repository. Also the old-DOS-zip fallback to 7-Zip (core/archives.py)."""
import io
import struct
import zipfile

import pytest

from dossier.core import archives, officesheet as osh, oldarchives as oa, viewmodes as vm

DOS_DATE = ((1989 - 1980) << 9) | (7 << 5) | 14          # 1989-07-14
DOS_TIME = (13 << 11) | (37 << 5) | (30 // 2)             # 13:37:30


def rows(book, sheet=0):
    return book.sheets[sheet].rows


def info(book):
    return {r[0]: r[1] for r in book.sheets[-1].rows[1:]}


def arc_entry(method, name, data=b"x" * 10, original=20):
    if method == 0:
        return b"\x1a\x00"
    head = b"\x1a" + bytes([method]) + name.encode().ljust(13, b"\x00") + struct.pack("<IHHH", len(data), DOS_DATE, DOS_TIME, 0xBEEF)
    return head + (b"" if method == 1 else struct.pack("<I", original)) + data


def test_an_arc_archive_is_listed_from_its_headers_with_subfolders(tmp_path):
    path = tmp_path / "GAMES.ARC"
    path.write_bytes(arc_entry(8, "README.DOC") + arc_entry(30, "SUB", data=b"") + arc_entry(2, "A.TXT", b"abc", 3)
                     + arc_entry(0, "") + arc_entry(9, "B.EXE", b"y" * 5, 900) + arc_entry(0, ""))   # a subfolder ends as an archive does
    book = osh.read_workbook(str(path))
    assert book.kind == "ARC archive (SEA ARC or PKPAK)" and [s.name for s in book.sheets] == ["Files", "Info"]
    assert rows(book)[0] == ["Name", "Size", "Packed", "Method", "Date", "CRC", "Note"]
    assert rows(book)[1] == ["README.DOC", "20", "10", "crunched", "1989-07-14 13:37:30", "BEEF", ""]
    assert [r[0] for r in rows(book)[1:]] == ["README.DOC", "SUB/", "SUB/A.TXT", "B.EXE"]
    assert rows(book)[4][3] == "squashed"
    f = info(book)
    assert f["Members"] == "4" and "DOS" in f["Platform and years"] and "unar" in f["Unpacked by"]
    assert vm.mode_for(str(path)) == "sheet" and not vm.opens_in_viewer(str(path), "viewer")


def test_a_zoo_archive_lists_long_names_folders_and_deleted_entries(tmp_path):
    header = b"ZOO 2.10 Archive.\x1a\x00\x00" + struct.pack("<Ii", 0xFDC4A7DC, 34) + b"\x00" * 6

    def entry(at, nxt, name, deleted=0, long=b"", folder=b""):
        base = struct.pack("<IBBIIHHHII", 0xFDC4A7DC, 2, 2, nxt, 0, DOS_DATE, DOS_TIME, 0x1234, 1000, 400)
        base += bytes([2, 1, deleted, 0]) + struct.pack("<IH", 0, 0) + name.ljust(13, b"\x00")
        var = bytes([len(long), len(folder)]) + long + folder
        return base + struct.pack("<HBH", len(var), 0x7F, 0) + var
    first = entry(34, 0, b"")                                # placeholder to measure
    e1_len = len(entry(0, 0, b"READ.ME", long=b"Read me first.txt", folder=b"docs"))
    e1 = entry(34, 34 + e1_len, b"READ.ME", long=b"Read me first.txt", folder=b"docs")
    e2_at = 34 + e1_len
    e2_len = len(entry(0, 0, b"OLD.TXT", deleted=1))
    e2 = entry(e2_at, e2_at + e2_len, b"OLD.TXT", deleted=1)
    end = struct.pack("<IBBI", 0xFDC4A7DC, 2, 0, 0) + b"\x00" * 60
    path = tmp_path / "x.zoo"
    path.write_bytes(header + e1 + e2 + end)
    book = osh.read_workbook(str(path))
    assert [r[0] for r in rows(book)[1:]] == ["docs/Read me first.txt", "OLD.TXT"]
    assert rows(book)[1][1:6] == ["1000", "400", "LZH", "1989-07-14 13:37:30", "1234"]
    assert rows(book)[2][6] == "deleted" and info(book)["Deleted entries still in the file"] == "1"
    assert first                                              # (the measuring entry is only for offsets)


def test_ace_ha_and_lbr_are_listed(tmp_path):
    main = struct.pack("<BH", 0, 0) + b"**ACE**" + b"\x00" * 20
    ace = struct.pack("<HH", 0, len(main)) + main
    name = b"dir\\file.txt"
    body = (struct.pack("<BH", 1, 0x4001) + struct.pack("<IIIIII", 3, 70, (DOS_DATE << 16) | DOS_TIME, 0x20, 0xCAFEBABE, 1)
            + struct.pack("<HH", 0, len(name)) + name)
    ace += struct.pack("<HH", 0, len(body)) + body + b"abc"
    (tmp_path / "a.ace").write_bytes(ace)
    book = osh.read_workbook(str(tmp_path / "a.ace"))
    assert book.kind == "ACE archive" and rows(book)[1] == ["dir/file.txt", "70", "3", "LZ77 (ACE 1)", "1989-07-14 13:37:30",
                                                             "CAFEBABE", "password"]
    ha = b"HA" + struct.pack("<H", 1) + bytes([0x22]) + struct.pack("<IIII", 2, 9, 0xABCD, 0) + b"src\xff\x00main.c\x00" + b"\x00" + b"zz"
    (tmp_path / "b.ha").write_bytes(ha)
    assert rows(osh.read_workbook(str(tmp_path / "b.ha")))[1][:4] == ["src/main.c", "9", "2", "HSC"]
    directory = b"\x00" + b" " * 11 + struct.pack("<HH", 0, 1) + b"\x00" * 16
    # status, name, ext, index, length, CRC, created, changed, two times, then the pad count at offset 26
    good = b"\x00" + b"HELLO   COM" + struct.pack("<HHHHHHH", 1, 2, 0x55AA, 0, 3000, 0, 0) + bytes([28]) + b"\x00" * 5
    gone = b"\xfe" + b"OLD     TXT" + struct.pack("<HHHHHHH", 3, 1, 0, 0, 0, 0, 0) + b"\x00" * 6
    lbr = (directory + good + gone + b"\xff" * 32).ljust(128 * 4, b"\x00")
    (tmp_path / "c.lbr").write_bytes(lbr)
    book = osh.read_workbook(str(tmp_path / "c.lbr"))
    assert rows(book)[1][:5] == ["HELLO.COM", "228", "256", "stored", "1986-03-19"]       # day 1 is 1 January 1978
    assert rows(book)[2][0] == "OLD.TXT" and rows(book)[2][6] == "deleted"


def test_formats_dossier_only_names_say_what_would_open_them(tmp_path):
    for name, data, title in (("x.sit", b"SIT!" + b"\x00" * 40, "StuffIt archive"), ("disk.dms", b"DMS!" + b"\x00" * 40, "DMS disk"),
                              ("a.sqz", b"HLSQZ" + b"\x00" * 40, "SQZ archive"), ("READ.MQE", b"\x76\xff" + b"\x00" * 40, "Squeezed")):
        (tmp_path / name).write_bytes(data)
        book = osh.read_workbook(str(tmp_path / name))
        assert book.kind.startswith(title) and [s.name for s in book.sheets] == ["Info"]
        assert info(book)["Members"].startswith("not listed")
    (tmp_path / "x.arc").write_bytes(b"plain text, not an archive")
    assert oa.kind_of(open(tmp_path / "x.arc", "rb").read(), str(tmp_path / "x.arc")) == ""
    (tmp_path / "x.dat").write_bytes(b"\x1a\x08" + b"\x00" * 40)                  # a weak signature needs the usual name
    assert vm.mode_for(str(tmp_path / "x.dat")) == "hex"


def test_a_damaged_listing_keeps_what_it_read_and_says_where_it_stopped(tmp_path):
    path = tmp_path / "cut.arc"
    path.write_bytes(arc_entry(8, "ONE.TXT") + arc_entry(8, "TWO.TXT")[:20])
    book = osh.read_workbook(str(path))
    assert [r[0] for r in rows(book)[1:]] == ["ONE.TXT"] and "damaged" in info(book)["Listing"]


def test_an_old_dos_zip_member_python_cannot_unpack_goes_to_7zip(tmp_path, monkeypatch):
    path = tmp_path / "old.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("GAME/README.TXT", "hello")
    backend = archives.ZipBackend()
    member = backend.members(str(path))[0]

    def refuse(self, *a, **k):
        raise NotImplementedError("That compression method is not supported")
    monkeypatch.setattr(zipfile.ZipFile, "open", refuse)
    opened = []
    monkeypatch.setattr(archives, "find_seven_zip", lambda: "7z")
    monkeypatch.setattr(archives.ExternalBackend, "open", lambda self, archive, m: opened.append((self.exe, archive, m.ref))
                        or io.BytesIO(b"hello"))
    assert backend.open(str(path), member).read() == b"hello"
    assert opened == [("7z", str(path), "GAME/README.TXT".replace("/", archives.os.sep))]
    monkeypatch.setattr(archives, "find_seven_zip", lambda: None)
    with pytest.raises(archives.ArchiveError, match="7-Zip or NanaZip would read it"):
        backend.open(str(path), member)
