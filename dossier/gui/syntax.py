"""Syntax highlighting for the notepad: a Scintilla lexer per language, coloured from the scheme (light or dark), not from the lexer's own
white-paper defaults. The colours are picked by what a style is called ("Comment", "Keyword", "String"...), so the same few roles work for
every language the lexers cover."""
from __future__ import annotations

from typing import Optional

from PyQt6 import Qsci
from PyQt6.QtGui import QColor, QFont

from . import theme

LEXERS = {"python": "QsciLexerPython", "javascript": "QsciLexerJavaScript", "json": "QsciLexerJSON", "html": "QsciLexerHTML",
          "xml": "QsciLexerXML", "css": "QsciLexerCSS", "yaml": "QsciLexerYAML", "sql": "QsciLexerSQL", "bash": "QsciLexerBash",
          "batch": "QsciLexerBatch", "cpp": "QsciLexerCPP", "csharp": "QsciLexerCSharp", "java": "QsciLexerJava", "ruby": "QsciLexerRuby",
          "perl": "QsciLexerPerl", "lua": "QsciLexerLua", "markdown": "QsciLexerMarkdown", "properties": "QsciLexerProperties",
          "diff": "QsciLexerDiff", "makefile": "QsciLexerMakefile", "cmake": "QsciLexerCMake", "tex": "QsciLexerTeX"}


def role_of(description: str) -> str:
    """``comment``, ``string``, ``number``, ``keyword`` or ``plain`` for a lexer style's name."""
    d = description.lower()
    if "comment" in d:
        return "comment"
    if any(w in d for w in ("string", "character", "regex", "regular expression", "quote", "heredoc", "here document")):
        return "string"
    if "number" in d:
        return "number"
    if any(w in d for w in ("keyword", "tag", "attribute", "preprocessor", "decorator", "class name", "function or method", "header",
                            "selector", "property", "target", "section")):
        return "keyword"
    return "plain"


def colour_for(role: str, t: dict) -> QColor:
    return QColor({"comment": t["dim"], "string": t["danger"], "number": t["marked"], "keyword": t["accent"]}.get(role, t["fg"]))


def lexer_for(key: str, font: QFont, parent=None) -> Optional[Qsci.QsciLexer]:
    """A lexer for ``key`` in the colours of the current scheme, or None when this Scintilla has none for it."""
    name = LEXERS.get(key)
    cls = getattr(Qsci, name, None) if name else None
    if cls is None:
        return None
    lexer = cls(parent)
    t = theme.current()
    paper = QColor(t["bg"])
    lexer.setDefaultPaper(paper)
    lexer.setDefaultColor(QColor(t["fg"]))
    lexer.setDefaultFont(font)
    for style in range(128):
        description = lexer.description(style)
        if not description:
            continue
        role = role_of(description)
        f = QFont(font)
        f.setBold(role == "keyword")
        f.setItalic(role == "comment")
        lexer.setFont(f, style)
        lexer.setColor(colour_for(role, t), style)
        lexer.setPaper(paper, style)
    return lexer
