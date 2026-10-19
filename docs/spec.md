# Dossier: feature specification

Status as of 2026-10-19. Written in our own words; see the clean-room rule below. This file is the source of truth for scope; a decision that changes it is made here, with a date.

## 1. Purpose and principles

Dossier is a Windows-first, cross-platform file manager for people who work with many folders at once and care about the text and metadata inside files. It keeps the functional idea of The Next Tool (several freely arranged windows, a selection that survives navigation) and adds Markdown notes, structured-data viewers and metadata editing.

**Clean-room rule.** This spec lists functions, written in our own words. No text, graphics, name or code from the original is reused, and the original binaries are not analysed.

**Legend.** *TNT* = the capability exists in the original's documented feature set. *New* = added for Dossier. *Later* = designed for, not built first.

**Principles**

1. Qt-free core, thin front ends: the GUI and the MCP server call the same functions.
2. Read-only by default for anything that is not a plain local folder (SQLite, remote, archives).
3. Every change is planned, shown, then committed; every commit can be undone or has a backup.
4. Text first: Markdown is rendered wherever a note or a README appears.
5. One stack: Python and PyQt6, shared code lives in `redactor_common`, licence GPL-3.0-or-later.

## 2. Windows and layout

The unusual part of the original is window management, so it comes first. Dossier is a multi-window application: each folder view is its own window inside a main workspace.

| ID | Requirement | Origin |
| --- | --- | --- |
| W1 | Four window types: tree + list, list only, multi-folder (several folders stacked in one window), tree only | TNT |
| W2 | Any number of windows; each remembers its folder, sort, columns and view mode | TNT |
| W3 | Arrangement modes: automatic (minimal overlap), cascade, two side by side, and a user-defined layout saved per window type | TNT |
| W4 | Commander mode: one switch gives two side-by-side list windows with the usual two-pane shortcuts (copy to other pane, swap panes) | TNT |
| W5 | Virtual desktops: named sets of windows, switchable by key, each with its own arrangement | TNT |
| W6 | Window chrome is native and follows the system theme; no fixed colour scheme | New |
| W7 | Optional control strip: drive buttons, favourite folders, command bar; can be hidden, docked or kept on top | TNT |
| W8 | Per-window address bar, breadcrumb, back/forward/up, history dropdown | New |
| W9 | Views: details, list, icons, thumbnails; folder notes pane under the listing (section 8) | New |
| W10 | Session restore: reopen with the same windows, desktops and folders | New |

## 3. Selection

Selection is stored by path in one shared store, not inside a window, so it survives navigation and every window can show it. **Decided 2026-10-19: one selection shared by all windows.**

| ID | Requirement | Origin |
| --- | --- | --- |
| S1 | Click toggles an item; drag marks a range; keyboard equivalents | TNT |
| S2 | Select all, none, invert; select and deselect by pattern (name, date, size, attribute) | TNT |
| S3 | The selection stays when the user changes folder or window; the status bar shows count and total size | TNT |
| S4 | Every file command works on the selection when there is one, otherwise on the focused item | TNT |
| S5 | Selected items from several folders can be acted on together (copy all into one target folder, flatten) | TNT |
| S6 | A selection can be saved by name, recalled, combined, and exported as a list | New |
| S7 | The same selection is readable by the MCP server (section 12) | New |

## 4. File operations

All operations run in the background with progress, cancel and a log. Destructive ones show a plan first (what will be created, overwritten, removed) and can be undone where the file system allows.

| ID | Requirement | Origin |
| --- | --- | --- |
| F1 | Copy, move, delete, rename, new folder, new file, properties | TNT |
| F2 | Rename by pattern (counters, parts of the old name, case change, date) with live preview | TNT |
| F3 | Copy options: keep relative path, flatten everything into one folder, skip if target is newer, skip unreadable files and report them | TNT |
| F4 | Delete to the recycle bin or permanently (setting, plus a confirmation switch) | TNT |
| F5 | Change attributes and timestamps, for one item or the whole selection | TNT |
| F6 | Compare two files or two folders (by name, size, date, optionally content) and select the differences | TNT |
| F7 | Optional short-name (8.3) handling on Windows | TNT |
| F8 | Print a file list | TNT |
| F9 | Create shortcuts / links | TNT |
| F10 | Undo log: moves and renames can be reverted from a history list | New |
| F11 | Conflict dialog: overwrite, skip, keep both, apply to all | New |
| F12 | Long paths and Unicode names everywhere | New |
| F13 | Disk tools: format, disk-image copy. Dropped for now; the OS already has them | TNT (Later) |

## 5. Archives and virtual folders

