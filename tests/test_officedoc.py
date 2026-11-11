"""The text of Word documents for the viewer's Document mode (core/officedoc.py): .doc through the Office 97 container reader,
.docx through its XML. tests/data/word97.doc was saved by Word with personal information removed."""
import os
import shutil
import struct
import zipfile

import pytest

from dossier.core import officedoc as od
from dossier.core import viewmodes as vm

WORD97 = os.path.join(os.path.dirname(__file__), "data", "word97.doc")
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_a_word_97_document_gives_its_text_with_the_field_result_and_without_the_field_code():
    doc = od.read_document(WORD97)
    assert doc.kind == "Word 97 document" and doc.markdown is None
    text = doc.plain
    assert text.startswith("Vrakkart 1910\n\nPlain start, bold words and italic. Blåbær, æøå, Ω and 5 * 3 = 15.")
    assert "Page 1" in text and "PAGE" not in text                     # the field's result, not its code
    assert "first item\n\nsecond item" in text
    assert "Ship\tYear\tPlace" in text                                  # a table row: cells by tabs
    assert text.endswith("After the table.")
    assert vm.modes_for(WORD97) == ["document", "hex"]


def test_a_damaged_or_locked_word_97_document_is_an_error_in_words_not_a_crash(tmp_path):
    data = open(WORD97, "rb").read()
    cut = tmp_path / "cut.doc"
    cut.write_bytes(data[:3000])
    with pytest.raises(od.DocumentError):
        od.read_document(str(cut))
    locked = tmp_path / "locked.doc"
    shutil.copy(WORD97, locked)
    with od.Compound(str(locked)) as cf:                                # set fEncrypted in the WordDocument stream's header
        start = cf._entry(cf.names["worddocument"])[5]
        offset = (start + 1) * cf.sector + 0x0A
    raw = bytearray(locked.read_bytes())
    raw[offset:offset + 2] = struct.pack("<H", struct.unpack_from("<H", raw, offset)[0] | 0x0100)
    locked.write_bytes(bytes(raw))
    with pytest.raises(od.DocumentError, match="password"):
        od.read_document(str(locked))
    loop = bytearray(data)                                              # a FAT that points a sector at itself must not hang
    with od.Compound(WORD97) as cf:
        fat_sector = struct.unpack_from("<I", data, 76)[0]
        first_dir = struct.unpack_from("<I", data, 48)[0]
    struct.pack_into("<I", loop, (fat_sector + 1) * 512 + 4 * first_dir, first_dir)
    looped = tmp_path / "loop.doc"
    looped.write_bytes(bytes(loop))
    with pytest.raises(od.DocumentError):
        od.read_document(str(looped))


def make_docx(path, body, styles=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
        if styles is not None:
            z.writestr("word/styles.xml", f'<?xml version="1.0"?><w:styles {W}>{styles}</w:styles>')
    return str(path)


STYLES = ('<w:style w:type="paragraph" w:styleId="Overskrift1"><w:name w:val="heading 1"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Tittel"><w:name w:val="Title"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Min"><w:name w:val="Min overskrift"/><w:basedOn w:val="Overskrift1"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Punkt"><w:name w:val="List Bullet"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>')


def para(text, style="", rpr=""):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def test_a_docx_becomes_markdown_with_headings_in_any_language_emphasis_lists_and_tables(tmp_path):
    body = (para("Vrakkart", "Tittel") + para("Lista", "Overskrift1") + para("Based on a heading", "Min")
            + '<w:p><w:r><w:t xml:space="preserve">Plain, </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">bold </w:t></w:r>'
              '<w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>not bold</w:t></w:r><w:del><w:r><w:delText>gone</w:delText></w:r></w:del>'
              '<w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:t>7</w:t></w:r><w:r><w:br/><w:t>next line</w:t></w:r></w:p>'
            + para("first", "Punkt") + para("second", "Punkt")
            + para("5 * 3 [x] &amp; _y_ # 1. not a list")
            + '<w:tbl><w:tr><w:tc>' + para("Ship") + '</w:tc><w:tc>' + para("Year") + '</w:tc></w:tr>'
              '<w:tr><w:tc>' + para("Haabet") + '</w:tc><w:tc>' + para("a|b") + '</w:tc></w:tr></w:tbl>'
            + '<w:sdt><w:sdtContent>' + para("In a content control") + '</w:sdtContent></w:sdt>')
    path = make_docx(tmp_path / "a.docx", body, STYLES)
    doc = od.read_document(path)
    md = doc.markdown.split("\n")
    assert md[:6] == ["# Vrakkart", "", "# Lista", "", "# Based on a heading", ""]
    assert md[6] == "Plain, **bold** not bold7\\"                       # deleted text and the field code are left out
    assert md[7] == "next line"
    assert md[9:11] == ["- first", "- second"]                         # one list, no blank line inside
    assert md[12] == "5 \\* 3 \\[x\\] \\& \\_y\\_ \\# 1. not a list"
    assert md[14:17] == ["| Ship | Year |", "| --- | --- |", "| Haabet | a\\|b |"]
    assert md[-1] == "In a content control"
    assert "Haabet\ta|b" in doc.plain and "**" not in doc.plain


def test_a_line_that_would_start_a_list_or_quote_stays_a_line(tmp_path):
    doc = od.read_document(make_docx(tmp_path / "a.docx", para("- not a list") + para("1. nor this") + para("&gt; nor a quote")))
    assert doc.markdown.split("\n\n") == ["\\- not a list", "\\1. nor this", "\\> nor a quote"]


def test_a_zip_that_is_no_docx_and_a_hostile_one_are_errors(tmp_path):
    with zipfile.ZipFile(tmp_path / "x.docx", "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(od.DocumentError, match="not a Word document"):
        od.read_document(str(tmp_path / "x.docx"))
    with zipfile.ZipFile(tmp_path / "bomb.docx", "w") as z:
        z.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    with pytest.raises(od.DocumentError):
        od.read_document(str(tmp_path / "bomb.docx"))
    (tmp_path / "broken.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(od.DocumentError):
        od.read_document(str(tmp_path / "broken.docx"))
