"""The cheap readers of 2026-11-11 (docs/reader-review-2026-11-11.md): OpenDocument text and spreadsheets, RTF, PowerPoint, EPUB
(core/textdocs.py, core/officesheet.py), CSV/TSV and SQLite (core/datatables.py) and torrent listings (core/torrent.py).
The .odt, .rtf, .pptx, .ods and .pdf in tests/data were saved by Word, PowerPoint and Excel with personal information removed;
the rest are built here."""
import hashlib
import os
import sqlite3
import zipfile

import pytest

from dossier.core import datatables, officedoc as od, officesheet as osh, torrent, viewmodes as vm
from dossier.core.officedoc import DocumentError

DATA = os.path.join(os.path.dirname(__file__), "data")
SAME_AS_WORD = ["# Vrakkart 1910", "", "Plain start, **bold words** and *italic*. Blåbær, æøå, Ω and 5 \\* 3 = 15.", "",
                "## Second heading", "", "- first item", "- second item", "", "Page 1"]


def data(name):
    return os.path.join(DATA, name)


# documents --------------------------------------------------------------------------------------------------------------------------
def test_an_odt_reads_like_the_word_document_it_was_saved_from():
    doc = od.read_document(data("word97.odt"))
    assert doc.kind == "OpenDocument text"
    assert doc.markdown.split("\n")[:10] == SAME_AS_WORD
    assert "| Ship | Year | Place |" in doc.markdown and doc.markdown.endswith("After the table.")


def test_rtf_follows_each_fonts_code_page_and_keeps_emphasis():
    doc = od.read_document(data("word97.rtf"))
    assert doc.kind == "RTF document"
    assert doc.markdown.split("\n")[2] == SAME_AS_WORD[2]               # the Ω is a Greek-font byte in Word's RTF
    assert "Page 1" in doc.plain and "Ship\tYear\tPlace" in doc.plain and doc.plain.endswith("After the table.")


def test_rtf_unicode_escapes_skip_their_fallback_and_hidden_groups_stay_hidden(tmp_path):
    rtf = tmp_path / "a.rtf"
    rtf.write_bytes(b"{\\rtf1\\ansi\\ansicpg1252{\\fonttbl{\\f0\\fswiss Arial;}}{\\info{\\author Someone}}"
                    b"{\\*\\generator Hidden;}\\uc1 Ol\\u233\\'e9 and caf\\'e9\\par {\\b bold}\\b0  \\{x\\}\\par "
                    b"{\\field{\\*\\fldinst PAGE}{\\fldrslt 7}}}")
    doc = od.read_document(str(rtf))
    assert doc.plain == "Olé and café\n\nbold {x}\n\n7"
    assert "Someone" not in doc.plain and "Hidden" not in doc.plain
    assert doc.markdown.split("\n\n")[1] == "**bold** \\{x\\}" or doc.markdown.split("\n\n")[1] == "**bold** {x}"
    assert vm.modes_for(str(rtf)) == ["document", "text", "hex"]       # RTF is text underneath
    assert vm.opens_in_viewer(str(rtf), "viewer")                      # so Enter keeps it in the viewer


def test_a_presentation_gives_each_slide_with_title_bullets_tables_and_notes():
    doc = od.read_document(data("deck.pptx"))
    assert doc.kind == "PowerPoint presentation"
    md = doc.markdown
    assert md.index("## Slide 1: Vrakkart 1910") < md.index("## Slide 2: Lista") < md.index("## Slide 3 (hidden)")
    assert "- **Haabet, 1910**\n- Blåbær Ω" in md
    assert "\\- a text box line" in md                                  # a text box is a paragraph, its dash kept as text
    assert "> *Notes:* Speaker note here" in md
    assert "| Ship | Year |" in md and "| Haabet | 1910 |" in md
    assert not vm.opens_in_viewer(data("deck.pptx"), "viewer")


