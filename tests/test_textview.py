import time

import pytest

from dossier.core.progress import Cancelled, CancelToken
from dossier.core.textview import (AUTO, TextSource, TextTooLarge, detect_encoding, looks_binary)


def src(tmp_path, data: bytes, encoding=AUTO, name="f.txt") -> TextSource:
    p = tmp_path / name
    p.write_bytes(data)
    s = TextSource(str(p), encoding)
    s.build_index()
    return s


# encodings -------------------------------------------------------------------------------------
def test_detection_by_bom_validity_and_zero_pattern():
    assert detect_encoding("héllo".encode("utf-8")) == "utf-8"
    assert detect_encoding(b"\xef\xbb\xbfabc") == "utf-8"
    assert detect_encoding("héllo".encode("windows-1252")) == "windows-1252"
    assert detect_encoding("abc".encode("utf-16")) == "utf-16"
    assert detect_encoding("hello world".encode("utf-16-le")) == "utf-16-le"
    assert detect_encoding("hello world".encode("utf-16-be")) == "utf-16-be"
    assert detect_encoding(b"plain ascii") == "utf-8"


def test_a_sample_cut_inside_a_multibyte_character_is_still_utf8():
    data = ("æøå" * 10).encode("utf-8")
    assert detect_encoding(data[:-1]) == "utf-8"


def test_binary_is_recognised_but_wide_text_is_not_binary():
    assert looks_binary(b"MZ\x00\x01\x02", "windows-1252")
    assert not looks_binary("hello".encode("utf-16"), "utf-16")


# lines -----------------------------------------------------------------------------------------
def test_lines_with_lf_crlf_and_no_trailing_newline(tmp_path):
    s = src(tmp_path, b"one\ntwo\r\nthree")
    assert s.line_count == 3
    assert s.lines(0, 5) == ["one", "two", "three"]
    s.close()


def test_a_trailing_newline_adds_no_empty_line_but_a_blank_line_does(tmp_path):
    s = src(tmp_path, b"a\nb\n")
    assert s.line_count == 2
    s2 = src(tmp_path, b"a\n\nb\n", name="g.txt")
    assert s2.line_count == 3 and s2.line(1) == ""
    s.close()
    s2.close()


def test_empty_file_has_no_lines(tmp_path):
    s = src(tmp_path, b"")
    assert s.line_count == 0 and s.line(0) == ""
    s.close()


def test_utf8_bom_is_not_shown_and_text_decodes(tmp_path):
    s = src(tmp_path, b"\xef\xbb\xbfh\xc3\xa9llo\nw\xc3\xb8rld\n")
    assert s.lines(0, 2) == ["héllo", "wørld"] and s.encoding == "utf-8"
    s.close()


def test_forcing_an_encoding_changes_the_text(tmp_path):
    data = "æøå\nlinje\n".encode("windows-1252")
    s = src(tmp_path, data)
    assert s.encoding == "windows-1252" and s.line(0) == "æøå"
    s.set_encoding("iso-8859-1")
    s.build_index()
    assert s.line(0) == "æøå" and s.line_count == 2
    s.set_encoding("cp437")
    s.build_index()
    assert s.line(0) != "æøå"
    s.close()


def test_utf16_files_are_viewable_with_both_line_endings(tmp_path):
    s = src(tmp_path, "første\r\nandre\r\n".encode("utf-16"))
    assert s.encoding == "utf-16" and s.lines(0, 5) == ["første", "andre"]
    s.close()


def test_a_huge_utf16_file_is_refused_not_loaded(tmp_path, monkeypatch):
    import dossier.core.textview as tv
    monkeypatch.setattr(tv, "MAX_WIDE_BYTES", 100)
    p = tmp_path / "w.txt"
    p.write_bytes(("x" * 200).encode("utf-16"))
    s = TextSource(str(p))
    with pytest.raises(TextTooLarge):
        s.build_index()
    s.close()


def test_an_enormous_line_is_cut(tmp_path):
    s = src(tmp_path, b"x" * 100000 + b"\nshort\n")
    assert s.line(0).endswith(" ...") and len(s.line(0)) < 21000 and s.line(1) == "short"
    s.close()


