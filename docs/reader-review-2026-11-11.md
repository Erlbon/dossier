# Cheap readers for the F3 viewer, 2026-11-11 (build 2026-11-11#03)

A look for file kinds the F3 viewer could show cheaply, after the Word (Document mode) and Excel (Spreadsheet mode) readers of today. Nothing was changed for this review. Cheap means: the standard library or a Qt module already in the build, no new dependency, works the same on Linux, and reuses a page the viewer already has (the Document page, the Spreadsheet grid). Every reader is for looking only: nothing in it edits.

**How it was checked.** Against `docs/spec.md` (viewer table V1-V9, A5), `CLAUDE.md` (the decisions of 2026-11-05), `core/viewmodes.py` (what F3 shows today: picture, Markdown, text, hex, Document, Spreadsheet) and `core/covers.py` (what already draws thumbnails). The Qt PDF modules were checked in the project's own environment (PyQt6 6.11: `QtPdf` and `QtPdfWidgets` both import).

**A rule to weigh first.** `CLAUDE.md` says "Core before new areas": no new viewers until the functionality review's Yes cards are built and a release has had a week of real use. Today's Word and Excel readers were built at your direct request, which set that aside for them. Every card below is a new viewer too, so a Yes here sets the rule aside again, and a Later keeps it.

**Left out on purpose:** pictures, Markdown, text and media (done or decided, V4, V7, V8); plug-ins (never, A7); editing in any of these viewers.

**Effort:** small = under 2 minutes of work, medium = up to 10, large = more than 10.

**Answers (owner, 2026-11-11):** Yes to 1-7 (CSV/TSV, SQLite, PDF, .odt, .ods, RTF, .pptx); Later for 8-12 (.eml, .msg, .ppt, fonts, notebooks). These Yes answers set "core before new areas" aside for these readers. EPUB was raised again by the owner the same day and became card 13: Yes, text only, with chapters. Cards 1-7 and 13 were built in build 2026-11-11#04, with torrent listings. Second round (forensic listings): Yes to 14 (shortcuts), 15 (document properties), 17 (Recycle Bin records) and 18 (plists); Later for 16 (programs), 19 (database times) and 20 (Thumbs.db).

**Overall.** One card stands out: PDF. Qt's PDF module is already in the build for thumbnails, and its view widget gives real pages, zoom and search for little code. Next come the two that are in the spec already (CSV, SQLite) and the formats people meet on Linux (OpenDocument) or in old archives (RTF). Mail, slides and the rest are cheap but rarer.

---

## 1. In the spec already

### 1. CSV and TSV in the Spreadsheet grid
- **What:** spec V5 asks for a CSV/TSV table viewer. Today a .csv opens as text (`core/viewmodes.py`, `TEXT_EXTENSIONS`). The grid built today (`gui/sheet_view.py`) already has find, cell copy and the limits.
- **Why:** CSV is the most common table on disk, and it is unreadable as text once columns are uneven. TC, DOpus and Excel show it as a table.
- **Fix:** `csv.Sniffer` for the delimiter, the encoding guessed as for text (`core/textview.py`), rows into the grid, with Text as the second mode. The spec's header toggle, sort, filter and row checker come later. The spec also plans a CSV viewer brought over from the Veritas scanner into `redactor_common` (spec, line 239): this card is the small step now, which that one can replace.
- **Effort:** medium. **Recommendation:** Yes (in the spec, and the grid is there).