def make_epub(path, encrypted=False, ncx=False, metadata=""):
    nav = ('<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol><li><a href="text/one.xhtml">The Wreck</a></li>'
           '<li><a href="text/two.xhtml#x">The Sea</a></li></ol></nav></body></html>')
    one = ('<?xml version="1.0"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title>'
           '<style>p{}</style></head><body><h1>One</h1><p>It was <em>cold</em> &amp; <b>dark</b>.</p>'
           '<ul><li>first</li><li>second</li></ul><blockquote><p>A quote.</p></blockquote>'
           '<p>- not a list<br/>next line</p><img src="x.png"/><script>alert(1)</script></body></html>')
    two = '<html><body><h2 id="x">Two</h2><pre>  code\n  kept</pre><table><tr><td>a</td><td>b</td></tr></table></body></html>'
    manifest = ('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' if not ncx else
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">' + metadata + '<manifest>' + manifest +
           '<item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="two" href="text/two.xhtml" media-type="application/xhtml+xml"/></manifest>'
           f'<spine{" toc=" + chr(34) + "ncx" + chr(34) if ncx else ""}><itemref idref="cover"/><itemref idref="one"/>'
           '<itemref idref="two"/></spine></package>')
    toc = ('<?xml version="1.0"?><!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">'
           '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap><navPoint><navLabel><text>NCX One</text></navLabel>'
           '<content src="text/one.xhtml"/></navPoint></navMap></ncx>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/toc.ncx", toc)
        z.writestr("OEBPS/text/cover.xhtml", '<html><body><img src="cover.jpg"/></body></html>')
        z.writestr("OEBPS/text/one.xhtml", one)
        z.writestr("OEBPS/text/two.xhtml", two)
        if encrypted:
            z.writestr("META-INF/encryption.xml", '<encryption><EncryptedData><CipherReference URI="OEBPS/text/one.xhtml"/>'
                                                  '</EncryptedData></encryption>')
    return str(path)


def test_an_epub_gives_its_chapters_in_reading_order_with_titles_from_its_table_of_contents(tmp_path):
    doc = od.read_document(make_epub(tmp_path / "book.epub"))
    assert doc.kind == "EPUB book"
    assert [c.title for c in doc.chapters] == ["The Wreck", "The Sea"]          # the cover page has no words and is left out
    one = doc.chapters[0].markdown.split("\n")
    assert one == ["# One", "", "It was *cold* \\& **dark**.", "", "- first", "- second", "", "> A quote.", "",
                   "\\- not a list\\", "next line"]
    assert "alert" not in doc.chapters[0].plain
    assert doc.chapters[1].markdown == "## Two\n\n```\n  code\n  kept\n```\n\na\tb"
    assert doc.markdown == doc.chapters[0].markdown
    ncx = od.read_document(make_epub(tmp_path / "ncx.epub", ncx=True))          # EPUB 2: titles from the NCX (it has a DOCTYPE)
    assert [c.title for c in ncx.chapters] == ["NCX One", "Two"]
    with pytest.raises(DocumentError, match="DRM"):
        od.read_document(make_epub(tmp_path / "drm.epub", encrypted=True))
    assert vm.modes_for(str(tmp_path / "book.epub")) == ["document", "hex"]


def test_xml_that_defines_entities_is_refused_but_a_plain_doctype_is_not():
    assert od.unsafe_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    assert od.unsafe_xml(b'<!DOCTYPE x [ ]><x/>')
    assert not od.unsafe_xml(b'<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://x/ncx.dtd"><ncx/>')
    assert not od.unsafe_xml(b"<!DOCTYPE html><html/>")


# tables -----------------------------------------------------------------------------------------------------------------------------
def test_an_ods_reads_like_the_excel_workbook_it_was_saved_from():
    book = osh.read_workbook(data("book.ods"))
    xls = osh.read_workbook(data("book.xls"))
    assert book.kind == "OpenDocument spreadsheet"
    assert [(s.name, s.hidden) for s in book.sheets] == [("Vrak", False), ("Andre", True)]
    assert [s.rows for s in book.sheets] == [s.rows for s in xls.sheets]      # the time by its cell style, the hidden sheet


def test_csv_and_tsv_by_their_sniffed_delimiter_with_quoted_line_breaks_and_utf16(tmp_path):
    semi = tmp_path / "a.csv"
    semi.write_bytes("﻿Ship;Year;Note\nHaabet;1910;\"two\nlines; one cell\"\nBlåbær;1911;\n".encode("utf-8"))
    book = osh.read_workbook(str(semi))
    assert book.kind == "CSV file"
    assert book.sheets[0].rows == [["Ship", "Year", "Note"], ["Haabet", "1910", "two\nlines; one cell"], ["Blåbær", "1911", ""]]
    tsv = tmp_path / "b.tsv"
    tsv.write_bytes("A\tB\r\n1\t2\r\n".encode("utf-16"))                       # Excel's "Unicode text"
    assert vm.mode_for(str(tsv)) == "sheet" and osh.read_workbook(str(tsv)).sheets[0].rows == [["A", "B"], ["1", "2"]]
    assert vm.modes_for(str(semi)) == ["sheet", "text", "hex"]
    assert vm.opens_in_viewer(str(semi), "viewer")                             # a CSV is text: Enter keeps it in the viewer


def test_a_sqlite_database_is_read_only_with_a_tab_per_table_and_view(tmp_path):
    db = tmp_path / "History"                                                  # no extension: known by its first bytes
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE urls (id INTEGER, url TEXT, visits REAL, icon BLOB);"
                      "INSERT INTO urls VALUES (1, 'https://example.com', 2.5, x'0102'), (2, NULL, 3, NULL);"
                      'CREATE TABLE "odd ""name""" (x); CREATE VIEW busy AS SELECT url FROM urls WHERE visits > 2.6;')
    con.commit()
    con.close()
    before = sorted(os.listdir(tmp_path))
    mtime = os.path.getmtime(db)
    book = osh.read_workbook(str(db))
    assert book.kind == "SQLite database"
    assert [s.name for s in book.sheets] == ['odd "name"', "urls", "busy (view)"]
    assert book.sheets[1].rows == [["id", "url", "visits", "icon"], ["1", "https://example.com", "2.5", "<2 bytes>"],
                                   ["2", "", "3", ""]]
    assert book.sheets[2].rows == [["url"]]
    assert sorted(os.listdir(tmp_path)) == before and os.path.getmtime(db) == mtime      # nothing written, no journal left
    assert vm.mode_for(str(db)) == "sheet" and not vm.opens_in_viewer(str(db), "viewer")