Anything that holds files can be entered like a folder. One interface (list, read, optional write, stat) serves local disk, archives, SQLite and remote sources, so every window, viewer and command works on all of them.

| ID | Requirement | Origin |
| --- | --- | --- |
| A1 | Enter ZIP, TAR, GZ/TGZ as folders; copy in and out with the normal commands | TNT |
| A2 | RAR, 7z, LHA, ARJ read support through optional plug-ins; absent plug-in means the archive opens as a plain file | TNT |
| A3 | Pack and unpack dialogs; ZIP split and merge; self-extracting archive creation is not planned | TNT |
| A4 | Guards: entry-count and compression-ratio limits against zip bombs, no path escape on extract, names decoded with a fallback code page | New |
| A5 | SQLite database as a virtual folder: tables and views are items, rows open in the table viewer | New |
| A6 | Remote sources (section 10) mount into the same tree | New |
| A7 | Plug-in interface for new virtual file systems, documented and versioned | TNT |

## 6. Viewers and editors

F3 opens a viewer in a window of its own or in a preview pane. The viewer is chosen by content, not only by extension.

| ID | Viewer | Requirement | Origin |
| --- | --- | --- | --- |
| V1 | Text | Any size (memory-mapped), encoding detection, line numbers, search, follow mode for logs; quick edit with save up to a size cap, larger or complex edits open in the user's external editor | TNT |
| V2 | Hex | Hex and text side by side, search by bytes or text, edit in place with explicit save | TNT |
| V1b | Notepad (F4) | The built-in quick editor and the viewer both support vertical (column, rectangular) selection: Alt+drag with the mouse and Alt+Shift+arrows, copy of the block, and in the editor typing and deleting down a column; never Ctrl+Alt, which is AltGr on Norwegian keyboards. Requested by the owner 2026-10-19 as an everyday function many notepads lack | New |
| V3 | Multi-file | Step through the selected files with next/previous in one viewer window | TNT |
| V4 | Markdown | Rendered by default with a source toggle; safe subset: raw HTML shown as text, links limited to http, https, mailto and local paths, 256 KB cap | New |
| V5 | CSV / TSV | Table with sniffed delimiter and encoding, header toggle, column sort and filter, lazy loading for large files, copy as TSV, optional row-checker hook; edit and save keep the original dialect | New |
| V6 | SQLite | Read-only by default: tables as folders, schema view, SQL console. Writing needs an explicit switch and makes a backup first | New |
| V7 | Image | Preview pane only: fit, zoom, rotate, EXIF panel, next/previous in folder; full viewing opens the system's image program | New |
| V8 | Media | Cover, tags and duration shown in the info pane; playback is left to the system player | New |
| V9 | Viewer registry | Viewers and editors are plug-ins keyed by type; the user can map any type to an external program | TNT |

## 7. Search and patterns

| ID | Requirement | Origin |
| --- | --- | --- |
| P1 | One pattern language everywhere: wildcards, optional regex, with date, size and attribute conditions | TNT |
| P2 | Search by file name, by content (text, with encoding choice), and inside archives | TNT |
| P3 | Results open as a virtual folder, so they can be sorted, selected and operated on like any other | TNT |
| P4 | Fast name lookup through a local index, optional and off by default | TNT (locate) |
| P5 | Search inside notes and metadata fields (title, author, tags) | New |
| P6 | Saved searches that appear as favourite folders | New |

## 8. Notes and sidecars

A folder shows its Markdown text under the listing, the way a repository page shows its README. Notes hold text, not navigation.

| ID | Requirement | Origin |
| --- | --- | --- |
| N1 | Top note: `about.md`, `artist.md`, `author.md`, `series.md` or `album.md`. Bottom note: `README.md` or `index.md`. `.nfo` and `.opf` as fallback | New (pluteus format) |
| N2 | Optional front matter between `---` lines (key: value, `[a, b]` lists, `- item` lists); `title` is read | New |
| N3 | One hidden sidecar per folder, `.dossier.md`, holds notes for individual files under a heading per file name, like one `.gitignore` per folder | New |
| N4 | Rename, move and copy keep sidecar entries in step with the files they describe | New |
| N5 | Edit a note in place (split source/preview); notes can be turned off per folder or globally | New |
| N6 | Notes are searchable (P5) and readable through MCP (section 12) | New |
| N7 | Archives and remote folders show their notes read-only | New |

## 9. File metadata

Reading is cheap and always on (columns, info pane). Writing is a planned, previewed, in-place commit.

