"""The PDF page of the F3 viewer: the pages one after another, drawn by Qt's PDF module (the same one the thumbnails use).

Fit to width at first; zoom in and out, every pixel (100 percent), and find with next and previous (Qt's search, which ignores case).
A locked PDF is not asked for its password: it says it is locked. Read only. The document's own facts (title, author, the program
that made it, its dates) are given by ``facts()`` for the status line.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPointF, QTimer, pyqtSignal
from PyQt6.QtPdf import QPdfDocument, QPdfSearchModel
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from . import theme


class PdfPage(QWidget):
    changed = pyqtSignal()                     # the page or the zoom changed: the window updates its place label
    found = pyqtSignal(str)                    # "found", "wrapped" or "none" after a find that had to wait for the search

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.document = QPdfDocument(self)
        self.view = QPdfView(self)
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.search = QPdfSearchModel(self)
        self.search.setDocument(self.document)
        self.view.setSearchModel(self.search)
        self.search.rowsInserted.connect(self._results_came)
        self._result = -1
        self._waiting: Optional[bool] = None   # a find (forward or back) waiting for the first results of a new search
        self._none_timer = QTimer(self)        # parented: a pending timer must not outlive the window
        self._none_timer.setSingleShot(True)
        self._none_timer.timeout.connect(self._no_results)
        self.view.pageNavigator().currentPageChanged.connect(lambda *_: self.changed.emit())
        self.view.zoomFactorChanged.connect(lambda *_: self.changed.emit())
        self.view.zoomModeChanged.connect(lambda *_: self.changed.emit())    # 100% from "fit width" may keep the same factor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        t = theme.current()
        self.view.setStyleSheet(f"QPdfView{{background:{t['card']};border:none;}}")

    def open(self, path: str) -> str:
        """Load ``path``; an empty string when it worked, else why not, in words."""
        self.close_file()
        error = self.document.load(path)
        if error == QPdfDocument.Error.None_:
            return ""
        return {QPdfDocument.Error.IncorrectPassword: "The PDF is locked with a password",
                QPdfDocument.Error.UnsupportedSecurityScheme: "The PDF is locked in a way that cannot be read here",
                QPdfDocument.Error.InvalidFileFormat: "The PDF is damaged",
                QPdfDocument.Error.FileNotFound: "The file is gone"}.get(error, "The PDF cannot be read here")

    def close_file(self) -> None:
        self._none_timer.stop()
        self.search.setSearchString("")
        self._result = -1
        self._waiting = None
        self.document.close()

    def page_count(self) -> int:
        return self.document.pageCount()

    def properties(self) -> list:
        """What the PDF says of itself, for the Info panel: ``[(label, value)]``."""
        field = QPdfDocument.MetaDataField
        rows = []
        for label, key in (("Title", field.Title), ("Subject", field.Subject), ("Author", field.Author),
                           ("Keywords", field.Keywords), ("Made with", field.Creator), ("PDF by", field.Producer)):
            value = str(self.document.metaData(key) or "").strip()
            if value:
                rows.append((label, value))
        for label, key in (("Created", field.CreationDate), ("Modified", field.ModificationDate)):
            value = self.document.metaData(key)
            if value is not None and hasattr(value, "isValid") and value.isValid():
                rows.append((label, value.toString("yyyy-MM-dd HH:mm:ss t")))
        rows.append(("Pages", f"{self.page_count():,}"))
        return rows

    def facts(self) -> str:
        """The short form for the status line: the making program and the dates."""
        props = dict(self.properties())
        parts = [f"Made with: {props['Made with']}"] if "Made with" in props else []
        if "PDF by" in props and props["PDF by"] != props.get("Made with"):     # Word writes the same program twice
            parts.append(f"PDF by: {props['PDF by']}")
        parts += [f"{k.lower()} {props[k][:16]}" for k in ("Created", "Modified") if k in props]
        return ", ".join(parts)

    def place(self) -> str:
        if self.page_count() <= 0:
            return ""
        page = self.view.pageNavigator().currentPage() + 1
        fitted = self.view.zoomMode() == QPdfView.ZoomMode.FitToWidth      # Qt keeps the old factor while it fits the width
        return f"Page {page:,} of {self.page_count():,}   " + ("fit width" if fitted else f"{self.view.zoomFactor() * 100:.0f}%")

    # zoom ------------------------------------------------------------------------------------------------------------------------
    def zoom_by(self, factor: float) -> None:
        current = self.view.zoomFactor()
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.1, min(8.0, current * factor)))

    def fit(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def actual_size(self) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(1.0)

    # find ------------------------------------------------------------------------------------------------------------------------
    def find(self, needle: str, forward: bool = True) -> str:
        """Go to the next (or previous) place ``needle`` is found. ``searching`` when a new search has started (the answer then
        comes through ``found``), ``found``, ``wrapped`` or ``none``."""
        if not needle:
            return "none"
        if self.search.searchString() != needle:
            self._result = -1
            self._waiting = forward
            self.search.setSearchString(needle)
            # Qt's search runs in steps and says nothing when it ends without a hit: give it time by the page count, then say so
            self._none_timer.start(2000 + 20 * max(0, self.page_count()))
            return "searching"
        count = self.search.count()
        if count == 0:
            return "searching" if self._waiting is not None else "none"
        step = 1 if forward else -1
        nxt = self._result + step
        wrapped = nxt < 0 or nxt >= count
        self._go(nxt % count)
        return "wrapped" if wrapped else "found"

    def _no_results(self) -> None:
        if self._waiting is not None and self.search.count() == 0:
            self._waiting = None
            self.found.emit("none")

    def _results_came(self, *_args) -> None:
        if self._waiting is None:
            return
        self._none_timer.stop()
        forward = self._waiting
        self._waiting = None
        here = self.view.pageNavigator().currentPage()
        count = self.search.count()
        first = next((i for i in range(count) if self.search.resultAtIndex(i).page() >= here), 0) if forward else count - 1
        self._go(first)
        self.found.emit("found")

    def _go(self, i: int) -> None:
        self._result = i
        self.view.setCurrentSearchResultIndex(i)
        link = self.search.resultAtIndex(i)
        self.view.pageNavigator().jump(link.page(), link.location() if link.isValid() else QPointF(), self.view.zoomFactor())