def test_a_slow_view_is_stopped_and_says_so(tmp_path, monkeypatch):
    db = tmp_path / "slow.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE VIEW slow AS WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT x FROM c "
                      "WHERE x < 0;")
    con.close()
    monkeypatch.setattr(datatables, "QUERY_SECONDS", 0.3)
    sheet = osh.read_workbook(str(db)).sheets[0]
    assert sheet.rows[1:] == [] and "Stopped" in sheet.rows[0][0]


# torrents ---------------------------------------------------------------------------------------------------------------------------
def bencode(v) -> bytes:
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, str):
        v = v.encode()
    if isinstance(v, bytes):
        return b"%d:%s" % (len(v), v)
    if isinstance(v, list):
        return b"l" + b"".join(bencode(x) for x in v) + b"e"
    return b"d" + b"".join(bencode(k) + bencode(v[k]) for k in sorted(v)) + b"e"


def test_a_torrent_lists_its_files_and_the_info_hash_its_own_bytes_give(tmp_path):
    info = {"name": "Vrakkart", "piece length": 262144, "pieces": b"\x01" * 40,
            "files": [{"length": 1500, "path": ["maps", "1910.png"]}, {"length": 10, "path": [".pad", "10"], "attr": "p"},
                      {"length": 3_000_000, "path": ["list.csv"]}], "private": 1}
    meta = {"announce": "udp://tracker.example:80", "announce-list": [["udp://tracker.example:80"], ["https://t2.example/a"]],
            "created by": "Tool 1.0", "creation date": 1700000000, "comment": "Wrecks of 1910", "info": info,
            "url-list": "https://seed.example/files/"}
    path = tmp_path / "vrak.torrent"
    path.write_bytes(bencode(meta))
    book = osh.read_workbook(str(path))
    assert book.kind == "Torrent file" and [s.name for s in book.sheets] == ["Files", "Info"]
    files = book.sheets[0].rows
    assert files[0] == ["Path", "Size", "Bytes", "Note"]
    assert files[1][0] == "Vrakkart/maps/1910.png" and files[1][2] == "1500"
    assert files[2][3] == "padding" and files[3][2] == "3000000"
    fields = dict((r[0], r[1]) for r in book.sheets[1].rows[1:] if r[0] not in ("Tracker", "Web seed"))
    expected = hashlib.sha1(bencode(info)).hexdigest()
    assert fields["Info-hash (v1, SHA-1)"] == expected
    assert fields["Magnet link"].startswith(f"magnet:?xt=urn:btih:{expected}&dn=Vrakkart&tr=udp%3A%2F%2Ftracker.example%3A80")
    assert fields["Creation date"] == "2023-11-14 22:13:20 UTC" and fields["Private"] == "yes" and fields["Pieces"] == "2"
    assert fields["Files"] == "3" and "3,001,500 bytes" in fields["Total size"]
    trackers = [r[1] for r in book.sheets[1].rows if r[0] == "Tracker"]
    assert trackers == ["udp://tracker.example:80", "https://t2.example/a"]
    assert [r[1] for r in book.sheets[1].rows if r[0] == "Web seed"] == ["https://seed.example/files/"]
    assert vm.mode_for(str(path)) == "sheet" and not vm.opens_in_viewer(str(path), "viewer")   # Enter would start a download


def test_a_v2_torrent_walks_its_file_tree_and_a_hostile_one_is_an_error(tmp_path):
    info = {"name": "x", "meta version": 2, "piece length": 16384,
            "file tree": {"a.txt": {"": {"length": 5, "pieces root": b"r" * 32}}, "sub": {"b.bin": {"": {"length": 7}}}}}
    path = tmp_path / "v2.torrent"
    path.write_bytes(bencode({"info": info}))
    book = osh.read_workbook(str(path))
    assert [r[0] for r in book.sheets[0].rows[1:]] == ["x/a.txt", "x/sub/b.bin"]
    fields = dict((r[0], r[1]) for r in book.sheets[1].rows[1:])
    assert fields["Info-hash (v2, SHA-256)"] == hashlib.sha256(bencode(info)).hexdigest() and fields["Version"] == "v2"
    for bad in (b"d4:infod" * 200, b"d4:info", b"d4:spami1ee", b"d3:abc999999:x"):
        (tmp_path / "bad.torrent").write_bytes(bad)
        with pytest.raises(DocumentError):
            torrent.torrent_sheets(str(tmp_path / "bad.torrent"))
