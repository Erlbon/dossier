# Functionality review, 2026-11-05 (build 2026-11-05#01, working tree)

A read-only review of what Dossier does as a dual-pane file manager: where a flow is half done, where a feature has no sibling, where the user hits a dead end, and what could be added. Nothing in the program was changed. The answers go on the decision page (one card per proposal, Yes / No / Later); this file holds the same proposals and reasons.

**How it was checked.** Read `CLAUDE.md`, `docs/spec.md`, both code reviews, `CHANGELOG.md`, `README.md`, the menus (`gui/menus.py`, `gui/context_menu.py`) and the code behind every claim below (file and line given). Each gap was confirmed in the code, not taken from the docs.

**Compared with** Total Commander 11, Directory Opus 13, Double Commander 1.1 and Far Manager 3, from their known feature sets. Their websites were not opened for this review, so a "TC has it" is from knowledge, not a fresh check.

**Left out on purpose** (decided, recorded or in progress): undo stays small; no tags database; the menu restructure of today; the copy-robustness and assistant PRs; the installer and self-update; paste and drag-and-drop without a confirmation (review 2026-11-04, D12); a user guide (same review); and the spec items with no code yet (hex editing V2, CSV and SQLite viewers, profiles, languages, global hotkeys, `.dossier.md` sidecars, EPUB and video tag writing, F9 drag-out of servers, K3/K4/K7-K9).

**Effort:** small = under 2 minutes of work, medium = up to 10, large = more than 10.

**Overall.** The core is strong: plans before every change, a real conflict dialog, a queue that resumes, archives as folders, servers as folders, a command line with placeholders. The gaps are mostly in the everyday orthodox-commander flows that TC, DC and Far users expect without thinking: F5 cannot be pointed anywhere but the other panel, F4 cannot reach a server file or another editor, Unpack takes one archive, tabs have no menu. Most of them are small or medium. Given the earlier usability review's warning that scope grows faster than it is used, the recommendation is to take the small and medium gaps first, and to leave most large new features for later.

