# Changelog

Build numbers have the form `YYYY-MM-DD#NN`, as in the Redactor apps. Each check-in that changes real code runs `python bump_version.py` and adds a section here.

## 2026-10-20#10 -- Choose the columns of the folder lists

- **Settings > Columns > Add or Remove Columns...** and a **right-click on any column header** show or hide columns and set their order. Both are the shared dialog and menu of redactor_common, so Dossier and the Redactor apps work the same way. Drag a header to move a column; the other panel follows.
- **Name and Type always show.** The others can be switched on and off: Size, Date, **Created**, **Last opened**, **Attributes** (R read-only, H hidden, S system, A archive, C compressed, E encrypted; on Linux the permissions, rwxr-xr-x) and **Location** (the folder an item is in: useful in search results and the all-files list). By default you see Name, Type, Size and Date.
- The new columns sort like the others. The choice is stored by name (both panels share it), so a column added later never changes what you hid. The Home page keeps its own three columns. Settings > Columns > Back to the Default Columns undoes it.
- Still to come as columns: owner, size on disk, and values from inside files (artist, album, series, resolution), read in the background.

## 2026-10-20#09 -- Properties, with the tags inside audio, comic and video files (read only)

- **Files > Properties (Alt+Return)** for the marked items or the one under the cursor. General tab: name, place, type, size (a folder's size is everything below it), modified, created, last opened, attributes, link target. Several items give totals.
- **A second tab with what is inside the file:** audio (title, artist, album, track, date, genre, comment, lyrics, cover art, length, bitrate, sample rate, channels), CBZ comics (ComicInfo: series, number, title, date, credits, genre, summary, page counts) and video (container, tags, every video, audio and subtitle track with codec, size, frame rate, language and flags, chapters). Copy All puts the text on the clipboard.
- **Read only.** Nothing can be changed from this dialog yet; editing is a later step. The readers are new shared code in redactor_common (pinned at 2026-10-20-02), so the Redactor apps can use the same ones.
- Video details need ffprobe; without it the tab says so.

## 2026-10-20#08 -- The Search dialog

- **Commands > Search... (Alt+F7).** Where to look (the folder you are in; from a search result or a flat list it is the real folder behind it), the name (wildcards, `;` for alternatives, a plain word matches anywhere in the name, `!` in front leaves matches out), match case, files / folders / both, include subfolders, size at least / at most (KB, MB, GB or bytes), changed on or after / on or before, and text inside the files (plain or regular expression, with match case).
- The search runs on a background thread with a box showing how many were looked at and found, and a Cancel. The result opens in a **new tab**; its rows work like any folder (copy, move, delete, open). The next Search dialog starts from your last answers (this session only; nothing is stored).
- A bad entry (a size that is not a number, the smallest larger than the largest, a broken regular expression) is explained in the dialog, which stays open.

## 2026-10-20#07 -- Mount a network share, and the Client for NFS check

- **Mount a Network Share** (Home page entry, and Go menu): pick SMB or NFS, type the address (`\\server\share`, or `server:/export` for NFS), pick a drive letter or the next free one. Windows mounts it and the share appears under Network on the Home page with a light. A password is never typed into Dossier or put on a command line: a share that needs a login works when Windows already has it (Credential Manager); otherwise the mount fails and says why.
- **Client for NFS check:** View > Network Drives shows whether Windows' Client for NFS is switched on (looked up without administrator rights). When it is off, Mount says so and shows how to switch it on (Windows Features, or an administrator PowerShell line). Dossier never changes that system setting itself.
- The mount runs on a background thread with a progress box; the system's own answer is shown afterwards.

## 2026-10-20#06 -- Indicator lights on the Home page

- **Lights on drives and network places.** A small light on the icon: green filled dot (answered), grey hollow dot (not checked yet), red cross (not available or the last attempt failed), amber diamond (a different drive than last time under this letter). The shapes differ as well as the colours; the tooltip says what it means. Nothing is pinged: a drive's light follows its free-space check, a network location's light follows the last time you opened it.
- **Drives are told apart by volume ID, not letter.** A drive that comes back under another letter is recognised ("seen before as E:") and not flagged; another stick under the same letter turns amber.
- **View > Drive Memory:** "Remember Drives Between Sessions" is off by default (until you switch it on, drives are only compared within one session); "Forget Remembered Drives" deletes what was kept.
- Still to come: the Mount button for NFS and SMB, the Client for NFS check, and updating pins when a drive letter changes.

## 2026-10-20#05 -- A choice for every file that already exists

- **The conflict dialog is a table now.** When a copy, move or paste meets files that already exist, every one gets a row: name, what is being copied (size, time, newer or older), what is already there, and its own choice (Overwrite, Skip, Keep both). The row starts as Skip for files that look identical, Overwrite for a newer copy, Keep both otherwise. Buttons set many rows at once: All overwrite, All skip, All keep both, Newer only, Skip identical.
- The table is never taller than ten rows; more rows scroll, so a thousand conflicts do not make a box taller than the screen.
- A folder in the way (or the item itself) cannot be overwritten, so those rows do not offer Overwrite.
- Under the hood: `Plan.resolve_each`, `conflict_rows`, `looks_identical`, and the plan now records the size of what is in the way.
- Plans for metadata (read only first), Nextcloud, SCP, network drives with indicator lights and the NFS check are in docs/.

## 2026-10-20#04 -- Batch rename, search, all files below a folder, saved selections, checksums

- **Batch rename** (Commands > Batch Rename): by pattern (Ctrl+M), search and replace in names, change case, number the files. These are the shared dialogs of redactor_common (pinned in requirements.txt), so the Redactor apps and Dossier rename the same way. A rename is one undo; names that would collide get a number.
- **All Files Below This Folder** (Ctrl+Shift+B) lists every file below the folder in a new tab; the `..` row goes back to the real folder. Copy, move and delete work from the list.
- **Search engine** (name with wildcards and `;` alternatives, size, dates, text or regex inside files); results open in a new tab. The search dialog itself follows.
- **Marks:** Save Selection As..., Restore, Add to Marks and Forget (this session only), and Copy Marked Paths as Text.
- **Edit Folder Note** (Ctrl+Shift+E, or double-click the note): edits the folder's note, or creates a README.md.
- **Checksums:** Commands > Checksums of Marked Files (SHA-256, shown and copied as `hash *name` lines) and Verify Checksum... (paste a value, MD5/SHA-1/SHA-256/SHA-512 told by length). Nothing is ever written next to the files.
- Plans for metadata (Properties dialog), remote sources and the Home page lights are in docs/.

## 2026-10-20#03 -- The rest of the review, and a much smaller undo

- **Undo is small now.** Ctrl+Z puts back a rename, a move on the same drive and a new empty folder, and nothing else. A copy is never undone by deleting the files it made; an overwrite, a delete and a move to another drive have no undo (the older file is in the recycle bin).
- **Network drives have no recycle bin, and the program says so.** Deleting there is permanent, and an overwrite deletes the older file; the delete confirmation names how many items are affected, and the overwrite plan carries a warning.
- **The window's thread no longer touches the disk** for: a folder's note (read with the listing, not listed a second time), the sizes in the status line, unpacking a file from an archive (now on a thread with progress and Cancel, a question above 200 MB, and a guard against zip bombs), and checking pasted files (done while the plan is made).
- **Closing:** a big permanent delete stops between items when you cancel or close, and the program ends within two seconds even if a thread is stuck on a dead share.
- **Names over 242 characters** can be copied and overwritten (the temporary names are short then).
- **Linux and terminals:** a file copied by hand keeps its exec bit; a folder with `;` in its name works with Windows Terminal; a custom terminal template quotes the folder.
- **Inside:** the window is split into five parts (queue, slowness log, going places, folder sizes, unpacking) and one background-job helper; one size formatter and one stat helper; the tests that depended on timing now wait for events.

## 2026-10-20#02 -- Quick filter, folder history, hotlist, the other panel

- **Quick filter (Ctrl+S, View > Quick Filter):** a field under the list narrows it as you type: a part of a name, or a pattern with `*`, `?` and `[ ]`. Enter goes back to the list and keeps the filter; Esc clears it (a second Esc clears the marks). Marks stay on hidden items, but commands work only on what is shown. A refresh keeps the filter, going to another folder drops it.
- **Folder history, per tab (new Go menu):** Back (Alt+Left or the mouse's back button), Forward (Alt+Right or the forward button), and Folder History... (Alt+Down), a list of the last 100 folders with the current one ticked. A new place cuts off what was forward; switching tabs adds nothing.
- **Hotlist (Ctrl+B):** your pinned folders, numbered, so a digit goes there, and Pin This Folder.
- **The other panel:** Ctrl+Right or Ctrl+Left opens the folder under the cursor in the other panel (the current folder when the cursor is on a file); Ctrl+Shift+O makes it show this folder.
- Fixed on the way: folder sizes arriving while a sort was set no longer lose the cursor's place.

## 2026-10-20#01 -- Safer overwrites and other fixes from the code review

- **Overwrite is safe now.** The older file is moved aside only when the new one is complete and goes to the recycle bin only when the new one is in place, so a copy or move that fails leaves the old file exactly where it was (before, it was already in the bin and you had neither). In the bin it is called `name.dossier-old`.
- **Undo of an overwrite** removes the new file as before, and now tells you where the older file is (in the bin, under that name) so you can restore it.
- **A file that got shorter while it was copied** is an error, not a "done" copy.
- **Copy, move, paste and `%o` are refused while the panel they go to is still opening a slow folder** (they used to go to the folder it showed before).
- **Enter opens only archives by name** (`.zip .7z .rar .tar ...`) as folders; Word, Excel, epub, jar and cbz files open with their program. **Ctrl+PageDown (View > Open as Archive)** looks inside any file whose content is an archive.
- **Read-only files can be deleted permanently** (the attribute is cleared, as Explorer does).
- **A drive root or an empty path can no longer be copied, moved or deleted as one item**, and a source written with a trailing slash is copied as the folder it names instead of pouring its contents into the destination.

## 2026-10-19#04 -- Copying many folders no longer freezes the window

- Copy, move and paste first read every folder you chose to make the plan. That ran on the window's own thread, so a big selection froze it (58,000 items took 3.5 s here; a slower disk or a network share took far longer). The plan is now made in the background: the window stays alive, a box with the number of items found and a Cancel appears when it takes a moment, and the confirmation comes when the plan is ready.
- Cancelling stops the planning and changes nothing. Closing the window cancels it too.

## 2026-10-19#03 -- Folder sizes on request

- A sigma button (**Σ**) at the right of the address field, View > Folder Sizes, and Alt+Shift+Enter add up whole folder trees: the marked folders of the panel, or every folder in the list when none is marked. The Size column then shows each folder's size instead of DIR, sorts by it, and the marked total in the status line counts it.
- It runs in the background with a box that shows the folder, how many are done and the total so far, with Cancel. Links are not followed, a folder that cannot be read is counted and skipped, and the status line says how many files and folders were added up.
- The sizes belong to that listing: a refresh shows DIR again, and pressing the button adds them up afresh.

## 2026-10-19#02 -- Click the parts of the address

- The address field shows the path as parts: `C:` > `Temp` > `Export`. A click on a part goes to that folder and stands on the folder you came out of; a middle click opens it in a background tab. A long path folds its left parts into a `...` button with a menu.
- A click on the empty end of the field, a double click, or Ctrl+L (View > Edit the Path) turns it into text to type into; Enter goes there, Esc or leaving the field brings the parts back.
- Works inside archives (the way up leaves the archive) and on the Home page.

## 2026-10-19#01 -- The first build number

Dossier is a dual-pane file manager for Windows (primary) and Linux. This is the first numbered build; what it holds so far:

- **Two panels** with a shared selection, folder tabs, a Home page (drives, places, pins, network), a drive selector, the F-key bar, a command line with terminals, and Markdown folder notes as the last row of a list.
- **Viewer (F3) and editor (F4):** any size, encodings, find, vertical selection; regex find and replace, column editing.
- **Copying and moving:** plans with conflict choices, undo, a parallel copy engine for small files, the operating system's own copy for big ones, retries of locked files, a speed limit, speed and time left in the progress box, an operation queue with pause and resume, an optional verify after copy (a checkbox in the confirmation), a flush to the device for removable and network targets, and folders that move across drives.
- **Marking:** Space, Insert, Shift+arrows, Ctrl+Space, Ctrl+click, Shift+click, drag, Ctrl+F by wildcard pattern. Commands use only the marks of the panel they start from.
- **Archives as folders (read-only):** zip, 7z (py7zr), RAR, CAB, ISO, TAR and more (7-Zip).
- **Clipboard:** Ctrl+C, Ctrl+X and Ctrl+V on files, also with Explorer.
- **Looks:** dark and light schemes, two icon sets, the program icon, gold current tab with blue other tabs.
- **A slowness log** (off by default) that records moments the window stalls.
- **New:** this build number, shown in the status line and in Help > About.
