# Properties dialog and metadata (feature 13) -- plan

Goal: Alt+Enter on one or more items opens a Properties dialog with tabs. Dossier is meant to be a metadata specialist:
it shows what a file carries inside, and where it is safe to do so, lets the owner change it.

Status: PLAN ONLY. Nothing is built. Waiting for the owner to pick the tab layout and the order of the types.

## Tabs

| Tab | Content | Editable |
|---|---|---|
| General | name, full path, kind, size (and size on disk), folder totals, created / modified / accessed, attributes (read-only, hidden, system, archive), owner, link target | times, read-only/hidden |
| Metadata | the tags of the file's type, grouped (see below) | yes, where the type allows |
| Details | every raw key the provider found (EXIF tag names, ID3 frames, XMP paths), for the curious | no |
| Checksums | MD5/SHA-1/SHA-256 computed on a thread, compare against a pasted value; never writes sidecar files | no |
| Security (Windows) | owner, alternate data streams, "downloaded from the internet" mark | remove mark |

Several items selected: General shows totals; Metadata shows only the fields the items share, an edited field is written to all
(a field left alone is not touched; "(different)" is shown for fields that differ).

## Metadata per file type

- **Images (JPEG, PNG, WebP, TIFF)**: EXIF (camera, lens, exposure, date taken, GPS, orientation), XMP (title, description,
  keywords, rating, creator, copyright), IPTC (JPEG caption, keywords, credit). `redactor_common.core.image_meta` already reads
  EXIF and reads/writes XMP: reuse it. GPS can be removed in one click (privacy).
- **Audio (MP3, FLAC, OGG/Opus, M4A, WAV, WavPack)**: ID3v2 / Vorbis comments / MP4 atoms: title, artist, album, album artist, track,
  disc, year, genre, composer, comment, lyrics, cover art; technical: length, bitrate, sample rate, channels, codec, ReplayGain.
  Reader/writer should come from the Redactor audio code (promote to redactor_common first if it is not there).
- **Video (MKV, MP4, AVI)**: container tags (title, year, comment), tracks (video/audio/subtitle: codec, resolution, frame rate, language,
  default flag), chapters. Read through ffprobe where present; writing MKV tags via mkvpropedit, MP4 via the MP4 atom writer. Optional.
- **PDF**: Info dictionary (title, author, subject, keywords, creator, producer, dates), XMP packet, page count, page size,
  encryption flag. Write Info + XMP.
- **Office (docx, xlsx, pptx, odt, ods)**: docProps/core.xml (title, subject, author, keywords, last modified by, dates) and app.xml
  (application, pages/words). Zip-based: rewrite the one member.
- **EPUB**: OPF metadata (title, creators, publisher, language, identifier, series via calibre meta, subjects, description, date), cover.
  The Redactor epub app already does this: reuse.
- **Comic archives (CBZ)**: ComicInfo.xml (series, number, volume, writer, penciller, publisher, genre, summary, page list).
  cbzredactor's code is the source of truth: reuse.
- **Archives (zip, 7z, rar, tar)**: comment, member count, packed vs unpacked size, method, encryption. Read only.
- **Executables (exe, dll)**: version resource (company, product, file/product version, description), signature status. Read only.
- **Shortcuts (.lnk, .url)**: target, arguments, start-in. Read only at first.
- **Text/Markdown**: encoding guess, line endings, line/word count; front matter keys for Markdown (read; edit later).
- **Folders**: item counts, total size, the folder note, and for Redactor-style folders the series/album info found in notes.

## Architecture

- `core/metadata/` (Qt-free): a `Provider` per family with `matches(path)`, `read(fs, path) -> list[Field]` and
  `write(fs, path, changes) -> None`. `Field(key, label, value, kind, group, editable, choices)` where kind is text, number,
  date, list, rating, bool, or image.
- Reading runs on a thread (window never touches the disk); the dialog fills in when the result arrives.
- Writing is all-or-nothing: write to a temp file beside the original, verify it parses, then replace via
  `redactor_common` `commit_in_place`; one `.dossier-old` safety copy is not kept (the replace is atomic).
- Shared code rule: any reader/writer that Redactor apps also need is promoted to `redactor_common` first, then pinned here.
- Batch edit of metadata (several files) is the same code path, applied per file with one progress box and one result list.
- Editing is never available inside archives or on read-only folders; the fields show greyed with the reason.

## Phases (order set by the owner, 2026-10-20: mp3, cbz, mp4/mkv first)

0. Properties dialog shell: General + Checksums tabs, empty Metadata tab.
1. Audio tags (mp3 first, then FLAC/M4A/Ogg through the same field model). Source today: mp3redactor/core/tag_reader.py (216 lines)
   and tag_writer.py (438 lines), both tied to its `MP3File` class.
2. CBZ ComicInfo. Source today: cbzredactor/core/comicinfo.py (278 lines: `ComicInfoMetadata`, `parse_comicinfo_xml`,
   `serialize_comicinfo_xml`) plus the zip-member rewrite in cbz_file.py.
3. Video containers: mkv_backend.py, mp4_backend.py, video_metadata.py in videoredactor.
4. Then the rest (images, PDF, Office, EPUB, exe, shortcuts).

Each of 1-3 starts with a small step in redactor_common: a Qt-free `core/meta_<kind>.py` with plain `read(path) -> dict` and
`write(path, changes)`, pulled out of the app (the app then imports it, so there is one copy and a test that both use it). Dossier
wraps those into its `Provider` interface. Nothing is copied by hand.

## More suggestions

- Cover art tab for audio, EPUB and CBZ (show, replace, export) next to the tags.
- Read-only "problems" line per file: missing cover, no year, mixed-case tags, files that disagree with the folder note.
- Batch tag edit from the list: select an album, set Album Artist once, written to every file with one progress box and one undo list.
- Tag from filename and filename from tag, using the shared rename dialogs (Redactor already has the parsers).
- Extra list columns from metadata (Artist, Album, Year, Series, Number, Duration, Resolution), switched on per folder, read on a thread and cached.
- Copy metadata from one file to another (cover, tags, ComicInfo) between the two panels.
- Chapters and tracks for video: language and default flag per audio/subtitle track, edited without re-encoding (mkvpropedit / MP4 atoms).
- Subtitles next to a video (.srt/.ass): show which languages exist.
- Embedded vs sidecar view: NFO, poster and subtitle files shown with their video.

## Questions for the owner

- Which types matter most (so phase 2 starts with them)?
- Should the Metadata tab also appear as optional extra columns in the list (for example Artist/Album/Date taken)?
- Write time-stamps (created/modified) from the dialog: wanted?
