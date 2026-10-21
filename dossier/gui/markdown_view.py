"""The Markdown view of the F3 viewer: the file rendered, in the safe subset of ``core/markdownsafe.py``.

Raw HTML is shown as text, a file over 256 KB is not rendered, and a link opens only if it is http, https, mailto or a path on this
computer. The rendering itself is Qt's own (CommonMark with GitHub tables, task lists and strike-through); nothing here fetches anything
from the network.
"""
from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QTextDocument
from PyQt6.QtWidgets import QTextBrowser

from ..core import markdownsafe as ms
from . import theme


class MarkdownView(QTextBrowser):
    open_file_requested = pyqtSignal(str)             # a link to a file on this computer was clicked
    refused = pyqtSignal(str)                         # a link that is not allowed was clicked

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base_dir = ""
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._clicked)
        self.setReadOnly(True)
        self.restyle()

    def restyle(self) -> None:
        t = theme.current()
        self.document().setDefaultStyleSheet(
            f"a{{color:{t['accent']};}} code,pre{{background:{t['card']};}} "
            f"blockquote{{color:{t['dim']};}} table{{border-color:{t['line']};}}")
        self.setStyleSheet(f"QTextBrowser{{background:{t['bg']};color:{t['fg']};border:none;padding:12px;}}")

    def set_markdown(self, text: str, base_dir: str) -> None:
        """Render ``text``; pictures and links are looked for beside the file (``base_dir``)."""
        self.base_dir = base_dir
        self.setSearchPaths([base_dir] if base_dir else [])
        self.document().setBaseUrl(QUrl.fromLocalFile(base_dir + "/") if base_dir else QUrl())
        self.document().setMarkdown(ms.escape_html(text), QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        self.moveCursor(self.textCursor().MoveOperation.Start)

    def _clicked(self, url: QUrl) -> None:
        text = url.toString()
        if url.isLocalFile():
            text = url.toLocalFile()
        kind, target = ms.classify_link(text, self.base_dir)
        if kind in ("web", "mail"):
            QDesktopServices.openUrl(QUrl(target))
        elif kind == "file":
            self.open_file_requested.emit(target)
        elif kind == "anchor":
            pass                                       # headings carry no names in this rendering
        else:
            self.refused.emit(text)

    def loadResource(self, kind, url):                  # pictures only from this computer: nothing is fetched from the network
        if isinstance(url, QUrl) and url.scheme().lower() in ("http", "https", "ftp"):
            return None
        return super().loadResource(kind, url)
