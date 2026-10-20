# Tags on files (feature 21) -- plan

Decided with the owner, 2026-10-20: **no database.** Tags live on the file itself, in an NTFS alternate data stream (Linux:
extended attributes). The idea is a small piece of WinFS (items with properties you can query), done as a layer on ordinary
files, not as a replacement file system.

Status: PLAN ONLY. Nothing is built.

## Where the data lives

| System | Where | Notes |
|---|---|---|
| Windows (NTFS) | stream `file.ext:dossier` (also on folders) | One small UTF-8 JSON document. Reading and writing never touches the file's main content, so its checksum does not change. |
| Linux, macOS | extended attribute `user.dossier` (same JSON), plus `user.xdg.tags` (comma separated) and `user.xdg.comment` | The two `xdg` attributes are what Dolphin, Baloo and other freedesktop tools read, so tags show there too. |
| FAT, exFAT, most USB sticks, zip archives, read-only media | cannot hold tags | Dossier says so ("this drive cannot store tags") before it tries, and shows the Tags tab read only. |

The JSON: `{"v":1,"tags":["holiday","2019"],"rating":4,"label":"green","note":"free text"}`. Unknown keys are kept when
Dossier writes, so a newer version never loses what an older one saved.

## Copying between Windows and Linux

The record is the same JSON on both; only its container differs (a stream on NTFS, an attribute on Linux). So Dossier's own
copy and move read the tags from the source in whatever form it has and write them to the destination in the form the
destination holds. That is a re-wrap, not a conversion of the content.

- **Linux to Windows (and back) through Dossier on one machine:** works when the other side is reachable as a folder. Over SMB
  from Windows to a Samba share the stream is kept only when the server maps streams to xattrs (`vfs_streams_xattr`, then it
  lands as `user.DosStream.dossier:$DATA` on the Linux side); Dossier does not count on it and checks after the copy whether
  the tags arrived.
- **NFS:** Windows' NFS client has no streams, and xattrs over NFS need NFSv4.2 on both ends, so tags are normally not carried
  over NFS. Dossier says so.
- **SFTP and SCP (later):** neither carries streams or xattrs. Copy there warns "tags are not copied". An opt-in setting could
  put them in a `.dossier-tags` sidecar, but sidecar files are what the owner did not want, so this stays off the plan unless asked.
- **Foreign tags:** when `user.dossier` is missing but `user.xdg.tags` exists (Dolphin and other Linux tools), Dossier shows
  those tags and writes both on the next save. The rating also goes to `user.baloo.rating`. Windows Explorer's own tags live in
  the file's property store, not in a stream, and are not read here.
- Copying a tagged file to a drive that cannot hold tags warns once per copy, never once per file.

## What Dossier does with it

- **Properties > Tags tab:** edit tags (type, autocomplete from tags already seen in this session's lists), rating 0-5, colour
  label, note. Several selected files: add or remove a tag on all of them; a field left alone is not touched.
- **Tags column** (Settings > Columns): filled in the background for the rows on screen, never on the window's thread.
- **Mark > Mark by Tag...**, and `tag:` in the Search dialog; a tag search is a normal search that also reads the stream, so it
  is as slow as a text search and says so in its progress box.
- **Copy and move inside Dossier carry the tags** (a copy gets the source's stream; verify that the OS fast copy keeps it, and
  copy it explicitly where it does not). A copy to a drive that cannot hold tags warns once: "tags are not copied".
- Tags written by Dossier are never sent anywhere. Nothing is created until the first tag is saved.

## Honest limits (to tell the owner in the dialog, not hide)

- Tags are lost when a file is copied by a tool that ignores streams, uploaded to most cloud services, mailed, or zipped.
  Explorer copies keep them between NTFS drives; many NAS boxes keep them only if their share is set up for it.
- There is no index: finding files by tag reads the stream of every file below the folder searched. A background index
  (opt-in, off by default, with a Delete button) can come later if the scan is too slow.
- A stream on a read-only file needs the read-only flag cleared for the moment of the write; Dossier restores it.
- No relations between files at first (the WinFS "link" idea). A tag like `book:blueberry` covers most of it.

## Steps

1. `core/filetags.py`: read, write, remove, "can this path hold tags" (Windows streams via the `:dossier` name, Linux `os.setxattr`),
   with tests on a temp folder and a fake backend for non-NTFS. Qt-free; Dossier only (not for redactor_common unless an app wants it).
2. Properties > Tags tab (single and several files), read and write on a thread.
3. Tags column, Mark by Tag, `tag:` search criterion.
4. Copy and move keep the tags; the warning for drives that cannot hold them.
5. Later, opt-in: write-through to a file's own tag format (XMP keywords, ID3, ComicInfo Tags), once metadata editing exists.