| ID | Requirement | Origin |
| --- | --- | --- |
| M1 | Read common tags for columns and the info pane: title, author, album, track, duration, dimensions, page count | New |
| M2 | Write for EPUB (OPF), CBZ (ComicInfo.xml), MP3 (ID3) and video containers by reusing the Redactor cores | New |
| M3 | Edit one file in a form, or many at once with find/replace, case conversion, field order and rename-from-metadata | New |
| M4 | Plan, preview diff, commit, with automatic backup or undo entry; failures leave the original untouched | New |
| M5 | Format handlers are plug-ins with a stable contract: `read(path)`, `plan(path, changes)`, `commit(plan)` | New |
| M6 | Cover image view and replace | New |

## 10. Remote sources

Remote sources mount as folders through the common interface (section 5). They start read-only; writing is a per-connection switch.

| ID | Protocol | Scope | Phase |
| --- | --- | --- | --- |
| R1 | WebDAV | Browse, download, upload, rename, delete | 1 |
| R2 | OPDS 1.2 and 2.0 | Browse catalogues, download books | 2 |
| R3 | Subsonic | Browse artists and albums, stream tracks to the system player | 2 |
| R4 | SFTP, FTP | Not in the original list; considered after R1 | 3 |
| R5 | KOReader sync | Not planned | n/a |

Credentials go to the system keyring, never to a config file. Connections are bookmarks in the favourites list.

## 11. Commands, menus, shortcuts and settings

| ID | Requirement | Origin |
| --- | --- | --- |
| C1 | Every command is named and bound to a key; keys are editable, with the common two-pane set as a preset | TNT |
| C2 | Command palette: type to find any command, folder, favourite or recent file | New |
| C3 | User-defined menu entries and commands with placeholders (current file, selection list, folder), run as program, script or viewer | TNT |
| C4 | Command line under the listing: runs in the current folder, with history and placeholders | TNT |
| C5 | File templates for "New" | TNT |
| C6 | Favourite folders, with groups and quick keys | TNT |
| C7 | System-wide hotkeys (bring Dossier forward, open a new window here) | TNT |
| C8 | Profiles: separate settings sets that can be switched or exported; plain files, no registry | TNT |
| C9 | Themes: light, dark, sepia and a high-contrast set, plus following the system; Markdown and viewers use the same tokens | New |
| C10 | Interface languages through translation files; English and Norwegian first | New |
| C11 | Confirmation switches per operation type | TNT |

## 12. MCP server

A local server lets an AI assistant browse and work with the same state the user sees. It uses stdio only, no network listener.

| ID | Requirement |
| --- | --- |
| X1 | Read tools: list folder, stat, read text (size-capped), read metadata, read notes, search, list windows, get selection |
| X2 | Selection tools: set, add, clear the shared selection, so the user and the assistant can hand work to each other |
| X3 | Write tools only through plans: `plan_*` returns a preview, `commit_plan` runs it after the user confirms in the GUI |
| X4 | Read-only by default; each write class (files, metadata, notes) is a separate switch |
| X5 | Every call is logged, and the folder scope is limited to the roots the user lists |
| X6 | Same core functions as the GUI; no behaviour exists only in the server |

**Later (idea from the owner, 2026-10-19): an AI-aware client.** Besides serving an outside assistant over MCP, Dossier could host one: an optional AI provider setting (key in the system keyring) so the client itself can talk to a model and use the same core functions and the same plan-then-confirm rule (X3, X4). Not designed yet; it must stay off by default, never send file contents anywhere without an explicit per-folder opt-in, and work through the existing core so no behaviour exists only in the AI path.

## 13. Platforms

Windows is the primary target; Linux is a tested second. The core never calls an OS-specific function directly: it goes through one platform module, so a port changes that module and nothing else. macOS is not a target but is not blocked.

| ID | Area | Windows | Linux |
| --- | --- | --- | --- |
| O1 | Short (8.3) names (F7) | Supported | Not offered |
| O2 | Attributes and timestamps (F5) | Read-only, archive, hidden; creation time | Permissions and owner; creation time where the file system has it. The dialog shows what the system has |
| O3 | Drive buttons (W7) | Drive letters | Mounts and home folders |
| O4 | Delete to trash (F4) | Recycle bin | Freedesktop trash, through one library |
| O5 | Links (F9) | `.lnk` shortcuts | Symlinks |
| O6 | Long paths (F12) | Extended-length prefix applied automatically | Not needed |
| O7 | System-wide hotkeys (C7) | Supported | Works on X11, blocked on Wayland; optional, off when unavailable |
| O8 | Open with default program | `os.startfile` | `xdg-open` |
| O9 | Hidden sidecar (N3) | Hidden attribute set on `.dossier.md` | Hidden by the dot |
| O10 | Network paths | UNC and mapped drives | Mounted paths |
| O11 | Case sensitivity | Insensitive | Sensitive: `A.md` and `a.md` are different files |
| O12 | File names | UTF-16 | Arbitrary bytes |

