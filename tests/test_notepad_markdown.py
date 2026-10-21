"""The Markdown preview in the F4 editor: shown beside the source for Markdown files, drawn again as you type, safe, and remembered."""
import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest  # noqa: E402

from dossier.gui.main_window import MainWindow  # noqa: E402
from tests.test_gui_commander import FakeDialogs  # noqa: E402
from tests.test_notepad import app, pad  # noqa: E402,F401


def shown(win) -> str:
    return win.preview.toPlainText()


def drawn(win) -> None:
    QTest.qWait(450)                      # longer than the pause before the preview is drawn again


def test_a_markdown_file_opens_with_the_preview_beside_the_source_and_another_file_does_not(pad):
    win, _d, _p = pad("# Title\n\nSome **bold** text.\n", name="a.md")
    assert win.preview.isVisibleTo(win) and win.act_preview.isChecked() and win.is_markdown()
    assert "Title" in shown(win) and "bold" in shown(win) and "**" not in shown(win)       # rendered, not the source
    plain, _d2, _p2 = pad("# Title\n", name="a.txt")
    assert not plain.preview.isVisibleTo(plain) and not plain.act_preview.isChecked()
    assert pad("x", name="b.markdown")[0].act_preview.isChecked()


def test_the_preview_follows_what_is_typed_not_the_file_on_disk(pad):
    win, _d, p = pad("# One\n", name="live.md")
    win.editor.setText("# Two\n\nand a [link](https://example.com).\n")
    assert "One" in shown(win)                                         # not yet: it waits for a pause in the typing
    drawn(win)
    assert "Two" in shown(win) and "One" not in shown(win)
    assert p.read_text() == "# One\n"                                   # nothing was saved


def test_the_menu_switches_it_on_and_off_for_any_file(pad):
    win, _d, _p = pad("# Hi\n", name="note.txt")
    assert not win.preview.isVisibleTo(win)
    win.act_preview.trigger()
    assert win.preview.isVisibleTo(win) and "Hi" in shown(win)
    win.act_preview.trigger()
    assert not win.preview.isVisibleTo(win)
    win.editor.setText("# Changed\n")
    drawn(win)
    assert "Changed" not in shown(win)                                  # hidden: nothing is drawn while nobody looks


def test_raw_html_in_the_text_is_shown_as_text_and_never_run(pad):
    win, _d, _p = pad("<script>alert(1)</script>\n\n<img src=\"http://example.com/x.png\">\n", name="evil.md")
    text = shown(win)
    assert "<script>alert(1)</script>" in text and "<img" in text      # shown as characters
    assert "<script" not in win.preview.toHtml().replace("&lt;script", "")


def test_a_text_over_256_kb_is_not_rendered(pad):
    win, _d, _p = pad("# small\n", name="big.md")
    win.editor.setText("word " * 60000)
    drawn(win)
    assert "too big to show as Markdown" in shown(win)
    win.editor.setText("# small again\n")
    drawn(win)
    assert "small again" in shown(win)


def test_the_preview_keeps_its_place_when_it_is_drawn_again_and_follows_the_scrolling(pad):
    body = "\n\n".join(f"## Part {i}\n\nText of part {i}." for i in range(300))
    win, _d, _p = pad(body, name="long.md")
    win.resize(900, 500)
    QTest.qWait(100)
    bar = win.preview.verticalScrollBar()
    assert bar.maximum() > 0
    editor_bar = win.editor.verticalScrollBar()
    if editor_bar.maximum() > 0:
        editor_bar.setValue(editor_bar.maximum() // 2)
        QTest.qWait(50)
        assert 0.3 < bar.value() / bar.maximum() < 0.7                  # the middle of the source is the middle of the page
    middle = bar.value()
    win.editor.insertAt("added at the end\n", win.editor.lines() - 1, 0)
    drawn(win)
    assert abs(bar.value() - middle) < bar.maximum() * 0.1              # still about there, not back at the top


def test_a_refused_link_is_said_in_the_status_line(pad):
    win, _d, _p = pad("[x](javascript:alert(1))\n", name="links.md")
    win.preview.refused.emit("javascript:alert(1)")
    assert "not opened" in win.message.text() and "javascript" in win.message.text()


def test_the_choice_is_remembered_for_markdown_files_only(app, tmp_path, monkeypatch):
    left = tmp_path / "left"
    left.mkdir()
    (left / "a.md").write_text("# A\n")
    (left / "b.txt").write_text("b\n")
    win = MainWindow(settings_path=str(tmp_path / "s.ini"), start=(str(left), str(left)), dialogs=FakeDialogs())
    try:
        win.edit_file(str(left / "a.md"))
        md = win.editors[-1]
        assert md.act_preview.isChecked()                                # no choice yet: on for Markdown
        md.act_preview.trigger()                                         # off
        assert win.settings.value("editor/markdown_preview") == "false"
        md.mark_clean()
        md.close()
        win.edit_file(str(left / "a.md"))
        assert not win.editors[-1].act_preview.isChecked()               # remembered
        win.edit_file(str(left / "b.txt"))
        txt = win.editors[-1]
        assert not txt.act_preview.isChecked()                           # never for another kind of file...
        txt.act_preview.trigger()
        assert win.settings.value("editor/markdown_preview") == "false"  # ...and what it does there is not remembered
    finally:
        for w in list(win.editors):
            w.mark_clean()
            w.close()
        win.close()