### 2. SQLite tables in the grid
- **What:** spec V6 and A5: SQLite read-only, tables as folders, schema, SQL console. None is built.
- **Why:** programmers meet .sqlite/.db files all the time (browser data, app caches, Dossier's own kind of users). Seeing the tables without installing a browser for databases is the 80 percent case.
- **Fix:** open with `sqlite3` read-only (`file:...?mode=ro`), one tab per table and view, the first 20,000 rows each, column names as headers. Not the virtual folder (A5) and not the console. A database in WAL mode that another program is writing may refuse a read-only open: say so then.
- **Effort:** medium. **Recommendation:** Yes (in the spec; the folder view and console stay Later).

## 2. New and cheap

### 3. PDF pages
- **What:** F3 on a PDF shows hex today. The thumbnails already render a PDF's first page with Qt's PDF module (`gui/thumbnails.py:72`), so the library is in the build. `QtPdfWidgets.QPdfView` shows the pages; `QPdfSearchModel` finds text.
- **Why:** PDF is the document format everyone has. A quick look without starting a PDF program is the most useful reader on this list.
- **Fix:** a PDF page in the viewer: pages scrolled one after another, zoom (fit width, +, -), page count in the pill, find with next and previous, copy of selected text if Qt allows it. The view widget adds one small Qt library to the build. A locked PDF asks for nothing and says it is locked.
- **Effort:** medium. **Recommendation:** Yes (the biggest gain for the least code).

### 4. OpenDocument text (.odt) in the Document page
- **What:** LibreOffice's text files open as hex today (they are zips).
- **Why:** on Linux this is the common document format, and Dossier is meant for Linux too.
- **Fix:** read `content.xml` from the zip: headings by outline level, paragraphs, bold and italic by their style, lists, tables. The same Markdown output as .docx (`core/officedoc.py`).
- **Effort:** medium. **Recommendation:** Yes.

### 5. OpenDocument spreadsheet (.ods) in the grid
- **What:** LibreOffice's spreadsheets open as hex today.
- **Why:** the same reason as card 4, for tables.
- **Fix:** read `content.xml`: one tab per `table:table`, cell values from `office:value` and `office:date-value` (dates are stored as text already), with the repeat counts LibreOffice writes for empty rows capped by the grid's limits.
- **Effort:** medium. **Recommendation:** Yes.

### 6. RTF text in the Document page
- **What:** an RTF file opens as text, so you read `{\rtf1\ansi\deff0{\fonttbl...` and the words are buried in codes. Many old files named .doc are RTF inside; those open the same way.
- **Why:** RTF was the exchange format for decades (WordPad still writes it), so old folders are full of it.
- **Fix:** a small reader: skip the font table, colour table, styles, info and pictures; `\par` a new paragraph, `\tab` a tab, `\'hh` and `\uN` characters in the file's code page; bold and italic kept. Plain text on the Document page, with Text as the second mode.
- **Effort:** medium. **Recommendation:** Yes.

### 7. PowerPoint text (.pptx), slide by slide
- **What:** a .pptx opens as hex today.
- **Why:** checking what a presentation says without starting PowerPoint, the same need as for Word.
- **Fix:** the slides in the order `presentation.xml` gives, each as a heading ("Slide 3") with its title and text, and the speaker notes under it. The Document page.
- **Effort:** medium. **Recommendation:** Yes.

### 8. Saved e-mail (.eml)
- **What:** an .eml opens as text: headers, then the body, often in base64 or quoted-printable.
- **Why:** Thunderbird and many tools save mail this way; reading one means decoding it.
- **Fix:** Python's `email` package: From, To, Date and Subject on top, the plain-text body (or the HTML body as text), then the attachments by name and size. The Document page.
- **Effort:** medium. **Recommendation:** Later (rare in a file manager).

### 9. Outlook messages (.msg)
- **What:** a .msg is an Office 97 container, the same kind as .doc and .xls, with the subject, sender, body and attachments in their own streams.
- **Why:** mail dragged out of Outlook lands on disk as .msg, and nothing but Outlook opens it.
- **Fix:** the container reader (`officedoc.Compound`) needs to reach streams below the top level; then the same layout as card 8.
- **Effort:** large. **Recommendation:** Later.

### 10. PowerPoint 97 text (.ppt)
- **What:** the old PowerPoint format, an Office 97 container, opens as hex.
- **Fix:** scan the `PowerPoint Document` stream for its text atoms, slide by slide.
- **Effort:** medium. **Recommendation:** Later (old slides are rarer than old Word and Excel files).

### 11. Font preview (.ttf, .otf)
- **What:** a font file opens as hex.
- **Why:** seeing what a font looks like before installing it. Windows has a font viewer; Linux desktops vary.
- **Fix:** Qt loads the font for this window only (`QFontDatabase.addApplicationFont`), which installs nothing. The page shows its name and a sample line at a few sizes.
- **Effort:** medium. **Recommendation:** Later.

### 12. Jupyter notebooks (.ipynb)
- **What:** a notebook is JSON, so it reads as text, with code and outputs in escaped strings.
- **Fix:** Markdown cells as Markdown, code cells as code blocks, text outputs under them; pictures in outputs left out. The Markdown page.
- **Effort:** medium. **Recommendation:** Later.

### 13. EPUB text, chapter by chapter (added by the owner)
- **What:** an epub opens as a folder or in its program; F3 shows hex. Moved here from "Considered and not proposed" at the owner's request.
- **Why:** checking what a book holds without a reader program.
- **Fix:** the chapters in the order the book's package file lists them (`core/covers.py:259` already finds that file), each chapter's XHTML turned into Markdown (headings, paragraphs, emphasis, lists, quotes) by Python's HTML parser, one chapter at a time on the Document page with previous and next chapter in the pill and the chapter list in Settings. Pictures, styling and links inside the book are left out.
- **Effort:** medium. **Recommendation:** Yes (the owner's choice: text only, with chapters).

## 3. Forensic listings (asked for by the owner, 2026-11-11)

The owner: "Dossier is almost a forensic tool". Torrent listings were built at once (build 2026-11-11#04: files, the info-hash from the file's own bytes, trackers, dates). These are the other structured files worth listing the same way, in the grid as Field / Value rows or tables. All read only, standard library only.

### 14. Windows shortcuts (.lnk)
- **What:** a shortcut opens as hex in F3, and Enter runs its target. Nothing in Dossier reads one (`core/startmenu.py` only lists them).
- **Why:** a shortcut is a classic trace: it records the target's path, arguments and working folder, the target's own created, modified and accessed times and size at the moment the link was made, the drive's type, label and serial number, the network share, and the name of the machine it was made on. That shows what was opened, from where, and on which computer, even after the target is gone.
- **Fix:** read the Shell Link format (Microsoft's MS-SHLLINK, fixed structures) with `struct`; an Info tab of Field / Value rows. F3 shows it; Enter still opens the target.
- **Effort:** medium. **Recommendation:** Yes.

### 15. Document properties: who wrote it, when, how long
- **What:** the readers of today show a document's text, not its properties. Only the PDF status line gives its program and dates.
- **Why:** author, last saved by, created, modified and printed dates, revision number, total editing time, company and template are where a document's history sits. Office keeps them in `docProps/core.xml` and `app.xml` (.docx, .xlsx, .pptx), OpenDocument in `meta.xml`, Office 97 in its SummaryInformation streams (which the container reader of today can reach).
- **Fix:** an Info view on the Document, Spreadsheet and PDF pages, on the ⓘ button (I) the picture viewer already has, as Field / Value rows.
- **Effort:** medium. **Recommendation:** Yes.

### 16. Programs (.exe, .dll; ELF on Linux)
- **What:** a program opens as hex in F3.
- **Why:** the compile time stamp, the machine it is built for, the imported libraries and functions, the version resource (company, product, original file name) and whether a signature is attached tell what a program claims to be and when it was made. An original file name that differs from the file's name is a classic tell.
- **Fix:** PE headers, sections, imports, version resource and the signature's presence (not its validity) with `struct`, as tabs; ELF header, needed libraries and sections the same way on Linux.
- **Effort:** large. **Recommendation:** Later (the most code on this list; worth it once the smaller ones are in use).

### 17. Recycle Bin records ($I files)
- **What:** each deleted file in `$Recycle.Bin` has a small `$I` record beside its `$R` copy. Dossier shows the `$I` as hex.
- **Why:** the record holds the file's original path, its size and the time it was deleted.
- **Fix:** the two record versions are a few fixed fields; F3 shows them as Field / Value rows. A later step could list a whole `$Recycle.Bin` folder as one table.
- **Effort:** small. **Recommendation:** Yes.

### 18. Property lists (.plist, XML or binary)
- **What:** Apple's settings and app files. A binary plist opens as hex, an XML one as text.
- **Why:** macOS and iOS keep settings, recent items and app state in them; a backup or a disk image from a Mac is full of them.
- **Fix:** Python's `plistlib` reads both kinds; the grid shows Key path / Type / Value, dates as ISO, data as its length and first bytes.
- **Effort:** medium. **Recommendation:** Yes.

### 19. Readable times in browser and app databases
- **What:** the SQLite grid of today shows times as the raw numbers the databases store.
- **Why:** Chrome counts microseconds since 1601, Firefox microseconds since 1970, Apple seconds since 2001. A visit time is only evidence when it can be read.
- **Fix:** for known databases (Chrome History, Cookies; Firefox places.sqlite), show those columns as dates; elsewhere a "Show numbers as dates" choice per column.
- **Effort:** medium. **Recommendation:** Later.

### 20. Thumbs.db
- **What:** Windows XP to 7 kept a Thumbs.db in each folder of pictures: an Office 97 container with the file names and small JPEG copies.
- **Why:** it shows pictures of files that may be long gone, with their names.
- **Fix:** the container reader of today, its catalog stream for names and times, and the thumbnails as pictures beside the list.
- **Effort:** medium. **Recommendation:** Later.

## 4. Considered and not proposed

- **EPUB text:** moved up to card 13 at the owner's request.
- **Windows Prefetch (.pf):** compressed since Windows 10 with an algorithm Python does not have; only Windows' own API unpacks it, so not on Linux.
- **Event logs (.evtx) and registry hives:** binary XML and a whole database format respectively; a large job each, and a tree browser rather than a listing.
- **Internet shortcuts (.url):** already readable as text.
- **Word 6/95 fast-saved files and Excel 5/95 workbooks:** rare now, and they need their own record formats. They say so and point to Hex.
- **HEIC, AVIF and camera RAW pictures:** they need codecs that are not in the build, so not cheap.
- **Torrent files:** the format is easy to read, but rare in a file manager.
- **vCard, iCalendar, JSON, XML, YAML:** already readable as text.
