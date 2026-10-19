import os

from dossier.core.notes import MAX_BYTES, Note, compose_markdown, find_notes, split_front_matter
from dossier.core.vfs import LocalFileSystem

fs = LocalFileSystem()


def test_front_matter_title_is_read_and_stripped():
    fields, body = split_front_matter("---\ntitle: Earthsea\ntags: [a, b]\n---\nHello")
    assert fields["title"] == "Earthsea" and body == "Hello"


def test_no_closing_line_means_no_front_matter():
    text = "---\ntitle: x\nstill text"
    assert split_front_matter(text) == ({}, text)


def test_top_note_then_bottom_note(tmp_path):
    (tmp_path / "about.md").write_text("---\ntitle: About\n---\nTop", encoding="utf-8")
    (tmp_path / "README.md").write_text("Bottom", encoding="utf-8")
    (tmp_path / "other.md").write_text("ignored")
    notes = find_notes(fs, str(tmp_path))
    assert [n.body for n in notes] == ["Top", "Bottom"]
    assert notes[0].title == "About"


def test_only_one_of_each_kind_and_priority_order(tmp_path):
    (tmp_path / "about.md").write_text("A")
    (tmp_path / "series.md").write_text("S")
    (tmp_path / "README.md").write_text("R")
    (tmp_path / "index.md").write_text("I")
    assert [n.body for n in find_notes(fs, str(tmp_path))] == ["A", "R"]


def test_name_match_ignores_case_but_prefers_the_exact_spelling(tmp_path):
    (tmp_path / "Readme.MD").write_text("x")
    assert [n.body for n in find_notes(fs, str(tmp_path))] == ["x"]


def test_no_notes_and_unreadable_folder(tmp_path):
    assert find_notes(fs, str(tmp_path)) == []
    assert find_notes(fs, str(tmp_path / "missing")) == []


def test_big_note_is_cut_and_marked(tmp_path):
    (tmp_path / "README.md").write_text("x" * (MAX_BYTES + 10))
    (note,) = find_notes(fs, str(tmp_path))
    assert note.truncated and len(note.body) == MAX_BYTES


def test_bad_utf8_does_not_fail(tmp_path):
    (tmp_path / "README.md").write_bytes(b"caf\xe9")
    (note,) = find_notes(fs, str(tmp_path))
    assert note.body.startswith("caf")


def test_compose_adds_title_heading_unless_text_has_one():
    a = Note("a", "About", "Top text")
    b = Note("b", "Ignored", "# Own heading\n\nBottom")
    out = compose_markdown([a, b])
    assert out.startswith("## About\n\nTop text")
    assert "# Own heading" in out and "## Ignored" not in out
    assert "---" in out
    assert compose_markdown([]) == ""
    assert "longer" in compose_markdown([Note("c", "", "x", truncated=True)])
