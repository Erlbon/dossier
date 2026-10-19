import os

import pytest

from dossier.core.textedit import (BinaryFile, EncodingProblem, FileChangedOnDisk, FileTooLarge, convert_eol,
                                   encode_text, load_document, save_document)


def make(tmp_path, data: bytes, name="f.txt") -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def roundtrip(tmp_path, data: bytes, edit=lambda t: t):
    path = make(tmp_path, data)
    doc = load_document(path)
    save_document(doc, edit(doc.text))
    return open(path, "rb").read(), doc


# nothing the user did not touch is changed ------------------------------------------------------------------------
@pytest.mark.parametrize("data", [
    b"plain ascii\nsecond\n",
    b"windows\r\nline\r\n",
    b"old mac\rline\r",
    "æøå utf8\n".encode("utf-8"),
    b"\xef\xbb\xbfwith bom\r\n",
    "ansi \xe6\xf8\xe5\r\n".encode("latin-1"),
    "wide\r\ntext\r\n".encode("utf-16"),
    "wide le\n".encode("utf-16-le"),
    "wide be\n".encode("utf-16-be"),
    b"no trailing newline",
    b"",
])
def test_an_unedited_file_is_saved_byte_for_byte(tmp_path, data):
    out, doc = roundtrip(tmp_path, data)
    assert out == data


def test_encoding_bom_and_line_break_are_detected(tmp_path):
    doc = load_document(make(tmp_path, b"\xef\xbb\xbfa\r\nb\r\n"))
    assert doc.encoding == "utf-8" and doc.bom == b"\xef\xbb\xbf" and doc.eol == "\r\n" and not doc.mixed_eol
    assert doc.text == "a\nb\n"
    doc = load_document(make(tmp_path, "x\r\ny".encode("utf-16"), "w.txt"))
    assert doc.encoding == "utf-16-le" and doc.bom == b"\xff\xfe"


def test_an_edit_keeps_the_files_style(tmp_path):
    out, doc = roundtrip(tmp_path, b"one\r\ntwo\r\n", lambda t: t.replace("two", "TWO\nthree"))
    assert out == b"one\r\nTWO\r\nthree\r\n"
    out, _ = roundtrip(tmp_path, "ansi \xe6\n".encode("latin-1"), lambda t: t + "\xf8\n")
    assert out == "ansi \xe6\n\xf8\n".encode("latin-1")


def test_mixed_line_breaks_are_reported_and_written_as_the_most_common(tmp_path):
    doc = load_document(make(tmp_path, b"a\r\nb\r\nc\nd\r\n"))
    assert doc.mixed_eol and doc.eol == "\r\n"


def test_a_file_that_is_not_valid_utf8_opens_as_windows_1252_and_never_loses_bytes(tmp_path):
    data = b"caf\xe9 \x81 \x8d\n"                       # 0x81 and 0x8D have no Windows-1252 meaning
    out, doc = roundtrip(tmp_path, data)
    assert out == data and doc.encoding in ("windows-1252", "iso-8859-1")


def test_forcing_an_encoding_that_does_not_fit_is_an_error_not_silent_damage(tmp_path):
    path = make(tmp_path, "æx".encode("utf-8"))                  # three bytes: not whole UTF-16 units
    with pytest.raises(EncodingProblem):
        load_document(path, "utf-16-le")
    assert load_document(path, "windows-1252").text == "Ã¦x"


def test_a_character_the_encoding_cannot_hold_is_reported_before_anything_is_written(tmp_path):
    path = make(tmp_path, b"ascii only \xe6\n")
    doc = load_document(path)
    assert doc.encoding in ("windows-1252", "iso-8859-1")
    with pytest.raises(EncodingProblem) as info:
        save_document(doc, doc.text + "中")
    assert info.value.char == "中" and open(path, "rb").read() == b"ascii only \xe6\n"


def test_binary_and_huge_files_are_refused(tmp_path):
    with pytest.raises(BinaryFile):
        load_document(make(tmp_path, b"MZ\x00\x01\x02" * 50))
    with pytest.raises(FileTooLarge):
        load_document(make(tmp_path, b"x" * 200, "big.txt"), max_bytes=100)


# saving safely -----------------------------------------------------------------------------------------------------
def test_saving_refuses_when_another_program_changed_the_file(tmp_path):
    path = make(tmp_path, b"original\n")
    doc = load_document(path)
    with open(path, "ab") as f:
        f.write(b"someone else\n")
    with pytest.raises(FileChangedOnDisk):
        save_document(doc, "mine\n")
    assert open(path, "rb").read() == b"original\nsomeone else\n"
    save_document(doc, "mine\n", force=True)
    assert open(path, "rb").read() == b"mine\n"


def test_two_saves_in_a_row_work_because_the_returned_document_is_current(tmp_path):
    path = make(tmp_path, b"v1\n")
    doc = load_document(path)
    doc = save_document(doc, "v2\n")
    doc = save_document(doc, "v3\n")
    assert open(path, "rb").read() == b"v3\n" and doc.text == "v3\n"


def test_no_temporary_file_is_left_behind_even_when_the_save_fails(tmp_path):
    path = make(tmp_path, b"x\xe6\n")                          # Windows-1252: it has no code for Chinese
    doc = load_document(path)
    with pytest.raises(EncodingProblem):
        save_document(doc, "中", force=True)
    assert os.listdir(tmp_path) == ["f.txt"]
    save_document(doc, "ok\n")
    assert os.listdir(tmp_path) == ["f.txt"]


def test_the_line_break_can_be_changed_on_purpose(tmp_path):
    path = make(tmp_path, b"a\nb\n")
    doc = convert_eol(load_document(path), "\r\n")
    save_document(doc, doc.text)
    assert open(path, "rb").read() == b"a\r\nb\r\n"
    assert encode_text(doc, "x\ny") == b"x\r\ny"
