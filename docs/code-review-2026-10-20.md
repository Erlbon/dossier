# Code review and feature ideas, 2026-10-20 (build 2026-10-19#04)

Made by an independent Fable-model reviewer, read-only, with small experiments against the real core. "Reproduced" means it was run and the failure seen (by the reviewer; items marked "also by me" were run again by Claude). "By reading" means the code path was traced, not run.

## A. Findings, by severity

| # | What | Where | Status | Size |
| --- | --- | --- | --- | --- |
| 1 | Undo of an overwrite deletes the new file and does not bring the old one back; the old one is only in the recycle bin | ops.py:739-757, undo_log.py:132-142 | Reproduced, also by me | M |
| 2 | A failed overwrite (source vanished, locked, disk full) has already sent the old target to the bin: neither file is left | ops.py:739-757 | Reproduced, also by me | M |
| 3 | A source that shrinks during the copy is reported done with a short copy; nothing compares bytes written with the size | transfer.py:70-84, fastcopy.py:93 | Reproduced | S |
| 4 | Copy and move go to the other panel's previous folder while it is still loading a slow one (`Panel.path` is the model's path) | panel.py:563-577, main_window.py:956 | By reading, confirmed by me | S |
| 5 | Undo runs on the window's thread: no progress, no cancel, freezes on big or cross-drive undo | main_window.py:1100 | By reading | M |
| 6 | Every navigation lists the folder a second time on the window's thread (note lookup), so a slow share still freezes per folder | panel.py:653, notes.py:73 | By reading | M |
| 7 | Extracting an archive member for F3 or Enter runs on the window's thread with no size cap: big members and zip bombs freeze it and fill the temp folder | zipfs.py:195-204 | By reading | M |
| 8 | The `.dossier-part` suffix breaks file names over 242 characters (legal on NTFS up to 255) | transfer.py:63 | Reproduced | S |
| 9 | Office documents, jars, epubs and cbz files open as folders on Enter (any PK file counts as an archive) | archives.py:317, panel.py:851 | Reproduced, also by me | S |
| 10 | Permanent delete fails on read-only files (Explorer clears the attribute) | ops._remove_tree | Reproduced | S |
| 11 | A source with a trailing separator (a drive root copied in Explorer, pasted with Ctrl+V) merges its contents into the destination, and a move would try to move a drive's contents | ops.plan_copy, file_clipboard.get | Reproduced | S |
| 12 | The recycle bin on network paths (send2trash on UNC) may delete permanently or fail: "the old target goes to the bin first" is unproven there | ops.default_trash | Unverified | S (test) |
| 13 | Closing the window can wait for a big permanent delete (no cancel in `_remove_tree`), and `cmd_runner` is never shut down, so a stuck listing keeps the process alive | main_window.py closeEvent | By reading | S |
| 14 | Status-line and paste checks still stat on the window's thread (up to 200 per marks change, every clipboard path) | main_window.py:830-841, 1007-1013 | By reading | S |
| 15 | Unverified platform branches: Linux exec bit differs between the two copy paths; `wt.exe -d` with `;` in the folder; a custom terminal template inserts the folder unquoted | fastcopy.py, terminals.py:148 | By reading | S-M |
| 16 | Tests: several timing assertions will flake on a busy machine; failure paths without tests (undo after overwrite, failing overwrite, shrinking source, other panel loading); most cross-drive and conflict tests use the memory file system, whose rename and remove are not Windows' | see the list in the reviewer's report | Mixed | M |
| 17 | `main_window.py` is 1400 lines. Split the operation queue first (the only threaded part), then Home actions, terminal, slowness log. Three copies of the same holder/box/finished pattern (`_plan_in_background`, `_run`, `calculate_folder_sizes`), two `human_size`, a duplicated `_stat` | structure | Judgement | M-L |

## B. Feature ideas, ranked by value

1. Fix-pack for the overwrite path (findings 1 to 3). S-M.
2. Quick filter: type to narrow the list. S.
3. Folder history per panel (Alt+Left and Alt+Right, a list). S.
4. Hotlist of bookmarks with a popup and number keys (builds on Ctrl+D pins). S.
5. Batch rename with preview and undo (patterns, counters, regex, case; one plan, the journal already undoes). M.
6. Search by name, then by content, results as a virtual folder so every command and the shared selection work on them. M, L with content and archives.
7. Compare and synchronise folders (mark differences, then one plan). M compare, L sync. Needs 6's result list.
8. Checksums: compute and verify into sidecar files, show on the status line. S-M.
9. Duplicate finder (size, partial hash, full hash, mark all but one). M. Needs 8.
10. Pack and unpack: write into archives, Alt+F5 and Alt+F9, one 7-Zip call per archive instead of one process per member. M.
11. Resume the queue after a restart (opt-in). L.
12. Thumbnails and icons view mode with a background loader and cache. L.
13. Properties dialog (Alt+Enter): attributes, times, alternate streams. S-M.
14. Viewer modes by content: image, hex, Markdown. M.
15. "Same folder in the other panel", open the folder under the cursor in the other panel. S.
16. Named selections with a menu (save, load, to clipboard as a list); the core already has it. S.
17. Edit the folder note from the list (F4 on the note row, templates). S.
18. MCP or scripting front end over the core (list, plan with dry run, execute, selection). M.
19. Remote sources, SFTP, SCP (owner, 2026-10-20) and WebDAV read-only first (Home page H2 and later). L, high risk.
20. A per-file conflict dialog (this one: overwrite, skip, keep both, rename; sizes and dates side by side). M.

## Status, 2026-10-20

Fixed in build 2026-10-20#01: findings 1, 2, 3, 4, 9, 10 and 11 (overwrite order and undo note, short-copy check, the other panel still opening, Office files on Enter with Ctrl+PageDown to look inside, read-only delete, roots and trailing separators), each with a test that fails on the old code. The undo of an overwrite still removes the new file; it now says where the older one is (the recycle bin, as `name.dossier-old`) because the bin cannot be restored from by the program.

Built in build 2026-10-20#02: features 2 (quick filter), 3 (folder history), 4 (hotlist) and 15 (the other panel).

Fixed in build 2026-10-20#03 (all remaining findings):
- 5 undo on the window's thread: undo scaled down to renames, same-drive moves and new folders (instant), by the owner's decision; copies are no longer undone by deleting files.
- 6 the folder was listed twice: the note is read on the listing thread from the same listing.
- 7 archive members unpacked on the window's thread: unpacking runs on a thread with progress, Cancel, a question above 200 MB and a guard against an item that unpacks to much more than the archive says.
- 8 names over 242 characters: the temporary names are short when the name is long.
- 12 recycle bin on network: decided by the owner, there is none; deletes and overwrites on a network drive are permanent and the confirmation says so.
- 13 closing and exit: a big permanent delete stops between items on cancel, and the program leaves after 2 seconds even if a thread is stuck on a dead share.
- 14 the status line and paste no longer read the disk on the window's thread.
- 15 platform: the exec bit survives the hand copy, `;` in a folder name for Windows Terminal, and a custom terminal template quotes the folder.
- 16 tests: timing assertions replaced by events; failure paths covered.
- 17 structure: main_window.py went from 1580 to 1160 lines (five mixins and one background helper), one size formatter, one stat helper.

Still open: features 5 to 14 and 16 to 20 (batch rename, search, compare, checksums, duplicates, pack and unpack, resume, thumbnails, properties, viewer modes, named selections, note editing, MCP, remote sources, the per-file conflict dialog).