Two rules follow from O11 and O12. Sorting, rename-by-pattern, conflict handling and sidecar keys never assume names compare case-insensitively. Names that are not valid text are decoded with the file system's own error handling, shown with a replacement mark, and never crash a listing.

**Build and release, as for the Redactor apps.** Windows: a PyInstaller exe built by a GitHub Actions release job on a version tag. Linux: a self-contained x86-64 tar.gz built in the `redactor-build-tools` Docker toolchain, for Debian 12+ and Ubuntu 22.04+ (glibc 2.35 or newer; the Redactor apps list Fedora and Mint as working too). Tests run on both systems on every push, with Qt in offscreen mode, so case, path and file-name bugs show up before a release. Settings go to the platform's usual folder and secrets to the system keyring (Windows Credential Manager, Linux Secret Service). The `redactor-build-tools` Linux build is noted in the Redactor docs as not yet verified end to end, so the first Dossier Linux release doubles as that test.

## 14. Non-goals and open questions

**Not planned:** the blue Norton-style look, built-in disk formatting, self-extracting archives, an image editor, cloud sync of settings, anything commercial.

**Decided**

- 2026-10-19: one selection shared by all windows (S3, S5).
- 2026-10-19: the name is Dossier. Kept after the review; distributed through GitHub releases, not PyPI. Domain check still to do.
- 2026-10-19: windows are separate top-level windows with native chrome (not MDI). W3 arrangement modes, W4 commander mode and W5 virtual desktops move to Later.
- 2026-10-19: version 0.1 scope is fixed in `docs/review-and-plan.md` section 5.
- 2026-10-19: the folder note (N1) is the last row of the panel's list and scrolls with it, like a README under a repository's file list; it is not a pinned pane. A faux Explorer view mode (single pane with tree) may come later as an extra; the dual-pane commander stays the core.
- 2026-10-19 (correction by the owner): Dossier is a dual-pane orthodox commander. W4 commander mode is the core of 0.1, not Later; D2 in the review is reversed.

**Open questions**

- [ ] Should remote sources stay read-only until phase 2 is stable?
- [ ] Which metadata formats come first: EPUB, CBZ, MP3, video?
- [ ] Contact the original publisher about permission or a source release, or stay fully clean-room?
- [ ] Push access to `redactor_common` so the shared modules (zip handling, natural sort, front matter, CSV viewer) can be promoted there.

## 15. Build order

1. Core: virtual file system interface (local first), shared selection store, operations with plan, progress and undo.
2. GUI shell: windows, arrangement modes, commander mode, lists, tree, status bar.
3. Viewers: text, Markdown, hex, image; folder notes and `.dossier.md` sidecars.
4. CSV viewer promoted from the Veritas scanner into `redactor_common`, then the SQLite viewer.
5. Linux in CI from the first commit: the core's tests on Windows and Ubuntu, then the Debian/Ubuntu tar.gz once a window opens.
6. Archives (ZIP first), search and patterns, user commands and palette.
7. Metadata read, then write for the first chosen format.
8. WebDAV, then OPDS and Subsonic.
9. MCP server over the finished core.

## 16. Health checkers (planned, not in 0.1)

A family of read-only checkers reports problems in files and folders (hygiene, integrity, media, library structure, duplicates, bit rot); fixes are ordinary plans with undo. Scope, contract, catalogue and build waves are in `docs/checkers-plan.md`. Decisions H1-H6 there are open.

## 17. Design notes from the owner's screenshot of the original (2026-10-19)

The owner installed the original program (The Next Tool) on Windows 11 and shared its default look **for design notes only**: the layout of Dossier is not to be rearranged to match it, and nothing of its graphics or text is used (clean-room rule). Functions seen on the screenshot that Dossier does not have yet, as candidates for later, each to be decided separately:

| Seen | Candidate for Dossier |
| --- | --- |
| A separate extension column next to the name | Optional "Ext" column (sortable, resizable like the others) |
| An attributes column (read-only, hidden, system, archive shown as letters) | Optional "Attr" column; hidden and system files are shown, marked with their letters, and a View switch can hide them |
| Two counters at the bottom of every window: folders, files and total size of the listing, and the same for what is marked | A per-panel status line with both (today the window shows only the marked count and size across both panels) |
| Free space shown on the drive button and above the tree | Already in the address bar; the drive menu and strip also show it |
| Tree and list side by side in one window | The spec's tree view (W1, option C of the layout mockups); a later per-panel toggle |
| A row of command icons across the top | Not planned: the F-key bar and menus cover it |
| The window title shows the drive and a number | Dossier titles by machine name instead |