**Decisions (the owner, 2026-11-05, on the decision page).**
- **Yes, to build:** 1-23 and 25. Card 20 (Space adds up a folder's size) is Yes against my Later. Card 23 comes after 22, in the same box. Card 25 waits until the copy-robustness and assistant PRs are merged.
- **Later (stay open):** 24, 26, 27, 28, 29, 30, 31, 32. All of them were settled one by one in the walk-through below.
- **No:** none.
- **The Later cards, walked through with the owner (2026-11-05, afternoon):**
  - **24, Quick View: dropped.** "I think the large icon view is as good as this for images"; F3 is enough for text.
  - **26, folder tree: build now, as the popup only** (a key opens a tree, Enter jumps there, it closes), medium. No tree beside the panel.
  - **27, synchronized browsing: dropped.** "This is for a very small subset of tasks."
  - **28, saved searches: Later, placed.** Not on the Home page ("that would be cluttering"). Tools > Saved Searches with Run, Save Current Search and Forget, the same pattern as Mark > Saved Marks and Go > Tabs, plus a drop-down in the Search dialog to load one and change it before it runs.
  - **29, search inside archives: dropped.**
  - **30, save the listing as text or Markdown: dropped.**
  - **31, Everything: dropped**, and so is the alternative of Everything's "Open Path" opening the folder in a running Dossier. The owner uses Everything heavily and searches there; "just drop it".
  - **32, folder share after Folder Sizes: build now, as a percentage column only.** No bars to start with.
- **Added later the same day:** cards 33 and 34 (the assistant acting on its own, and commands on the server). Both Yes, 33 first.

**Suggested build order** (each card with a test that fails on the old code, as the reviews do):
1. **The small ones:** 1, 8, 10, 12, 17, 18, 19, 20, 21.
2. **The medium ones, in pairs that touch the same code:**
   - 2 and 3 (an external program and Open With, both using `core/tools.py`'s placeholders);
   - 6 and 15 (one criteria check for marking and searching; `dossier find` and the MCP search get the skip list too);
   - 4, 5, 7, 9, 11, 13, 14 and 16 on their own.
3. **The large ones:** 22, then 23; then 25 once the PRs are in.

New menu entries follow CLAUDE.md "Menus" and `tests/test_menu_rules.py`. In particular:
- 18 goes in File;
- 21 goes in Edit;
- 19 and the tabs' Reopen Closed Tab (13) go in Go;
- 11 goes in View;
- 16 goes in Help or Go.

---

## 1. Gaps: half-done flows, missing siblings, dead ends

### 1. F4 on a server file says it is "inside an archive" and refuses
- **What:** F4 on any path with a scheme (`sftp://`, `webdav://`, `ftp://`, `zip://`) answers "Items inside an archive are read-only. Copy the file out to edit it." (`gui/main_window.py:458-459`). For a server file the reason is wrong, and it says so even when that server's read-only switch is off.
- **Why:** a wrong reason sends the user looking in the wrong place. The real edit-on-a-server flow is card 25.
- **Fix:** say what the place is: "Files on a server cannot be edited here yet: copy the file to this computer, edit it, and copy it back." Keep the archive text for `zip://`.
- **Effort:** small. **Recommendation:** Yes.

### 2. "Use an external editor" with no way to set one
- **What:** a file over the notepad's size cap gets "Use View (F3) to read it, or an external editor to change it" (`gui/main_window.py:465`). There is no setting for an external editor, and F4 always opens the built-in notepad. TC, DC and Far all let F4 (and F3) run a program of your choice.
- **Why:** a dead end the program itself points at, and programmers will want F4 to open VS Code or Notepad++ for code.
- **Fix:** Settings > Opening Files gets "Editor for F4: Dossier's notepad / this program..." (one program, with `{file}` as in the tools bar, `core/tools.py`), and the too-large message offers "Open in <program>". A per-extension map (spec V9) can come later.
- **Effort:** medium. **Recommendation:** Yes.

### 3. The tools bar's programs are not in the right-click menu
- **What:** the tools bar runs your programs on the marked files (`gui/tools_bar.py`), but the right-click menu (`gui/context_menu.py:110-162`) has no Open With: the only route to another program is More Options (Windows Menu).
- **Why:** the same command should be reachable where you are. DOpus, TC and DC all have an Open With / user menu on right-click.
- **Fix:** an "Open With" submenu in `_item_menu`: the tools bar's programs (folders of tools as submenus), then "Choose Another Program..." (the Windows dialog on Windows).
- **Effort:** medium. **Recommendation:** Yes.

### 4. Unpack and Convert take one archive; Pack takes many
- **What:** Alt+F9 and Convert Archive to Zip stop with "Put the cursor on one archive" when several are marked (`gui/archive_commands.py:127-130`, `:161-163`). Pack to Zip works on all marked items.
- **Why:** unpacking a folder of downloaded zips one by one is exactly the job a commander is for; TC, DC and Far unpack all marked archives, each into its own folder if asked.
- **Fix:** with several archives marked, ask once: "each into a folder of its own name, beside it" (default) or "all into this folder". Skip the extra folder when an archive already holds one top folder of the same name (avoids `x\x\`). One plan for all.
- **Effort:** medium. **Recommendation:** Yes.

### 5. Batch rename cannot use the tags Dossier already reads
- **What:** the pattern dialog's placeholders are file facts only (name, folder, counter, dates; `gui/batch_rename.py:18-25`), and the code says the metadata ones "will add their own placeholders". Dossier reads artist, album, track, title, series, issue (`core/metacolumns.py`) and the photo date (`core/exif.py`).
- **Why:** "rename from tags" (`%track% - %title%`, `%series% %number%`, photo date) is the most asked-for batch rename after counters. TC's multi-rename and DOpus both do it.
- **Fix:** add placeholders fed from the metadata readers, read on a thread with the preview; empty when a file has no such tag.
- **Effort:** medium. **Recommendation:** Yes.

### 6. Mark by Pattern is by name only
- **What:** Ctrl+F marks by wildcard name (`gui/main_window.py:803-832`). The spec asks for date, size and attribute too (S2), and Search already has size and date conditions (`core/search.py:24-40`).
- **Why:** "mark everything over 1 GB" or "everything changed today" in the current folder needs a search today. TC (Mark > Select by...), DOpus and DC have it.
- **Fix:** the mark dialog gets the same optional size, date and attribute fields as Search, using one criteria check (the folder's listing already holds size, dates and attributes, so no disk access).
- **Effort:** medium. **Recommendation:** Yes.

### 7. Compare Two Files only says where the first different byte is
- **What:** `compare_files` (`gui/compare_folders.py:285-307`) reports "identical" or "first difference at byte N". No text diff.
- **Why:** for two config files or two versions of a text, the question is what differs. TC, DC and DOpus show a side-by-side text compare.
- **Fix:** for two text files under a size cap, show a side-by-side diff (Python's `difflib`, built on a thread) in a viewer window; keep the byte answer for binary files.
- **Effort:** medium. **Recommendation:** Yes.

### 8. New File does not open the new file
- **What:** Shift+F4 makes an empty file and selects it (`gui/new_from_content.py:60-93`); you then press F4. TC and Far open the editor on it straight away.
- **Fix:** after the file is made by New File (not by paste), open it in the editor.
- **Effort:** small. **Recommendation:** Yes.

### 9. F7 cannot make nested folders
- **What:** New Folder refuses a name with a separator (`core/ops.py:208-209`). TC, DC and Far make `a\b\c` in one go.
- **Fix:** split the answer on separators, check each part with `check_name`, make the missing ones, one undo entry with a step for each folder made, select the first.
- **Effort:** medium. **Recommendation:** Yes.

### 10. Rename selects the extension too
- **What:** F2 opens a plain input box with the whole name selected (`gui/main_window.py:1048`). Typing replaces `report.pdf` with `x`, losing the extension. Explorer, TC and DC select only the part before the extension.
- **Fix:** a rename box that selects the stem (folders: the whole name). redactor_common's `gui/rename_single_file.py` may already do it; check before writing one.
- **Effort:** small. **Recommendation:** Yes.

### 11. Hidden and system files are always shown
- **What:** the listing has the attributes (`core/vfs.py:38`, the Attributes column) but nothing hides hidden or system files; the spec's design notes asked for "a View switch can hide them" (spec section 17).
- **Why:** every other file manager has the toggle (a toolbar button in TC and DC, Ctrl+H in Far, a button in DOpus). In a user profile the hidden files are mostly noise.
- **Fix:** View > Show Hidden and System Files (on by default, so nothing changes until switched), applied in the model like the quick filter, with dot-names counting as hidden on Linux; the panel's count says how many are hidden.
- **Effort:** medium. **Recommendation:** Yes.

### 12. A panel never says what is in it
- **What:** the panel bar shows free space only (`gui/panel.py:731`, `:1729-1738`); the status line shows marks. Nothing says "38 folders, 412 files, 6.1 GB". The spec's design notes list this (section 17).
- **Fix:** a count beside the free space from what the model already holds (`model.counts()`), "of N shown" while filtered.
- **Effort:** small. **Recommendation:** Yes.

### 13. Tabs have no menu and a closed tab is gone
- **What:** tabs can be moved and closed (`gui/panel.py:1440-1560`) but have no right-click menu, no reopen of a closed tab, and files cannot be dropped on a tab.
- **Why:** TC, DC and DOpus have Duplicate Tab, Close Other Tabs, Copy Tab to the Other Panel, Lock Tab, and reopen closed; closing the wrong tab is the commonest tab mistake.
- **Fix:** a tab menu (Duplicate, Close Others, Close to the Right, Open in the Other Panel, Lock: a locked tab opens a subfolder in a new tab), Go > Tabs > Reopen Closed Tab (a short list kept for the session). Dropping on a tab can be a later step.
- **Effort:** medium. **Recommendation:** Yes.

### 14. The Ctrl+F-key row is empty
- **What:** the function-key table has a Ctrl row with no defaults (`core/fkey_config.py:21-28`), and there is no key for sorting. TC, DC and Far use Ctrl+F3 to Ctrl+F6 for sort by name, extension (Type here), date and size.
- **Fix:** make the four sort orders commands in `gui/fkeys.py` `COMMANDS` and put them on Ctrl+F3..F6 by default (again = reverse); they show in Settings > Function Keys and can be changed.
- **Effort:** medium. **Recommendation:** Yes.

### 15. Search cannot skip folders
- **What:** search walks everything below the root (`core/search.py:174-224`): `.git`, `node_modules`, `__pycache__`, `.venv` included. The CLI's `find` has the same limit.
- **Why:** for programmers (the audience) a name search in a project is drowned by these. TC and DC have "search in subfolders except".
- **Fix:** a "Skip folders" field in the Search dialog (wildcards, remembered, a sensible default list offered), a `--skip` flag for `dossier find`, and the MCP search, one criteria field for all three.
- **Effort:** medium. **Recommendation:** Yes.

## 2. Easy gets (new, small or medium)

### 16. Command palette (Ctrl+K)
- **What:** type a few letters of any command and run it. Spec C2, not built. redactor_common already has one (`gui/command_palette.py`, Ctrl+K, fed from the menu bar); Ctrl+K is free in Dossier.
- **Why:** Dossier has well over a hundred commands in nine menus; the palette finds them without knowing where they live, and lists their keys.
- **Where:** one call in `MenusMixin._build_menus`, an entry in Help (or Go).
- **Effort:** medium. **Recommendation:** Yes.

### 17. Put the name under the cursor into the command line
- **What:** Far and TC put the cursor's name (Ctrl+Enter) or full path into the command line. Dossier has `%f` and `%p` placeholders but no key; Ctrl+Enter is taken (new tab).
- **Where:** `gui/main_window.py` near `_type_to_command`; keys Ctrl+J (name) and Ctrl+Shift+J (full path), quoted when needed. Both free.
- **Effort:** small. **Recommendation:** Yes.

### 18. Show in Explorer
- **What:** open this folder (or the file under the cursor, selected) in the system's file manager. Nothing does this today; the Windows menu is the only bridge.
- **Where:** one function in `core/platform.py` (`explorer /select,` on Windows, `xdg-open` of the folder elsewhere); File menu and the right-click menu.
- **Effort:** small. **Recommendation:** Yes.

### 19. Go to the root of the drive
- **What:** TC and Far jump to the drive's root (Ctrl+\). On a Norwegian keyboard backslash needs AltGr, so Ctrl+Backspace instead (Backspace already goes up one).
- **Where:** Go menu, `gui/panel.py` beside `go_up`.
- **Effort:** small. **Recommendation:** Yes.

### 20. Space on a folder adds up its size
- **What:** in TC, Space marks a folder and shows its size, so the status line's marked total is true. Dossier's Space marks only (`gui/main_window.py:594-599`); the total counts a folder as 0 until Folder Sizes is run.
- **Where:** `_space_pressed` starts `calculate_folder_sizes` for that one folder.
- **Effort:** small. **Recommendation:** Later (useful, but it starts disk work on a key that today never touches the disk; worth trying by hand first).

### 21. Copy Names as Text, Copy This Folder's Path
- **What:** Edit > Copy Paths as Text copies full paths only (`gui/marks_and_notes.py:90-97`). The two siblings TC and DC have: names only, and the panel's own folder.
- **Where:** two entries next to it in the Edit menu.
- **Effort:** small. **Recommendation:** Yes.

## 3. Harder tasks (large, or medium but new ground)

### 22. F5 and F6 to any folder, and copy with a new name
- **What:** F5/F6 always go to the other panel's folder; the confirmation has no destination field (`gui/main_window.py:955-986`, `gui/dialogs.py:101-113`). TC, DC, Far and DOpus all show an editable target: a subfolder, a typed path, or a new name for a single file (Shift+F5 in Far and TC copies in the same folder under a new name).
- **Why:** the most-used command of a commander has no way to say "into `backup\` there" or "as `report-old.pdf`". Today it takes a trip with the other panel.
- **Fix:** the confirmation gets a destination line (the other panel's folder, editable, with completion from `core/completion.py`). A typed folder that does not exist is made; a single file with a new name is copied under that name; the plan is rebuilt for the new target before it runs. Same-folder copy becomes a duplicate.
- **Effort:** large. **Recommendation:** Yes (the biggest gap in the core flow).

### 23. Copy options in the F5 box
- **What:** only files matching a pattern, flatten into one folder (the core already has `flatten`, `core/ops.py:336`), newer only. The spec's F3.
- **Effort:** large. **Recommendation:** Later (after 22, in the same box).

### 24. Quick View in the other panel (Ctrl+Q)
- **What:** TC and Far turn the other panel into a live preview of whatever the cursor is on: text, picture, Markdown, a folder's size and contents. Dossier has all the viewers, but only in their own windows.
- **Effort:** large. **Recommendation:** Later (high value, but new ground; after the gaps above).

### 25. Edit files on servers and in zips with F4
- **What:** download to a private temp copy, open in the editor, and on save write it back (upload, or a zip rewrite), refusing when the remote file changed in the meantime. Only for servers whose read-only switch is off. DC, TC (with plugins) and WinSCP do this.
- **Why:** the audience is tailscalers; editing a config file on a server is a daily job.
- **Effort:** large. **Recommendation:** Yes, after the two open PRs are merged (it builds on the copy code they change).

### 26. A folder tree
- **What:** spec W1: a tree beside a panel, or a tree popup to jump through (Far Alt+F10, TC Ctrl+F8 tree panel). Not built.
- **Effort:** large. **Recommendation:** Later.

### 27. Synchronized browsing
- **What:** both panels step into the same-named subfolder together (DOpus Navigation Lock, TC and DC "synchronous directory change"). Handy when comparing two copies of a tree.
- **Effort:** large. **Recommendation:** Later.

### 28. Saved searches on the Home page
- **What:** spec P6: a search saved by name, shown as a place, run again on Enter. The search is already a result list in a panel.
- **Effort:** medium. **Recommendation:** Later.

### 29. Search inside archives
- **What:** spec P2: names (and text) inside zips found by Search. TC does it.
- **Effort:** large. **Recommendation:** Later.

### 30. Save the listing as text or Markdown
- **What:** spec F8 (print a file list). Names, sizes, dates of the listing or the marks as a Markdown table, to the clipboard or a file. Fits the notes idea.
- **Effort:** medium. **Recommendation:** Later.

### 31. Instant name search through Everything
- **What:** spec P4 (a fast index). On Windows, voidtools Everything answers name searches over all NTFS drives at once; Dossier could use it when it is installed and show the results as a search result list.
- **Effort:** large. **Recommendation:** Later (Windows-only, and the Linux build gets nothing).

### 32. Size bars after Folder Sizes
- **What:** after Folder Sizes, a bar or percentage of the parent per row, to see at a glance what fills a disk (as DOpus and WinDirStat show it).
- **Effort:** medium. **Recommendation:** Later.

## 4. Added after the review: the assistant acting on its own and on servers

The owner, 2026-11-05: "we might want to let the MCP actually do things remotely if it is checked in settings. I needed that functionality today." He chose both parts below (option C), A first, then B.

**The real job (the owner, same day):** "I wanted to copy d:\erlend\maritime from erbo2 to homeserver3", "while on my phone on the train". So:
- the assistant talks to `dossier mcp` on erbo2, where the folder is a local disk;
- the target is an SFTP folder on Homeserver3, listed as an assistant root;
- the owner is on the phone, so nobody can press Run in erbo2's window.

`plan_copy` from the local folder to the SFTP root can already be made. Only the commit is blocked (card 33). Checking the copy afterwards with `write_manifest`/`compare_with_manifest` reads every file on Homeserver3 back over SFTP, and card 34's `sha256sum` on the server removes that. Both cards are tested against this job: a big folder, local to SFTP, with the window closed, and a check at the end.

Where it stands today: since PR Erlbon/dossier#1 (merged today) the assistant can read, search, compare, hash and plan on listed SFTP and SCP folders. But `commit_plan` only sends a plan to the window and waits for Run, and it refuses when the window is not open (`assistant/tools.py:768`). Away from the window, nothing can be changed.

### 33. The assistant may carry out its own plans (a switch, off by default)
- **What:** Settings > Assistant Access gets "Let the assistant carry out its own plans without asking", off by default and only usable while "allow file changes" is on.
  - With it on, `commit_plan` runs the plan in the MCP server itself, through the same core the window uses (`core/ops.py`, the queue journal). So it works with the window closed: from the phone, a cloud session, or another machine.
  - With the window open, the window shows the change running, with Pause and Cancel.
- **Guard rails, all in the core, not in the assistant's text:**
  - only inside the listed folders, which are checked again at commit;
  - read-only servers stay read-only;
  - never an overwrite: a conflict stops that step and is reported, with Skip and Keep Both allowed;
  - never a permanent delete. Deletes go to the recycle bin, so on a network drive, a USB stick or a server (no bin) a delete still needs the Run button;
  - every step is written to the assistant's call log, and the window lists what was done the next time it opens.
- **Rule change:** spec X3 ("`commit_plan` runs it after the user confirms in the GUI") and `docs/assistant.md` say so in words: the owner may switch confirmation off, within these limits.
- **Where:**
  - `assistant/tools.py` `commit_plan`;
  - `assistant/config.py` (one new field, kept off when a settings file has none);
  - `gui/assistant.py` (the switch and the "done while you were away" list);
  - tests that an overwrite, a permanent delete, a path outside the roots and a read-only server are each refused with the switch on.
- **Effort:** large. **Recommendation:** Yes (the owner's choice, C).

### 34. Commands on the server itself (SFTP and SCP)
- **What:** for a listed SFTP or SCP folder, the assistant's checksums, copies and moves within that one server run on the server (`sha256sum`, `cp -a`, `mv` through `core/shellclient.py`) instead of streaming every byte through this PC. Today a manifest of an archive on Homeserver3 downloads all of it.
- **Guard rails:**
  - a separate switch per server ("Allow commands on this server"), off by default;
  - a fixed set of commands built by Dossier with each path quoted, never a command line from the assistant;
  - the same plan, root and read-only checks as card 33;
  - when the switch is off or the command is missing on the server, the work goes over SFTP as now.
- **Where:** `assistant/remote.py`, `core/manifest.py` (remote hashing), `core/ops.py` (a server-side copy and move step), the server settings dialog.
- **Effort:** large. **Recommendation:** Yes (after 33).

## Considered and not proposed
- **Split and join files, shredding, encryption:** rare needs that 7-Zip and the OS cover.
- **Browsing the recycle bin:** goes against the small-undo decision.
- **More top-level windows (W2):** the commander layout is the decided model.
