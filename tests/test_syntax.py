"""The notepad's syntax highlighting and folding: opt-in, chosen by file name or by hand, coloured from the scheme, folds blocks."""
import pytest

from dossier.core import languages

pytest.importorskip("PyQt6")
pytest.importorskip("PyQt6.Qsci")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dossier.gui import syntax, theme  # noqa: E402
from tests.test_notepad import app, pad  # noqa: E402,F401

CODE = "def a():\n    if x:\n        return 1\n    return 2\n\n\ndef b():\n    return 3\n"


def test_the_language_comes_from_the_file_name():
    assert languages.language_for(r"C:\code\tool.PY") == "python" and languages.language_for("page.html") == "html"
    assert languages.language_for("notes.md") == "markdown" and languages.language_for("Makefile") == "makefile"
    assert languages.language_for("CMakeLists.txt") == "cmake" and languages.language_for("app.config") == "xml"
    assert languages.language_for("plain.txt") is None and languages.language_for("noextension") is None
    assert all(key in syntax.LEXERS for key in languages.LANGUAGES)                      # every language listed has a lexer


def test_style_names_are_sorted_into_the_few_colour_roles():
    assert syntax.role_of("Comment") == "comment" and syntax.role_of("Single-quoted string") == "string"
    assert syntax.role_of("Number") == "number" and syntax.role_of("Keyword") == "keyword" and syntax.role_of("Identifier") == "plain"


def test_highlighting_is_off_until_it_is_asked_for_and_then_follows_the_file_name(pad):
    win, _d, _p = pad(CODE, "tool.py")
    assert not win.act_syntax.isChecked() and win.editor.language is None
    assert not win.act_fold.isEnabled()
    win.act_syntax.setChecked(True)
    assert win.editor.language == "python" and win.act_fold.isEnabled()
    win.act_syntax.setChecked(False)
    assert win.editor.language is None


def test_it_can_start_on_and_the_switch_is_reported_so_it_can_be_remembered(pad):
    win, _d, _p = pad(CODE, "tool.py", syntax=True)
    assert win.editor.language == "python"
    seen = []
    win.syntax_toggled.connect(seen.append)
    win.act_syntax.setChecked(False)
    win.act_syntax.setChecked(True)
    assert seen == [False, True]


def test_an_unknown_kind_of_file_says_so_and_a_language_can_be_picked_by_hand(pad):
    win, _d, _p = pad(CODE, "notes.txt", syntax=True)
    assert win.editor.language is None and "No highlighting" in win.message.text()
    win.lang_actions["python"].trigger()
    assert win.editor.language == "python"
    win.lang_actions["none"].trigger()
    assert win.editor.language is None
    win.lang_actions["auto"].trigger()
    assert win.editor.language is None                                   # auto again: .txt has none


def test_a_text_too_big_is_not_coloured_and_says_so(pad, monkeypatch):
    monkeypatch.setattr("dossier.gui.notepad.HIGHLIGHT_LIMIT", 10)
    win, _d, _p = pad(CODE, "tool.py", syntax=True)
    assert win.editor.language is None and "too big" in win.message.text()


def test_the_colours_come_from_the_scheme_and_the_paper_is_the_schemes(pad):
    win, _d, _p = pad(CODE, "tool.py", syntax=True)
    lexer = win.editor.lexer()
    t = theme.current()
    comment = next(s for s in range(128) if lexer.description(s) == "Comment")
    keyword = next(s for s in range(128) if lexer.description(s) == "Keyword")
    assert lexer.color(comment).name() == t["dim"] and lexer.color(keyword).name() == t["accent"]
    assert lexer.paper(keyword).name() == t["bg"] and lexer.font(keyword).bold() and lexer.font(comment).italic()


def test_blocks_fold_and_unfold(pad):
    win, _d, _p = pad(CODE, "tool.py", syntax=True)
    QApplication.processEvents()
    editor = win.editor
    visible = lambda: sum(1 for line in range(editor.lines()) if editor.SendScintilla(editor.SCI_GETLINEVISIBLE, line))   # noqa: E731
    assert visible() == editor.lines()
    editor.set_all_folds(True)
    assert visible() < editor.lines()
    editor.set_all_folds(False)
    assert visible() == editor.lines()


def test_save_as_to_another_kind_of_file_changes_the_language(pad):
    win, dialogs, p = pad(CODE, "tool.txt", syntax=True)
    assert win.editor.language is None
    dialogs.save_path = str(p.with_name("tool.py"))
    assert win.save_as()
    assert win.editor.language == "python"


def test_the_settings_menu_has_the_switches_and_the_view_menu_the_fold_commands(pad):
    win, _d, _p = pad(CODE, "tool.py")
    settings = [a.text() for a in win.settings_menu.actions()]
    assert "Word Wrap" in settings and "Show Spaces and Tabs" in settings and "Language" in settings and "Encoding" in settings and "Line Break" in settings
    assert any("Syntax Highlighting" in t for t in settings)
    view = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "View")
    texts = [a.text() for a in view.actions()]
    assert "Fold All Blocks" in texts and "Unfold All Blocks" in texts and "Markdown Preview" in texts
    assert "Word Wrap" not in texts                                      # a setting, not a view action
    assert len(win.lang_actions) == 2 + len(languages.LANGUAGES)


def test_encoding_and_line_break_are_chosen_from_the_settings_menu(pad):
    win, _d, _p = pad("a" + chr(10) + "b" + chr(10), "t.txt")
    win.encoding_menu.aboutToShow.emit()
    assert any(a.text() == "utf-8" and a.isChecked() for a in win.encoding_menu.actions())
    win.eol_menu.aboutToShow.emit()
    unix = next(a for a in win.eol_menu.actions() if a.text().startswith("Unix"))
    assert unix.isChecked()
    windows = next(a for a in win.eol_menu.actions() if a.text().startswith("Windows"))
    windows.trigger()
    assert win.doc.eol == chr(13) + chr(10) and win.is_modified()