def test_big_file_is_indexed_and_any_line_is_reachable(tmp_path):
    n = 300_000
    data = b"".join(b"line %d\n" % i for i in range(n))
    s = src(tmp_path, data)
    assert s.line_count == n and s.complete
    assert s.line(0) == "line 0" and s.line(n - 1) == f"line {n - 1}" and s.line(123456) == "line 123456"
    s.close()


def test_indexing_reports_progress_and_can_be_cancelled(tmp_path):
    p = tmp_path / "big.txt"
    p.write_bytes(b"x\n" * 5_000_000)             # 10 MB: more than one chunk
    s = TextSource(str(p))
    seen = []
    s.build_index(progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (s.size, s.size) and len(seen) >= 2
    token = CancelToken()
    token.cancel()
    s2 = TextSource(str(p))
    with pytest.raises(Cancelled):
        s2.build_index(cancel=token)
    s.close()
    s2.close()


def test_follow_adds_new_lines_and_a_shrunk_file_is_reindexed(tmp_path):
    p = tmp_path / "log.txt"
    p.write_bytes(b"a\nb\n")
    s = TextSource(str(p))
    s.build_index()
    assert s.line_count == 2
    with open(p, "ab") as f:
        f.write(b"c\nd")
    assert s.refresh() and s.line_count == 4 and s.line(3) == "d"
    assert not s.refresh()
    p.write_bytes(b"x\n")
    assert s.refresh() and s.line_count == 1 and s.line(0) == "x"
    s.close()


# search ------------------------------------------------------------------------------------------
def test_find_forward_case_sensitive_and_insensitive(tmp_path):
    s = src(tmp_path, b"alpha\nBeta beta\ngamma\n")
    assert s.find("beta", case_sensitive=True) == (1, 5)
    assert s.find("beta", case_sensitive=False) == (1, 0)
    assert s.find("beta", 1, 1, case_sensitive=False) == (1, 5)
    assert s.find("beta", 1, 6, case_sensitive=False) is None
    assert s.find("zzz") is None
    s.close()


def test_find_backward(tmp_path):
    s = src(tmp_path, b"x one\ntwo x\nthree x x\n")
    assert s.find("x", 2, 8, forward=False) == (2, 6)
    assert s.find("x", 2, 6, forward=False) == (1, 4)
    assert s.find("x", 1, 4, forward=False) == (0, 0)
    assert s.find("x", 0, 0, forward=False) is None
    s.close()


def test_find_non_ascii_needle_in_utf8_and_in_a_single_byte_encoding(tmp_path):
    s = src(tmp_path, "første linje\nandre ÆØÅ\n".encode("utf-8"))
    assert s.find("ørste", case_sensitive=True) == (0, 1)
    assert s.find("æøå", case_sensitive=False) == (1, 6)
    s2 = src(tmp_path, "første\nÆØÅ\n".encode("windows-1252"), name="w.txt")
    assert s2.find("ØÅ", case_sensitive=True) == (1, 1)
    s.close()
    s2.close()


def test_find_columns_count_characters_not_bytes(tmp_path):
    s = src(tmp_path, "ææææ needle\n".encode("utf-8"))
    assert s.find("needle", case_sensitive=True) == (0, 5)
    s.close()


def test_find_in_wide_text(tmp_path):
    s = src(tmp_path, "første\nandre Linje\n".encode("utf-16"))
    assert s.find("linje") == (1, 6)
    s.close()


def test_a_long_search_can_be_cancelled(tmp_path):
    s = src(tmp_path, b"abc\n" * 100_000)
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        s.find("zzz", forward=False, cancel=token)
    s.close()


def test_a_match_spanning_a_chunk_boundary_is_found(tmp_path):
    import dossier.core.textview as tv
    old = tv._CHUNK
    tv._CHUNK = 64
    try:
        s = src(tmp_path, b"a" * 60 + b"NEEDLE" + b"b" * 200 + b"\nend\n")
        assert s.find("NEEDLE", case_sensitive=True) == (0, 60)
        s.close()
    finally:
        tv._CHUNK = old
