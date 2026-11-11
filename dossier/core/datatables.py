"""Tables that are not Office files, for the viewer's Spreadsheet grid: CSV/TSV text and SQLite databases. Read only.

CSV and TSV: the delimiter is sniffed (comma, semicolon, tab or bar; a .tsv falls back to tab), the encoding guessed as for text, and
quoted fields with line breaks are kept whole. SQLite: opened read-only (``mode=ro``), one tab per table and view with the column names
as the first row; nothing is written, not even a journal. A query that runs longer than ``QUERY_SECONDS`` is stopped, so a slow view
cannot hang the viewer. The limits of ``officesheet`` (rows, columns, cells) hold here too.

Only the standard library; Qt-free.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import time
from pathlib import Path

from .officedoc import DocumentError
from .officesheet import Sheet, _Grid, MAX_CELLS, MAX_ROWS, number_text
from .textview import detect_encoding

CSV_EXTENSIONS = (".csv", ".tsv", ".tab")
SQLITE_MAGIC = b"SQLite format 3\x00"
QUERY_SECONDS = 5.0
SNIFF = 64 * 1024


def csv_sheets(path: str) -> list:
    """One sheet: the rows of a CSV or TSV file."""
    try:
        with open(path, "rb") as f:
            raw = f.read(SNIFF)
            encoding = detect_encoding(raw)
            f.seek(0)
            text = io.TextIOWrapper(f, encoding=encoding, errors="replace", newline="")
            sample = raw.decode(encoding, "replace").lstrip("﻿")
            try:
                dialect = csv.Sniffer().sniff(sample[:SNIFF // 2], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel_tab if path.lower().endswith((".tsv", ".tab")) else csv.excel
            grid = _Grid([MAX_CELLS])
            first = True
            for r, row in enumerate(csv.reader(text, dialect)):
                if first and row:
                    row[0] = row[0].lstrip("﻿")
                    first = False
                if r >= MAX_ROWS:
                    grid.cut = True
                    break
                for c, value in enumerate(row):
                    grid.put(r, c, value)
    except (OSError, csv.Error) as e:
        raise DocumentError(f"The file cannot be read as a table: {e}") from e
    return [Sheet(os.path.basename(path), grid.rows(), grid.cut)]


def _value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return f"<{len(v):,} bytes>"
    if isinstance(v, float):
        return number_text(v)
    return str(v)


def _connect(path: str) -> sqlite3.Connection:
    """Read-only. A database in WAL mode whose shared-memory file cannot be made read-only is opened ``immutable`` instead (it then
    shows what is in the main file, without changes still in the journal)."""
    uri = Path(os.path.abspath(path)).as_uri()
    last = None
    for extra in ("?mode=ro", "?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(uri + extra, uri=True, timeout=1.0)
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return con
        except sqlite3.Error as e:
            last = e
    raise DocumentError(f"The database cannot be opened read-only: {last}")


def sqlite_sheets(path: str) -> list:
    con = _connect(path)
    try:
        deadline = [0.0]
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline[0] else 0, 20000)
        try:
            names = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                                "AND name NOT LIKE 'sqlite_%' ORDER BY type = 'view', name").fetchall()
        except sqlite3.DatabaseError as e:
            raise DocumentError(f"The database is damaged or locked: {e}") from e
        budget = [MAX_CELLS]
        sheets = []
        for name, kind in names:
            sheet = Sheet(name + (" (view)" if kind == "view" else ""))
            grid = _Grid(budget)
            deadline[0] = time.monotonic() + QUERY_SECONDS
            try:
                cur = con.execute('SELECT * FROM "{}" LIMIT ?'.format(name.replace('"', '""')), (MAX_ROWS,))
                for c, col in enumerate(cur.description or ()):
                    grid.put(0, c, col[0])
                for r, row in enumerate(cur, start=1):          # row MAX_ROWS (one past the grid) marks the sheet as cut
                    for c, v in enumerate(row):
                        grid.put(r, c, _value(v))
            except sqlite3.OperationalError as e:
                text = "Stopped: it took longer than {:.0f} seconds".format(QUERY_SECONDS) if "interrupt" in str(e) else str(e)
                grid.put(0, 0, text)
            sheet.rows, sheet.cut = grid.rows(), grid.cut
            sheets.append(sheet)
        return sheets
    finally:
        con.close()
