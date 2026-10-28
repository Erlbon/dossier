# Changelog

Build numbers have the form `YYYY-MM-DD#NN`, as in the Redactor apps. Each check-in that changes real code runs `python bump_version.py` and adds a section here.

## 2026-10-28#04 -- Fix: the frosted glass viewer was all black

- **The frosted look showed a plain black window.** Windows' blur effect lays a tint colour over the blurred desktop, and with no tint it uses black, which hid the picture's see-through layer completely. The viewer now gives it a nearly clear neutral grey, measured on Windows 11 over a white-and-coloured backdrop: the desktop shows through blurred and darkened, as in the mockup. The dim look was right already. A computer where Windows refuses the blur falls back to dim, as before.

## 2026-10-28#03 -- A stand-alone picture viewer with a see-through glass look

- **`dossier view picture.jpg`** opens only the picture viewer, with no file manager behind it: a frameless window over the screen, the desktop showing through, the picture on top. The other pictures of the folder follow (Right, Page Down, Space and the wheel for the next, Left, Page Up and Backspace for the previous, Home and End, Esc to close); several pictures open just those; a folder opens its first picture. Zoom, fit, turn and every-pixel are the same as in F3. A floating bar (previous, next, zoom, fit, turn, close) fades in when the mouse moves and out when it rests.
- **Three looks, with a fallback:** **frosted** (the default: the desktop blurred under a dark layer, with Windows' own blur effect), **dim** (the dark layer, the desktop sharp) and **solid** (no transparency). A look the computer cannot do falls back one step, frosted to dim to solid; a remote desktop session gets solid.
- **Parameters:** `--glass frosted|dim|solid|0-100|frosted:60` (a number is how much of the desktop shows through; 0 is solid) and `--scheme auto|light|dark` for this run. Without them the saved look is used.
- **In the window:** **Files > View as Glass** opens the picture under the cursor (or the marked pictures) in the same viewer, and **Settings > Appearance > Picture Viewer Glass...** sets the look and how much shows through. "Glass view" can be given a function key in Settings > Function Keys.
- The F3 viewer is unchanged. This is a first version to try the look; the same effect for the whole file manager is planned after it.

## 2026-10-28#02 -- Unpack beside the archive; moved files are not left marked

- **Unpack (Alt+F9) now suggests a folder beside the archive**, named like it, in the folder the archive stands in. It used to suggest the other panel's folder. The question can still be edited to any folder. Pack (Alt+F5) still suggests the other panel.
- **After a cut and paste, or a Move (F6, drag and drop), the moved files are no longer marked.** The marks follow a moved file to its new place (that is what keeps a renamed file marked), so after a move all the files stayed marked in the other folder. They are now unmarked once the move is done; a file that failed to move stays marked for a retry. A rename keeps its marks, as before.

## 2026-10-28#01 -- The Help menu is filled out, with About last

- **Help** now reads: Keyboard Shortcuts (F1), Documentation (Online), What's New (Online), the Slowness Log submenu, and About Dossier last, as in other programs. The two online items open the project page and its changelog in the browser. The Slowness Log, a debugging tool, moved below the help items.

## 2026-10-27#01 -- SSH sessions from the terminal button

- **A terminal on a server's folder is now an SSH session.** With an SFTP or SCP server in the panel, the Terminal button, Ctrl+Shift+T and F12 open a terminal window running `ssh` on that server, in the folder shown (`cd` to it, then the server's own shell for your user as a login shell). Before, they said a terminal only opens on this computer. The same is in **Tools > SSH Terminal Here** (any function key can be given to it in Settings > Function Keys) and in the Terminal button's right-click menu as **Open an SSH Session to This Server**.
- **Same safety as a file connection.** The session uses the system's own `ssh` and Dossier's own known-hosts file only, so a server whose host key you have not approved (connect to it in a panel once and check its key) is refused with a reason, and a changed key stops it. A password is typed by you in the terminal window (ssh asks for it itself) and never passes through Dossier; key files and the ssh-agent log in without one. The key file and port of the saved server are used.
- A folder name cannot become a command: it is passed to the server as one quoted word, and a name with a line break is refused. The administrator terminal stays for this computer only; WebDAV, FTP and the other servers have no shell and still say so.

## 2026-10-26#02 -- Address bar: double-click a folder name to edit, right-click to copy the path

- **Double-click on a part of the path** (a folder name in the address bar) now switches the bar to typing, starting from the path up to that part. Before, only a click in the empty end of the bar did that, so a double-click on the path itself did nothing. The first click still goes to that folder; the release after the double-click is not counted as a second click.
- **Right-click on the address bar** has **Copy Path** (the whole path), **Copy Path up to ...** (when the mouse is over a part other than the last) and **Edit Path**. While you are typing, the text field keeps its own menu (Copy, Paste, Select All).

## 2026-10-26#01 -- Choose your function keys: plain, Shift and Ctrl rows

- **Settings > Function Keys...** lets you choose the command of every key in three rows: plain `F1`..`F12`, `Shift+F1`.. and `Ctrl+F1`... Each key has a drop-down of commands (about 40: copy, move, search, health check, dates, links, compare, quarantine, checksums, terminals, pack and unpack and more), or "(none)". "Restore This Tab" and "Restore All" go back to the built-in choices.
- **The bar follows the keys you hold.** Hold Shift or Ctrl and the buttons change to that row; let go and they change back. A row with no keys in it is never shown, so holding Ctrl for Ctrl+C does not blank the bar.
- **The Shift row has defaults:** F1 Health, F2 Dates, F3 Link, F4 New file, F5 Compare files, F6 Compare folders, F7 Quarantine, F8 Erase (delete permanently), F9 Checksums, F10 Duplicates, F11 Sizes, F12 Admin terminal. The Ctrl row is empty.
- **One key, one command.** Every function key is set on the menu action of its command from this one table, so the menu, the bar and the keyboard cannot disagree; the Keyboard Shortcuts list (F1) shows what is set now. The fixed keys (Alt+F5, Alt+Enter, Delete, Ctrl+Shift+T and so on) are not changed. Only your changes are saved, so a later build can improve a built-in choice you never touched.
- New: **Files > New File...** (Shift+F4) makes an empty text file in the folder of the active panel.

## 2026-10-25#01 -- All twelve function keys do something

- **F1 to F12 are all in use.** The bar had F2 to F8. New: **F1 Keys** (a list of every keyboard shortcut, read from the menus so it is never out of date, with a filter box and sortable columns), **F9 Properties**, **F10 Search**, **F11 Full screen** (F11 again puts the window back, maximized or not) and **F12 Terminal**. The old shortcuts (Alt+Enter, Alt+F7, Ctrl+Shift+T) still work. Pack and Unpack stay on Alt+F5 and Alt+F9.
- **The bar shrinks.** The twelve buttons may be narrower than their names; a button that is too narrow shows only `F5` (its tooltip has the full name), so the window can still be made narrow.
- **Ready for more rows.** The keys are a table per layer (`gui/fkeys.py`); a Shift or Ctrl row is one more entry plus `set_fkey_layer(...)`, and the same buttons show it and run its commands. Nothing but the plain row exists yet.
- New painted icons for help, info and full screen, for icon sets that lack them.

## 2026-10-24#17 -- Fix: dialogs freed the right way (build #16 broke reading a dialog after it closed)

- **Build #16 had a bug.** It freed dialogs with Qt's "delete on close" flag, but `exec()` then deletes the dialog the moment it returns, before the caller can read what the user typed. Dialogs such as Connection, Properties, Dates, Link, Quarantine and Copy Settings, and the message boxes, could fail with "wrapped C/C++ object has been deleted" when OK was pressed. Its tests replaced `exec()` with a stand-in and did not see it.
- **The fix.** `OwnedDialog.exec()` now runs the dialog and then calls `deleteLater()`, which waits until control is back in the caller's own event loop, so the answer can be read and a follow-up dialog (a nested loop) does not delete it early. A dialog shown without `exec()` is deleted when closed. The window's message boxes get the same `deleteLater()`.
- **Tests now use the real `exec()`**, closed by a timer from inside it, and read the answer afterwards; the test fails with the old design and passes with the new one. Six dialog kinds opened 10 times leave no widgets behind.

## 2026-10-24#16 -- Dialogs no longer stay in memory after they are closed

- **A leak is fixed.** Every dialog is made with the window as its parent, and Qt keeps a child alive for as long as its parent lives, so each dialog that had been opened stayed in memory, with all its fields, until the program closed: about 12 to 60 widgets each time, and about half a megabyte for Properties. Opening Properties 30 times left 1,830 widgets and 14 MB behind. A window left open for weeks, with dozens of dialogs a day, would have grown by tens of megabytes. (The soak test did not catch it, since it never opened these dialogs; a check of the Redactor apps did.)
- **One shared base, `OwnedDialog`, deletes a dialog as soon as it is closed** (accepted, rejected or closed), once control is back in the event loop, so what the caller reads from it right after it closes is still there. All 27 dialogs use it, and so do the window's own message and question boxes and the output viewer. A test fails when a new dialog class is made straight from QDialog, and another checks that opening six kinds of dialog again and again leaves no widgets behind; both fail without the fix.
- `tools/soak.py` now opens six dialogs every tenth round: over 1,000 rounds the object count stayed flat (63,620 at the end) and memory moved by 1.2 MB.

## 2026-10-24#15 -- The three small buttons sit closer together

- **The sum, flatten and refresh buttons are one tight group** in the panel's bar: no gap between them and less padding at their sides, so each takes about 23 pixels instead of 34 (the three together about 70 pixels instead of 100). The room goes to the address bar, so a long path collapses into "..." later.

## 2026-10-24#14 -- Auto refresh, with its own switch for network drives, and a Refresh button

- **Settings > Auto Refresh** has two switches. **Drives of This Computer** (on by default): a panel shows a file saved, a download that finished or a folder made by another program without you refreshing. **Network Drives (can be slow)** (off by default): watching a share can be slow and unreliable, so it is separate, and a network folder is never watched unless you turn that on. Both are remembered.
- **Gentle by design.** Only the folder each panel shows is watched (two watches at most, nothing for the Home page, archives, search results or servers). A burst of changes (a download growing, a big copy by another program) is waited out, a panel is refreshed at most every 1.5 seconds, and nothing is refreshed while the panel is loading, an operation is running, a name is being edited, the address is being typed or the quick filter is open: the change is looked at again a moment later, never forgotten. It is the ordinary refresh, so the cursor, the marks and the scroll position stay where they were.
- **A Refresh button** (a circular arrow) sits next to the sum and flatten buttons in each panel's bar and reads that panel's folder again (Ctrl+R refreshes both panels; F5 is still copy).

## 2026-10-24#13 -- Built to stay open for weeks: a soak test and two limits

- **A soak test, `tools/soak.py`,** uses the window hard and watches memory, handles, threads and the number of objects: each round changes both panels' folders and does one more thing (a tab opened and closed, select all, a sort, the view mode, a copy that overwrites and a delete, a Health window opened and closed, a command, an undo, a refresh). Over 2,000 rounds (4,000 folder changes) the object count stayed flat (62,326 from start to end) and memory moved by under 2 MB, with no growth in handles or threads. A window can stay open for weeks.
- **The thumbnail memory is limited in bytes now,** to 96 MB, as well as to 800 pictures. By count alone, 800 huge (256 pixel) thumbnails would have taken about 200 MB; the least recently used pictures go first, and one picture over the limit is still kept.
- **The command line keeps the newest 500 commands** in memory (the history list and Up); before, the list had no limit.
- Already limited, and checked: the undo list (20 actions), the folder-size memory (reset at 200,000 entries), the zip index cache, the saved-in-the-window lists (viewers and editors leave their list when closed), and temporary copies for drags (removed on closing and, after a crash, a day later). The only timers that run all the time do nothing when idle (0.0% CPU measured on the running window).

## 2026-10-24#12 -- The Metadata tab of Properties can be edited (mp3 and cbz)

- **Alt+Enter on an mp3, flac, ogg, opus or m4a file, or a cbz, now shows its tags as a form** in the Audio tags (or ComicInfo) tab, with **Save Metadata** for that tab and Save Tags for the Tags tab. A field that was changed is shown in bold; the little x takes a field away. Under the form, the rest of what the file carries (length, bitrate, cover art, lyrics) is listed read only as "Also in the file", so nothing is hidden and nothing is touched.
- **Several files of one kind at once:** a field they all share shows its value; one that differs shows "(different)" and is left alone unless you type something in it (then every file gets it). The line under the form says "2 fields changed on 3 files", and files that cannot be changed (read-only, damaged) are counted and left out.
- **Saving asks once** (which fields, how many files, who is left out and why), then writes on a thread with progress and Cancel. Each file is made beside the old one, read back and checked, then put in place; the old file goes to the recycle bin; a failure leaves it as it was. The panels refresh afterwards.
- For large batches (numbering by pattern, whole libraries) the Redactor apps remain the tool; this is for one file or a few. A separate window with a preview table is kept for importing metadata from elsewhere.

## 2026-10-24#11 -- Writing metadata, first step: mp3 tags and cbz ComicInfo (engine and command line)

- **`dossier tag`** shows or changes the tags inside files. It writes mp3, flac, ogg, opus and m4a tags (title, artist, album, album artist, track, disc, year or date, genre, composer) and the ComicInfo of a cbz (series, number, count, volume, title, summary, year, month, day, the credits, publisher, genre, tags, language, age rating, manga, web). `--set FIELD=VALUE`, `--clear FIELD`, `--dry-run` for old and new values, `--fields` to list the fields. Several files of one kind at once.
- **Only what you name is touched.** Cover art, lyrics, custom frames and ComicInfo elements Dossier does not know stay exactly as they are; a value that is already there is not written; an empty value takes the field away. A new ComicInfo element goes where the schema puts it, a comic without ComicInfo.xml gets one, and one inside a folder is changed in place.
- **A file is never changed in place.** The new version is made beside it (an mp3 as a copy with the new tags, a cbz as a rewritten zip), read back and checked against what was asked for, and only then put in the old one's place; the old file goes to the recycle bin (deleted at once on a drive that has none). A failure, a locked file or a cancel leaves the original as it was, with no leftover files. Values are checked first (a month is 1 to 12, a year a whole number), and a read-only, damaged or other kind of file is named with the reason while the rest goes on. The rating and label Dossier keeps on a file follow it.
- The window for it (Tools > Edit Tags...) comes next. No new libraries: `mutagen` was already in for reading, the cbz uses the standard library and the zip rewrite that was already there.

## 2026-10-24#10 -- The Health window

- **Tools > Check Folder Health...** opens a window that runs the file health checks (`dossier check`) on the active panel's folder and everything below it. Findings are **grouped by rule on the left**, worst first, each with its count and a coloured dot (red error, amber warning, grey note); **All findings** is on top for the flat view. The files of the chosen group are on the right with severity, item, folder, what is wrong and the fix on offer. Every header resizes and sorts (severity sorts by how bad it is, not alphabetically).
- **The check runs on a thread** with progress ("12,000 files looked at, 31 findings so far") and a **Stop** button; a stopped check keeps what it found. **Deep** also reads whole zip-based files. Closing the window stops the check. A folder that cannot be read is said, not hidden.
- **Fixes are plans, previewed first.** **Preview fix...** lists the steps of the plan (renames, deletes to the recycle bin, moves to the quarantine folder) and changes nothing; **Fix selected (n)** or **Fix all n** (when no row is selected the whole group) runs them through the ordinary queue: a name that is taken is asked about and never replaced, a delete goes to the recycle bin, renames and same-drive moves can be undone with Ctrl+Z. Fixes of different kinds are separate plans, one after the other. What was fixed leaves the list.
- **Mark in the panel** puts the checked files into the shared selection (and shows their folder when it is just one), so every command works on them. **Ignore this rule here** hides a rule below the checked folder until the next check; **Show ignored** brings it back (nothing about it is written to disk). **Copy list** puts the group on the clipboard as tab-separated lines.
- Underneath: findings are grouped and ignored by `core/health.py` (`group_by_rule`, `IgnoreList`), a run can end early and keep its findings (`partial_on_cancel`), and the one-line description of a planned step is now shared by the command line and the preview (`ops.describe_op`).

## 2026-10-24#09 -- A quarantine folder, with settings

- **Settings > Quarantine...** chooses where quarantined files go. The default is **on each drive, in `<drive>:\Temp\Quarantine`** (for example `D:\Temp\Quarantine`): moving a file there stays on its drive, so it is instant and can be undone with Ctrl+Z. Or choose **one folder for everything**; each drive then gets a folder of its own inside it (`C`, `D`...). The dialog shows where the file under the cursor would go. "Back to the default" is there too.
- **Tools > Move to Quarantine...** (also in the right-click menu) moves the marked items there after one confirmation that names the folder. A file **keeps its place in the folder tree** (`D:\Photos\2019\a.jpg` becomes `D:\Temp\Quarantine\Photos\2019\a.jpg`). **Tools > Put Back from Quarantine** moves it back to where it came from, making its folders again if they are gone. A name that is already taken, in the quarantine or where a file belongs, is asked about with the usual conflict dialog and never replaced. Nothing is ever deleted, and the quarantine is never emptied for you. **Go > Quarantine Folder** opens it.
- **Planning changes nothing:** the folders the quarantine needs are made when the plan runs, so a dry run, a cancel or a declined confirmation leaves the disk alone (a move plan can now begin with steps that make its destination).
- **File health fixes use it:** empty files and damaged zips (`bad-zip`, `bad-crc`) now offer "Move to the quarantine folder". `dossier check --fix --quarantine` applies it (`--quarantine-folder FOLDER` for one folder instead of the drive default); it cannot be combined with `--delete-junk` in one run.

## 2026-10-24#08 -- A Nextcloud preset under Remote sources

- **"Nextcloud or ownCloud" is a new type in the Add a Server dialog.** Give the server (`cloud.example.com`) and your user name, or paste the address of its web page (`https://cloud.example.com/nextcloud/index.php/apps/files/` is cut down to the server and the folder it lives in); the address of your files, `.../remote.php/dav/files/<user>`, is worked out for you, so the Start in box is not shown. A user name with a space or a slash is encoded safely. It is still a WebDAV connection underneath (same client, certificate question, read-only by default), saved with `preset = nextcloud`, listed on the Home page as "Nextcloud".
- **The login asks for an app password,** not your main password, and says how to make one (Settings > Security > Devices and sessions in Nextcloud). An app password works with two-factor accounts and can be revoked there. It is kept in the system's password store only if you ask, like any other password.
- Not built yet (docs/home-and-servers-review.md section 10): Nextcloud's trash as a recycle bin, chunked upload, share links, versions.

## 2026-10-24#07 -- One outline around the current tab and its box

- **The current tab now has a 1 px outline like the blue tabs, and it runs on around the whole box below it.** One line goes up the side of the tab, over its rounded top, down the other side, along the box's top edge beside the tab (where the other tabs rest on it), and down and around the sides and bottom of the box. The tab and the box read as a single shape. In the active panel the line is a darker gold, on the panel's very edge, with the gold frame inside it; in the other panel it is a lighter dim gold, where that panel's box starts.
- Colours are new theme entries (`frame_line`, `inactive_frame_line`), worked out from the accent for dark and light schemes. The line lies over the panel and lets every click through. Only the outline is new: the fills, the blue tabs and the bars are as before, and the first tab still lines up with the box.
- Tests check the outline's path (box edges, where the tab is), its two colours, that it follows the current tab, and the pixels on the panel edge.

## 2026-10-24#06 -- The first tab lines up with the box below it

- **The step under the first tab is gone.** In the panel that is not active, the first tab stuck out about 2 pixels (a frame's width) to the left of the address bar and list below it, because only the active panel has a gold frame to fill that margin. The first tab of a panel that is not active now starts where the box below starts; in the active panel it still runs on into the gold frame as before. Only the first tab moves, and only by that width, when the active panel changes. Tests check the two edges in both states for both panels.

## 2026-10-24#05 -- Pictures, text and web links become files; drag items out of archives and servers

- **Ctrl+V with no files on the clipboard makes a file of what is there:** a picture becomes a PNG, text becomes a UTF-8 `.txt`. You are asked for the name first (suggested from the time, for example `Pasted image 2026-10-24 10.30.12.png`); the extension the kind needs is added if you leave it out, and typing `.jpg`, `.bmp`, `.tif` or `.webp` saves the picture in that format. **Edit > Paste Picture or Text as New File...** (Ctrl+Shift+V) does the same on purpose. A name that is taken becomes `name (2).ext`: nothing is ever overwritten, and the file is made exclusively on a thread.
- **Dropping a picture or text on a panel does the same,** in the panel's folder, or inside the folder row it was dropped on (the row lights up). A **web link dragged from a browser** becomes an Internet Shortcut (`.url`) named after the site. Files dropped from Explorer, and what Dossier itself drags, are handled as files, as before. A read-only place (an open archive, a catalogue, the Home page) says why nothing was made.
- **Dragging items that are inside an archive or on a server to another program now works.** The other program is offered file URLs, and the items are copied to a temporary folder only when it asks, at the drop; a drag that ends inside Dossier copies nothing. The limit is 64 MB (files that are listed are counted up front, and a folder that turns out bigger stops the copy); a bigger drag says so in the status line and still works between the panels. The temporary copies are removed when the window closes, and old ones a crash left (more than a day) when the program starts.
- Drag-in from other programs (files from Explorer or a file manager) was already there; it is now joined by pictures, text and links.

## 2026-10-24#04 -- Saved tab sets

- **View > Tabs > Save Tab Set As...** keeps the folders of the active panel's tabs, and which tab was in front, under a name. **Open Tab Set** replaces the panel's tabs with them (as the saved session does when the program starts); **Add Tab Set** opens its folders as more tabs after the ones there; **Forget Tab Set** removes one. A set is not tied to a panel: open it in either. The lists of names are filled each time the menu opens, like the saved selections of the Mark menu.
- Only sets you save by name are kept (in the settings, with the folder layouts); a folder that is gone when a set is opened falls back to the nearest folder above it. A search result tab is saved as the folder the search started in.
- Tests now pin that the sort order follows the same scope as the folder layout: a rule for a folder and its subfolders gives the subfolders its sort, a sort change there changes the rule, and nothing outside it is written.

## 2026-10-24#03 -- The command line completes names and lists its history

- **Ctrl+Space completes the word at the cursor.** In the first word it offers the programs of `PATH` (read once on a thread and kept for five minutes), the files of the folder and what you typed before; elsewhere it offers the files and folders of the panel's folder, or of the folder you typed (`sub\in`, `C:\Users\`, `~/`). One match is put in; several put in what they have in common and drop a list under the line (Up and Down, Enter or Tab or a click chooses, typing closes it and goes on). A name with a space gets quotes, a folder ends in the separator and keeps the quote open so the next press goes one level in. Hidden names show only when you start with a dot. It never runs or changes anything, and it works on a thread so a slow share cannot freeze the window.
- **Ctrl+Down (or Tools > Command Line History...) lists what was typed this session**, newest first, each command once; with something already typed only the commands that contain it. The history is still kept in memory only.
- Ctrl+Space and Ctrl+Down are used because Tab stays "back to the panel" and no shortcut uses Ctrl+Alt.

## 2026-10-24#02 -- Change Dates and Attributes, and New Link, in the window

- **Tools > Change Dates and Attributes...** (also in the right-click menu) works on everything marked, or the item under the cursor. Choose which dates (modified, last opened, created on Windows) and how: set a moment, shift by a difference (`+2h`, `-1d`), copy one date of the item into another (created from modified), take the date of a file, or take a photo's date taken. Attributes are three-state boxes: leave as it is, switch on, switch off (hidden, system and archive on Windows). Folders can be included with what is inside them, and their own dates can be left alone.
- **The table shows old and new for every item before anything is written.** It is made on a thread a moment after you stop typing, lists items that cannot be changed with the reason (a photo without a date taken, a file in an archive), and every header resizes and sorts. Nothing is written until **Apply**; then the change runs on a thread with progress and Cancel, and says how many items changed and which failed.
- **Tools > New Link...** (also in the right-click menu) makes a symbolic link, a junction (folders, Windows) or a hard link (files, same drive) to the item under the cursor, by default in the other panel's folder. Options that cannot work for the item are greyed out with the reason in their tooltip; a hard link keeps the extension in the suggested name; a symbolic link can store a relative path. If the link is refused (the name is taken, no right to make symlinks) the dialog opens again with the reason and what you typed.
- Date and time parsing is shared by the window and `dossier touch`, and one function plans dates and attributes together for both.

## 2026-10-24#01 -- Links and dates: the engine and the command line

- **`dossier link target link [--kind symlink|junction|hardlink]`** makes a symbolic link, a junction (Windows, folders) or a hard link (same drive, files). Nothing is ever replaced, and each refusal says why (a hard link cannot be made for a folder, a junction only shows a folder, Windows needs Developer Mode for a symlink and says so). `--relative` makes a symlink that survives moving both ends.
- **`dossier info` shows what a link is:** where a symlink or junction points, whether it is broken, and for a hard-linked file how many names it has (on Windows also the other names).
- **`dossier touch`** changes dates and attributes of many items at once: set a moment, shift by a difference (`+2h`, `-1d`), take the date of another file, take the date a photo was taken, or copy one date of the item into another (creation date into modified date). Modified, accessed and created (Windows) dates; read-only, hidden, system and archive attributes (Windows; read-only elsewhere). It goes into folders with `-r`, works on read-only files, and `--dry-run` lists old and new values first.
- Built as Qt-free cores (`core/links.py`, `core/filetimes.py`) with a plan-then-apply split and a restore plan; the window for them comes next.

## 2026-10-23#02 -- Resume after a restart: the gaps closed

- **Every job that moves or deletes files is remembered, not only Copy, Move, Paste, drag and drop and Delete.** Unpack, Synchronize, Convert, copy with Flatten and what the assistant asks for are kept as their steps while they wait or run (still only when Settings > Copy and Move > remember is on). Plans that only rename or make folders are not kept.
- **Your conflict choices survive.** A kept plan has the overwrite, skip and keep-both choices already in it, so after a restart nobody is asked again; only the steps that are not done run (a step whose source is gone, or whose copy is already there with the same size and time, is dropped).
- **A job that ended with failed steps stays on the list** (for example a full disk or a locked file) and says so ("3 failed last time"); the next start offers it again, and only what failed is left to do. A job you cancelled or stopped yourself still goes off the list.
- **Not now is not forgotten:** the status line says how many unfinished operations are remembered, and **Tools > Operations > Unfinished Operations...** asks about them again at any time (it also says when nothing is remembered, or when remembering is off).
- Long plans are written to the list on a thread, in order, so the window never waits for the disk; the list is one object per window now (before, each use made a new one).

## 2026-10-23#01 -- File health checks (first wave): `dossier check`

- **`dossier check folder...`** looks through a folder tree for files that are not healthy and reports each with a severity (error, warning, note) and the evidence. It finds empty files, junk (`Thumbs.db`, `~$` files, half-downloaded files), names that break on Windows (trailing space or dot, reserved or illegal characters, accents stored in the wrong form, text read in the wrong encoding, paths over 259 characters), names that differ only in case, dead links, dates in the future or before 1980, a file whose extension and content disagree (a `.cbz` that is really a rar), subtitle files without a video, and empty folders (the folder you check is never called empty).
- **`--deep`** also reads every zip, cbz, epub and Office file completely: a damaged entry, an archive that cannot be read, a name stored twice, and entries that would unpack outside their folder.
- **Reports only.** Nothing is changed unless `--fix` is given: it applies the renames (a plan, so the same conflict rules apply); `--fix --delete-junk` instead moves junk and empty folders to the recycle bin. `--dry-run` shows the steps. `--list` names the checkers, `--only` runs some of them. Exit code 1 when there are errors or warnings.
- Built as a Qt-free core (`core/health.py` the framework, `core/health_rules.py` the rules) so the window, the command line and the assistant can use the same checks later. No window for it yet.

## 2026-10-21#22 -- A Markdown preview in the editor

- **The F4 editor can show the text as Markdown beside the source** (View > Markdown Preview, Ctrl+Shift+M). It is on when you open a Markdown file (`.md`, `.markdown`) and off for any other file, and you can switch it on for a text file too. It is drawn again a moment after you stop typing, from the text as it is now (nothing is saved for it), keeps its place on the page while you type, and follows the source when you scroll (the same fraction of the page is in view).
- **Safe like the viewer's Markdown:** raw HTML in the text is shown as text and never run, a link opens only to the web, mail or a file on this computer (a refused link is said in the status line), and a text over 256 KB is not rendered (the source stays editable).
- **Remembered for Markdown files:** if you switch the preview off (or on) in a Markdown file, the next Markdown file you open does the same. What you do in other files is not remembered.

## 2026-10-21#21 -- The release build's tests pass on the GitHub runner

- The first run of the release workflow stopped at the tests: four tests of SFTP connections failed on the GitHub runner, because there the Windows OpenSSH `sftp-server` comes first on the path and the tests spell their paths for the one in Git for Windows. The test helper now looks for Git's build first. (Test code only; the program is unchanged.)

## 2026-10-21#20 -- Version 0.4, the first release

- **Dossier has a release version: 0.4.** It is `RELEASE` in `dossier/core/version.py`, shown in Help > About and in `dossier --version` (`Dossier 0.4 (build 2026-10-21#20)`); the build number is still there to say which check-in a program is made from. A release is made by pushing the tag `v0.4`.
- **The release build:** `dossier.spec` (PyInstaller, one exe with the window and the command line), `build_exe.bat`, and `.github/workflows/release.yml`, which checks the tag against `RELEASE`, runs the tests, builds `dist/dossier.exe` with UPX, starts it once (`--version`, `ls`, `--check`) and publishes it with the notes in `docs/releases/v0.4.md`.
- **Tailnet list lines up:** the address is alone in the Details column, and the system and state ("Windows, online") are in the Type column, so each column starts at the same place.
- **The README is rewritten** to say what the program does today (it described things that were never built), with a download section; CLAUDE.md has the release rules.

## 2026-10-21#19 -- Tailnet devices on the Home page

- **A Tailnet section on the Home page lists the devices of your Tailscale network** (name, address, system, online or offline, and "this computer"), read from the Tailscale program already on the computer. If Tailscale is not installed or not running there is no section. Dossier only reads the list: it never logs in or out, changes a setting or scans the network.
- **Enter on a device adds it as a server:** the Add a Server dialog opens with the device's name and address filled in (SFTP first; change the type there). The right-click menu offers SFTP, WebDAV, OPDS and Subsonic directly, **Copy the Address** and **Read the Tailnet Again**.
- The list is read on a thread when Dossier starts and when you show the Home page (not more than every half minute), so the page never waits for it. **Network > Show Tailnet Devices on the Home Page** switches the section off.
- Not built: Taildrop (send files to a device) and Tailscale SSH checks.

## 2026-10-21#18 -- OPDS book catalogues and Subsonic music servers

- **Two new kinds of server (Add a Server... > Type):** **OPDS** (a book catalogue: Calibre, Calibre-Web, Kavita, Komga, COPS) and **Subsonic** (a music server: Navidrome, Airsonic, Gonic). They show as folders and files on the Home page and in the panels, like the other servers, and are **always read-only**: nothing in a catalogue can be changed from Dossier.
- **OPDS:** the catalogue's folders are folders, and every book is a file for each format it comes in (`The Sea Wolf.epub`, `The Sea Wolf.pdf`). Both OPDS 1.x (Atom) and OPDS 2.0 (JSON) are read, long feeds are followed page by page, and links to another computer are left out. Put the catalogue's address on the server in *Start in* (for example `/opds`). Login is the web's (Basic or Digest).
- **Subsonic:** `Artists / artist / album / tracks` and `Playlists`. The login sends a salted token, never the password. A track is the server's original file.
- **Copy a book or a track out** with F5 or drag it to the other panel; **Enter** downloads it and opens it in the program Windows has for it (a book reader, a music player). Nothing plays before the download is complete: this is not streaming.
- Tested against test servers of my own, not against the real programs; try it on yours and tell me what a real catalogue does differently. Search in a catalogue, covers and the Kavita kind of entry that is both a folder and a book are not built.
- A web address pasted into Host keeps the kind you chose.

## 2026-10-21#17 -- The function key bar and the command line can be moved too

- **The function key bar (F2 Rename ... F8 Delete) and the command line can go above the panels.** Each has the same six dots at its left end: drag them into the upper half of the panels to put the bar above them, into the lower half to put it back under them. A gold strip shows where it will land. The programs bar keeps its three places (menu bar row, under the menu bar, bottom).
- **View > Bar Positions** sets all three without the mouse, in one submenu with a group for each bar. Every bar's place is remembered. Above the panels the order is: programs bar, command line, function key bar.
- The view menu has one entry for this instead of one per bar.

## 2026-10-21#16 -- The programs bar can be moved

- **The tools bar (your programs and folders of programs) can sit in the menu bar's row**, after the menus, which gives a whole row of the screen back to the panels. **Drag the six dots at its left end** to move it: a gold strip shows where it will land (the menu bar's row, the row under the menu bar, or the bottom, above the command line), and letting go puts it there. **View > Tools Bar Position** does the same without the mouse. The place is remembered, and View > Tools Bar still shows or hides the bar wherever it is.
- The bar draws the edge that fits its place: a line under it below the menu bar, above it at the bottom, and none in the menu bar's row.

## 2026-10-21#15 -- Settings > Mouse Wheel

- **Settings > Mouse Wheel...** chooses what the wheel does in the picture viewer, separately for the wheel, Ctrl+wheel and Shift+wheel: *scroll the picture, then the next or previous one*, *next or previous picture*, *zoom*, *scroll up and down*, *scroll left and right* or *nothing*. A viewer that is open follows at once. In the file lists the wheel always scrolls.
- **The default wheel scrolls a zoomed picture and goes on to the next (or previous) picture when it reaches the end**, or at once when the whole picture fits the window. A spin that is still scrolling when it reaches the end does not jump on to the next picture; the next, separate turn does. Ctrl+wheel zooms and Shift+wheel scrolls, as before.

## 2026-10-21#14 -- The wheel changes pictures

- **In the viewer, the mouse wheel steps to the next or previous picture** (down is next, up is previous), through the pictures of the folder, like the arrow keys. **Ctrl+wheel still zooms** and **Shift+wheel moves** a zoomed picture. A touchpad's many small steps are added up, so one notch of movement is one picture.

## 2026-10-21#13 -- Tidier details

- **Folder tabs are shorter:** the height now follows the text (a few pixels above and below the letters) instead of Fusion's roomy default.
- **Column headers line up with their values:** Size is right-aligned over its numbers, the others are left-aligned (they were all centred).
- **The headings in a folder note are smaller** (a first-level heading is about one and a third times the text, not twice).
- **The main button of every dialog is gold and is the one Enter presses** (Save, Find, Add, Run...). One filter on the application does it, so a dialog added later gets it too.
- **Check boxes line up** at the left edge in the Copy and Move, Assistant Access and Fonts dialogs (they were indented under empty labels), and the "Forget the remembered list" button keeps its own width.
- The cursor colours of the two panels are unchanged on purpose: the active panel must be told from the other one.

## 2026-10-21#12 -- Quieter folder rows

- **No more "UP" and "DIR" in the lists.** The ".." row is just "..", and a folder's Size cell is empty until its size has been calculated (Alt+Shift+Return); the Type column already says Folder. Sorting is unchanged.

## 2026-10-21#11 -- Saving a text file waits for a program that holds it

- **A save of a text file no longer fails when a virus scanner or indexer has the new file open for a moment.** Putting the new file in place is tried again for a second or two (a Windows sharing violation) before giving up; if it still fails, the original file is untouched and the error is shown as before.
- One shared rule (`core/fsretry.py`) for the text editor and the archive writer, which had its own copy.

## 2026-10-21#10 -- A new menu layout, and two visual fixes

- **The menus are sorted by what they are for.** *Files* (what can I do to the files), *Edit* (new: Undo and the clipboard), *Mark*, *View* (how a folder is shown), *Go* (where am I and where to next), *Tools* (replaces *Commands*: search, duplicates, compare, batch rename, archives, checksums, the operation queue, terminals), *Network* (new: servers, shares, network drives), *Settings* and *Help*. Every command keeps its shortcut and is in exactly one place; a test checks that.
- Moved: *Home Page*, *Edit the Path* and *Pin Folder to Home Page* to **Go**; *Swap Panels* to **Go**; *Open as Archive*, *Pack*, *Unpack* and *Convert* to **Tools > Archives**; *Pause or Resume* and *Cancel Waiting Operations* to **Tools > Operations**; *Copy Marked Paths as Text* to **Edit**; the three saved-selection submenus into one **Mark > Saved Selections**; *Add a Server*, *Disconnect* and *Add Network Share* and *Network Drives* to **Network**; the slowness log to **Help > Slowness Log**.
- **Settings** now holds only settings: **Appearance** (Color Scheme, Icon Set, Fonts and Bold, Thumbnails, Columns, Drive Selector), Copy and Move, Opening Files (renamed from "Opening Files (Enter and Double-Click)"), Drive Memory and Assistant Access.
- **Fixed: an unchecked check box could not be seen in the light scheme** (white on a pale card, no edge); check boxes and radio buttons now have an outline in both schemes.
- **Fixed: the Home page showed one or two tall, half-empty rows** after a folder with a note (README) was shown in the same panel: the row that had held the note kept its height and span. It is reset now.
- The menu code moved out of the window file into `gui/menus.py`.

## 2026-10-21#09 -- Enter opens pictures and text in the viewer

- **Enter and double-click on a file now show it in Dossier's own viewer** when it is a picture, text or Markdown (a binary file, such as a Word document or a program, still goes to the program Windows has for it, so it is not shown as hex by accident). **Ctrl+Enter does the other thing**: the Windows program for a picture or text file, the viewer for a binary one. Marking is unchanged (Ctrl+click and Ctrl+Space still mark).
- **Settings > Opening Files** changes what Enter and double-click do: *pictures, text and Markdown in the viewer* (the default), *always in the Windows program* (the old behaviour) or *everything in the viewer*. Ctrl+Enter always does the opposite of the setting.
- A file inside an archive is judged by its name (it is not unpacked just to decide).

## 2026-10-21#08 -- An assistant can use Dossier (MCP)

- **`dossier mcp` is a local MCP server**, so an AI assistant such as Claude can look at your files and propose changes. It is **off until you switch it on** in Settings > Assistant Access, and it only sees the folders you list there (paths are resolved first, so `..` and links cannot get out). [docs/assistant.md](docs/assistant.md) lists every tool and setting.
- **Looking is read-only:** list a folder, stat, read text, read tags and EXIF, read folder notes, search, find duplicates, compare folders, see what the panels show and which files you have marked. The assistant can also mark files for you in the window.
- **Changing needs two keys.** `allow_file_changes` must be on, and every change (copy, move, delete, rename, sync) is only a *plan* until the assistant asks to commit it: then the Dossier window shows the change in words and **you press Run or Reject**. The window makes the plan again itself and checks the folders again. With no window open, nothing happens.
- File names, text and tags are marked as untrusted content, every call is logged (opt-out, never file contents, one megabyte at most), and the settings dialog opens and clears the log.
- Removed the "Tab switches panel, Space marks" hint from the status line.
- Tests now give every test its own assistant folder, so a test window never touches the real settings.

## 2026-10-21#07 -- The command line

- **`dossier <command>` runs without the window**, in the same program (the same exe once it is built): the first argument decides, a command name runs the command and anything else starts the window as before. The commands: **`ls`** (a folder, or what is inside an archive), **`info`** (size, times, tags and what is inside audio, comics, video and photos), **`find`** (by name, size, date, text and tag), **`checksum`** (in the format of `sha256sum`, and `--check` against such a list), **`copy`**, **`move`**, **`delete`**, **`dups`** (files with exactly the same content, and delete the extras) and **`compare`** (two folders, and `--sync` to make them alike). `dossier help` and `dossier <command> --help` list the options; [docs/cli.md](docs/cli.md) has them all with examples.
- **The same rules as the window, made for scripts:** everything that changes files has **`--dry-run`** (the plan, and nothing else); **nothing is overwritten** unless `--on-conflict overwrite` says so; what is deleted or replaced goes to the **recycle bin** (`delete --permanent` is the only way for good); one copy of every duplicate group always stays. Wildcards are expanded by Dossier, since the Windows command prompt does not.
- **Output a script can read:** text on stdout, or with **`--json`** one JSON document and nothing else there; progress and warnings on stderr (`-q` silences them); **`--output FILE`** writes the result to a file that is complete when the program ends. Exit codes: 0 all went well, 1 some items failed, 2 a mistake in the command or a path that does not exist, 70 a bug, 130 Ctrl+C.
- It uses the Redactor apps' shared command-line skeleton, so it behaves like theirs. Servers (SFTP, SCP, WebDAV, FTP) are not reachable from the command line: they need a login and a key or certificate question that only the window asks.
- Also: `dossier --askpass` (the built exe answering ssh's request for a password, with no window), which the SFTP and SCP connections need once Dossier is built as an exe.

## 2026-10-21#06 -- FTP and FTPS servers

- **A fourth kind of server: FTP and FTPS.** Choose *FTP or FTPS* as the type, or paste an `ftp://` or `ftps://` address into Host. **Encrypted (FTPS) is ticked by default**; plain FTP sends the password and every file as readable text, which the dialog and the server's description (*not encrypted*) say plainly. Folders are `ftp://user@host/path` and work like any other, **read-only until you switch it off**. A server with no user name is logged into as anonymous.
- **FTPS is checked like the web:** the system's certificates decide; a server with a certificate of its own shows its SHA-256 fingerprint and asks once, and a changed certificate stops the connection (Cancel is the default). The data connections resume the control connection's TLS session, which many servers (vsftpd) demand.
- **Exact listings:** the machine-readable `MLSD` is used when the server has it. A server without it is read from its text listing (Unix and DOS/IIS styles) and **you are told once that sizes and times may be wrong**.
- **Several connections, a few at a time:** a transfer keeps an FTP connection busy, so every open file gets a connection of its own (kept and reused), at most two for reading and two for writing at once, because servers limit them. Listing a folder while a big file is copied therefore works. A straight read of a file is one transfer, a jump in a file asks the server to start there (`REST`).
- Modified times are set on uploaded files where the server has `MFMT`, and kept as the server dates them where it has not. A replaced file is deleted before the new one takes its name (FTP has no replace). Deleting is permanent and says so: there is no recycle bin on a server. Names are UTF-8 (negotiated); a server that cannot be read that way is read as Latin-1.
- Not in this build: implicit FTPS on port 990 (explicit TLS on the usual port only), resuming a failed upload.

## 2026-10-21#05 -- WebDAV servers

- **A third kind of server: WebDAV** (a web folder over HTTPS or HTTP): Nextcloud and ownCloud (`https://host/remote.php/dav/files/you`), a NAS, Apache, nginx, Pluteus. Choose *WebDAV* as the type when you add a server, or **paste the whole web address into Host**: the encryption, port, user and base folder are filled in for you. The base folder is the top of the connection, so a Nextcloud account shows your files and not the server's internals. Folders are `webdav://user@host/path`; everything that works on a folder works there (copy in both directions, move, rename, delete, F3, search, compare, duplicates), **read-only until you switch it off** for that server.
- **The certificate is checked.** HTTPS is verified against the certificates this computer trusts. A server with a certificate of its own (a NAS, a home server) shows you its **SHA-256 fingerprint** and asks once; from then on the connection is made only to a server that shows exactly that certificate, and a changed certificate stops the connection with a warning (Cancel is the default). There is no "ignore certificate errors" switch.
- **Login:** none (a public folder), Basic or Digest, as the server asks. The password is asked for only when the server wants one, can be kept in the system's password store, and on a connection that is **not encrypted** (plain HTTP) the dialogs and the server's description say that the password and every file travel as plain text.
- **Safe reading of the server's answers:** a reply with a document type declaration (the "billion laughs" attack) is refused and a reply is capped in size. A folder is deleted only when it is empty (a DELETE on a collection would remove everything in it on the server), so deleting a tree is planned and confirmed by Dossier like on any other server, and it is permanent: a web folder has no recycle bin.
- **Files:** read in ranges (any size, any starting point); written in one go when the file is closed, as WebDAV works. A server dates a file when it is uploaded: the modified time of a copy to a web folder is the time of the copy (compare and sync by time keep that in mind).
- **Fixed:** closing the window while a panel was on a server could end the program with an error (the panel asked to reconnect after the connections had been closed on purpose).

## 2026-10-21#04 -- SCP: servers that have a shell but no SFTP

- **A second kind of server, SCP,** for servers that offer only a command line over SSH (old routers and NAS boxes, restricted accounts). Choose *SCP* as the type when you add the server. Its folders are `scp://user@host/path` and work like any other: list, copy in both directions, move, rename, delete, new folder, F3, compare and sync, with the same host-key question, login (keys, ssh-agent, then a password) and **read-only until you switch it off**.
- **How it works:** Dossier keeps one `sh` running over the connection and sends it ordinary POSIX commands (`ls -la`, `mkdir`, `mv`, `rm`...), each followed by a marker that carries its exit status, so the end of every answer is known exactly. File contents are read with `dd` (any size, any starting point) and written as base64 text that the server decodes. It needs only the tools such servers have (`sh`, `ls`, `dd`, `mkdir`, `mv`, `rm`, `rmdir`, `touch`, `base64`). Every name goes through the shell quoted, so nothing a file is called can run as a command.
- **Slower than SFTP** (a command is a round trip and base64 is a third larger): use SFTP when the server has it. A server that allows only `scp -t` and no shell at all cannot be browsed. Times shown by `ls` are to the minute (to the day for files older than half a year), converted from the server's own time zone.
- The type box in the server dialog says so. SFTP and SCP entries for the same address are kept apart.

## 2026-10-21#03 -- SFTP servers

- **Servers on the Home page.** A new *Servers* section lists your saved servers and ends with *Add a server...* (also Commands > Add a Server...). A server has a name, host, port, user, an optional key file and start folder, and two choices: **read-only** (the default: nothing on the server can be changed from Dossier until you switch it off for that server) and *keep the password in the system's password store*. Right-click a server for Connect/Open, Open in a New Tab, Disconnect, Edit and Remove. **Nothing is contacted until you open a server**: the list never pings, scans or connects on its own.
- **Opening a server** shows its folders like any other (`sftp://user@host/path`, also typed in the address bar). Copy, move, delete, rename, new folder, search, find duplicates, compare and F3 all work there, in either direction between a server and your disks, with the usual conflict dialog, progress, queue and cancel.
- **The server's key is never trusted silently.** The first time you are shown its fingerprint and asked; the key you approve is remembered. If it later differs you get a plain warning (a server that was reinstalled, or somebody in the middle) and the connection is stopped; replacing the key is a separate, deliberate button and Cancel is the default.
- **Login:** your keys and the ssh-agent are tried first. Only if the server refuses them are you asked for a password (or the passphrase of your key), with a box to keep it in the Windows credential manager (or the macOS keychain or the Linux secret service). The password never appears on a command line, in a file or in a log.
- **A server has no recycle bin:** deleting there is permanent, and the confirmation says so. Replacing a file on a server overwrites it for good, which the plan warns about.
- **No extra program or library is installed:** Dossier uses the OpenSSH that comes with Windows 10/11, macOS and Linux (`ssh -s host sftp`) and speaks the SFTP protocol itself, so the program does not grow. If OpenSSH is missing the connect says so and where to get it (Windows: Settings > System > Optional features > OpenSSH Client).
- **Disconnect** (Commands, or the server's menu) ends the connection; closing Dossier ends every connection. A connection that drops says so and can be opened again.
- Not in this build: SCP (next), WebDAV and FTP.

## 2026-10-21#02 -- Viewer modes: pictures, hex and Markdown

- **F3 now looks at what a file is, not only its name.** The viewer has four modes and opens the one that fits; the **View as** box in its toolbar switches a file to any other sensible mode (Markdown as its source, any file as hex, a binary file as text).
- **Pictures:** PNG, JPEG, GIF, BMP, WebP, TIFF and icons (recognised by their first bytes, so a photo called `.dat` is still a photo). The picture is fitted to the window and never enlarged; `+` and `-` or Ctrl+wheel zoom, `0` fits, `1` shows every pixel, double-click toggles, `L` and `R` turn it a quarter (the file is never changed), dragging moves a zoomed picture. A photo taken with the camera turned is shown upright by its EXIF orientation. **Info (I)** opens a panel with the file's facts and, for a photo, its **EXIF**: camera, lens, exposure, aperture, ISO, focal length, date taken and GPS position. The EXIF is read by Dossier itself (no extra program). Opening **one picture steps through all the pictures of its folder** with Ctrl+Page Down and Ctrl+Page Up, in natural order.
- **Hex:** a binary file opens as offsets, bytes and text side by side, for a file of any size (only the visible rows are read; a growing file is followed). Click or use the arrow keys, Home, End, Page Up and Down; Shift extends a selection; Ctrl+C copies it as hex, Ctrl+Shift+C as text; Ctrl+G goes to an offset (decimal or `0x` hex). **Find** looks for text (case optional) or for bytes (`DE AD BE EF`) forward and back and around the file, on a thread. The status line reads the bytes at the cursor as 8, 16 and 32-bit numbers. Hex is read-only.
- **Markdown:** `.md` files are shown **rendered**, with the source one choice away. Safe by design: raw HTML (`<script>`, `<form>`, `<img>`...) is shown as text and never run, nothing is fetched from the network, a file over 256 KB is shown as its source, and a link opens only if it is `http`, `https`, `mailto` or a file on this computer (a link to another `.md` opens it in the same viewer; `javascript:`, `data:` and the rest are refused).
- Binary files used to open as unreadable text with a warning; they now open as hex, and the text view still warns.

## 2026-10-21#01 -- Compare Folders and Synchronize

- **Commands > Compare Folders and Synchronize... (Alt+Shift+F8)**, also in the right-click menu of empty space (*Compare with the Other Panel...*): the folder of the left panel against the folder of the right. Choose whether to look in the subfolders, how two files are told apart (**size and time**, **size only** or **content**, which reads the files and stops at the first different byte), how close two times must be to be the same time (two seconds by default, as a FAT drive keeps them) and whether to ignore a difference of exactly one hour (summer time on FAT drives).
- **The differences are listed**, nothing else: only on the left, only on the right, newer on the left, newer on the right, different at the same time, and a file against a folder. A folder that exists on both sides is entered, a folder on one side only is one row for everything in it. Filter the list by kind.
- **Synchronize** in five directions: *update the right* or *the left* (copy what is new or newer, never replace a newer file, never delete), *both ways* (the newer version wins; what cannot be decided is left alone), and *make the right the same as the left* or the other way (replaces files that differ and moves the extras to the recycle bin). Each row shows what will happen to it and has a check box to leave it out; the line below says what the checked rows add up to. A confirmation lists it all before anything runs.
- **It uses the ordinary copy and delete plans**: progress, the queue, pause and cancel, verify, the recycle bin and Ctrl+Z work as they do for every copy. **Mark the Differences in the Panels** marks each side's differing files instead, so you can use any command on them.
- **Commands > Compare the Two Current Files:** the file under the cursor in each panel, byte by byte: identical, or the byte where they first differ, with sizes and dates.

## 2026-10-20#37 -- Find Duplicate Files

- **Commands > Find Duplicate Files... (Alt+Shift+F7)**, and in the right-click menu on a folder and on empty space. Choose where to look (this panel's folder and everything below it, and optionally the other panel's folder too, which finds the files that are in both places), the smallest file to bother with and, if you like, which file names. Files are duplicates when they hold **exactly the same bytes**, whatever they are called or where they are.
- **Fast on a big library:** three steps, each throwing away what cannot be a duplicate. Files of different sizes are different (most files are done here and never opened); of the files that share a size only the first and last 64 KB are compared; only the files that still look identical are read completely (SHA-256). A reported group is therefore really identical, and a file that cannot be read is counted and left out, never reported. It runs on a thread with a Cancel; empty files are ignored.
- **A box lists the groups**, biggest waste first: each group shows its copies with folder and date, and the summary says how much space the extra copies take. *In every group keep* the oldest, the newest or the one with the shortest path, then **Check the Others**; or check copies by hand. **Delete Checked...** goes through the ordinary Delete command (its confirmation, the recycle bin, the queue and Ctrl+Z are unchanged), **Mark Checked in the Panels** only marks them, and **Show All in a Tab** lists every copy as a normal file list.
- **At least one copy of every group always stays:** the delete button is greyed out while all copies of a group are checked, and the command refuses it as well.

## 2026-10-20#36 -- Metadata columns

- **Sixteen new columns that show what is inside the files** (Settings > Columns..., or right-click a column header): *Title (tag), Artist, Album, Track, Year, Genre, Length, Bitrate* (audio tags: mp3, flac, m4a, ogg and more), *Series, Issue, Writer, Publisher, Pages* (the ComicInfo of a CBZ) and *Resolution, Video codec, Audio languages* (video: mkv, mp4, avi and more, read through ffprobe). Length, Title, Year, Bitrate and Publisher come from whichever kind of file has them. They are **read-only** for now.
- **Off everywhere until you switch them on, and a folder layout can switch them on for one folder only** (View > Folder Layout > Keep This Layout for This Folder...): a column that opens every file is only paid for where you work with that kind of file. An old column choice or folder layout made before these columns existed does not show them.
- **Read on the side:** the files are opened by a few background threads, only the kinds of file the visible columns need (an Artist column never opens a comic or a video), and the cells fill in a batch at a time while the list stays usable. Each answer is kept in memory by path, size and time, so a file is read again only when it has changed. Nothing is written to disk. The columns sort (numbers in their natural order) once the values have arrived.
- A file that cannot be read (damaged, no ffprobe, no mutagen) has empty cells, never an error.

## 2026-10-20#35 -- Folder layouts

- **View > Folder Layout** lets a folder keep its own **columns, view (details or thumbnails), thumbnail size and sort order**: *Keep This Layout for This Folder Only*, *Keep This Layout for This Folder and Its Subfolders*, *Back to the Default for This Folder* and *Forget All Folder Layouts...*. A photo folder can be thumbnails sorted by date, newest first, while everything else stays as it was; a music folder can show columns the other folders do not.
- **Which layout applies:** the rule of exactly that folder, else the nearest parent folder whose rule covers its subfolders, else the ordinary choice. Leaving the folder puts the panel back to the ordinary columns, view and sort; the ordinary choices are never overwritten by a folder's layout.
- **While a folder has a layout, changing it changes that layout:** switching a column on or off, dragging columns, Details/Thumbnails, thumbnail size, a click on a column header or Arrange By. A small **Folder layout** note appears in the status line (with a tooltip saying which folder it comes from), so a column that "disappeared" is explained. The other panel is not affected unless it shows a folder under the same rule.
- Only the folders you set are stored (in the settings file, at most 500); nothing is recorded about the folders you merely visit. The Home page, archives and search results have no layout of their own. This is also the base the metadata columns will be built on, so an expensive column can be on only where you work with that kind of file.

## 2026-10-20#34 -- The Windows menu at the bottom of the right-click menu

- **More Options (Windows Menu)...** is the last entry of our right-click menu, on an item and on empty space (Windows only, for real files and folders; not for items inside an archive, search results or the Home page). It opens the **full Windows menu** the shell builds for the same items: 7-Zip, Git, Defender, Open with, Send to, Share, PowerToys (File Locksmith, PowerRename) and everything else installed programs have added. **Hold Shift** when choosing it for the extended entries.
- **Our own commands win:** if you pick Cut, Copy, Paste, Delete or Rename in the Windows menu, Windows is *not* asked to do it. Dossier runs its own command on the same items, with its own conflict dialog, progress, undo and tags. Everything else is run by Windows, and the lists refresh afterwards.
- **A slow or stuck shell extension cannot freeze Dossier:** the menu is built and shown on a thread of its own, with its own hidden window, and the status line says "Opening the Windows menu..." while it works. The shell is called directly (no extra package is installed).

## 2026-10-20#33 -- Continue unfinished copies, moves and deletes after a restart

- **Settings > Copy and Move > After a restart:** switch on *Remember copies, moves and deletes that were not finished*. It is **off by default**: the list names the folders and files you worked on, so nothing is written unless you ask for it.
- While it is on, every copy, move (also by drag, Ctrl+X/Ctrl+V and the batch of marked items) and delete is written to `queue.json` next to the settings file when it is queued, and taken off the moment it ends: done, cancelled or failed. If the program is closed or killed (or the computer loses power) while it runs or waits, the entry stays.
- **At the next start-up** a box lists what was not finished and offers *Continue*, *Discard the list* or *Not now* (the list stays for next time). Continue makes the plan again from what is still on the disk: a move whose source is gone drops out, **a file that was copied completely is recognised (same size and time) and skipped**, a half-written file never carried its final name, and a name that is really in conflict is asked about as usual. Nothing is done twice.
- **Forget the remembered list now** in the same dialog, and switching the setting off, empty the file.

## 2026-10-20#32 -- The test suite runs in 2 minutes instead of 48

- **Tests only, nothing changes in the program.** The tests never deleted the windows they opened, so hundreds of closed windows and thousands of menus kept receiving events and every later test got slower (a window that opened in 1 second took 15 at the end of a run). A shared test fixture now deletes them after each test: the full suite (1036 tests) runs in about 2 minutes, and the check before each push no longer takes most of an hour.
- The in-memory test file system (`memfs`) no longer trips when worker threads add files while another thread lists or renames; the faster run made that race show.

## 2026-10-20#31 -- Tools bar folders follow the colour scheme; Add Program fixed

- **Folders on the tools bar** (and their drop-down menus) are now skinned by the dark/light scheme: the folder icon is drawn in the scheme's accent colour like the folders in the file lists, the drop-downs get the bar's background, border, selection colour and separators, and everything is redrawn when the scheme changes. Before, the folders were the plain system icon and the drop-downs had the default look.
- **Fixed: Add Program failed** with "'CancelToken' object is not callable" when it looked at the Start menu. A test now runs the real flow on its thread.

## 2026-10-20#30 -- Add a Program starts in the Start menu

- **Add Program** (the + on the tools bar, or right-click > Add Program) now **opens the Windows Start menu as a tree**, with its groups (PowerToys, 7-Zip...) and a search box. Double-click a program, or select it and press Add; its name and shortcut are filled in and you can still change the arguments, the start folder and where it goes. The shortcut is started the way the Start menu starts it, with its own settings.
- **Other program...** goes on to the plain dialog (browse for a file, or start from the short list of suggestions). A computer without a Start menu goes straight to it. Uninstallers are left out of the list. The Start menu folders are read on a background thread.

## 2026-10-20#29 -- The tools bar can be seen

- An **empty tools bar was almost invisible** (a greyed-out line of text on the menu bar's own colour), so it looked as if there was no bar. It now has its own background and a line under it, a plain hint ("Your programs go here: press + or right-click this bar to add one") and a **+ button** that is always at the end of the bar, like the + of a browser's bookmarks bar; it opens the same menu as a right-click (Add Program, Add Folder, Add Separator, Manage Tools, Hide the Tools Bar). View > Tools Bar shows or hides the bar.

## 2026-10-20#28 -- Thumbnails

- **View > Thumbnails (Ctrl+2)** shows the list as a grid of pictures with the names under them; **View > Details (Ctrl+1)** goes back. The choice belongs to each panel and is remembered, so the left panel can show photos while the right shows details. The Home page always shows details.
- **What gets a picture:** image files (JPEG, PNG, GIF, BMP, WebP, TIFF, icons; photos turn upright), the **first page of a comic archive** (cbz), the **cover of an epub**, the **cover art inside audio files** (mp3, flac, m4a, ogg...), and a **folder gets the picture lying in it** (cover.jpg, folder.jpg, front.jpg, poster...). Everything else, and anything whose picture cannot be read, keeps its type icon, drawn smaller in the middle of its tile.
- **View > Thumbnail Size** has five sizes (Small 64 to Huge 256); **Ctrl+mouse wheel** changes the size in the thumbnail view. **View > Arrange By** sorts the list by name, size, date, type, created or last opened, ascending or descending, in either view (the thumbnail view has no column headers to click).
- **Made on the side, kept in memory:** the pictures are made by a few background threads, only for what is on screen, and appear one by one; the window never waits for a picture. They are kept in memory while the program runs (up to 800) and **nothing is written to disk**. A big folder costs what you can see.
- **Settings > Thumbnails...:** pictures on **network drives** are off by default (each one has to be read over the network); a **frame from videos** is off by default and needs ffmpeg; a button forgets the pictures made so far.
- The keyboard, marking, dragging, dropping and the right-click menu work in the thumbnail view exactly as in the table. The folder note is not shown in the thumbnail view.
- Under the hood the details table and the thumbnail view share one list, one cursor and one set of marks.

## 2026-10-20#27 -- The tools bar

- **A row of your own programs between the menu bar and the panels**, like the bookmarks bar in a browser. One click starts a program on the marked items (or the item under the cursor); the program's own icon is shown. **Folders** hold more programs, and more folders inside them, as a drop-down. View > Tools Bar shows or hides it.
- **Add a program:** right-click the bar > Add Program (a list of the ones found on this computer starts you off: 7-Zip, File Locksmith and PowerRename from PowerToys, Notepad, Calculator), or **drop a program file on the bar**. Name, program, arguments and the folder to start in; choose the bar itself or a folder to put it in.
- **Arguments** can use `{files}` (every marked item, or the one under the cursor, each as its own argument), `{file}` (the first), `{name}` (its name), `{dir}` (this panel's folder) and `{other}` (the other panel's folder). The line is cut into words first and the values put in afterwards, so a file name with spaces or quotes can never become a second argument or a command, and no shell is started. A mistake (an unknown placeholder, `{files}` stuck to other text) is explained in the dialog.
- **Edit, remove, move left or right** from the right-click menu of a button; **Manage Tools** shows the whole bar as a tree where you drag items into folders and into order. The list is kept in the settings file only.
- On Windows the system starts the program, so a shortcut, a script or a program that asks for administrator rights works as it does from Explorer.

## 2026-10-20#26 -- Batch Rename, Terminal Here and Pin in the right-click menu

- **Batch Rename** submenu on every item (By Pattern, Search and Replace in Names, Change Case, Number the Files), in place of PowerRename in the Windows menu. It works on the item you right-clicked, or on all the marked items when you click a marked one; before, batch rename only used marks.
- **Terminal Here** and **Pin to the Home Page** on a folder item: the terminal opens in that folder (not the one the panel shows), and the folder is pinned.

## 2026-10-20#25 -- The right-click menu

- **Right-click (or the Menu key, or Shift+F10) opens a menu** in the file lists. On a **file**: Open, View, Edit, Copy to and Move to the other panel, Copy, Cut, Paste, Copy the Path as Text, Rename, Delete, Pack to Zip, Properties. On a **folder**: Open, Open in a New Tab, Open in the Other Panel instead of View and Edit. On an **archive** also Unpack, and Convert Archive to Zip for 7z, RAR, tar and the like. On **empty space**: New Folder, Paste, Select All, Terminal Here, Search, All Files Below This Folder, Refresh, Properties of This Folder. On the **Home page**: Open and Open in a New Tab for a drive, place, pin or network location, Remove from the Home Page for a pin or saved location, and Add a Network Share on empty space.
- **Which items it works on:** right-click a marked item and the menu works on all the marked items; right-click an unmarked item and it works on that item alone, while the marks stay as they are. The same rule as dragging. Entries that need one item (Rename, View, Edit, Unpack) are greyed out when several are marked.
- Every entry runs the command the program already has, the same one as its menu entry and key, so the conflict dialog, progress, undo, tags and the zip edits all behave as usual. Nothing in the menu reads the disk: whether an entry shows is judged from the name.

## 2026-10-20#24 -- Drag and drop

- **Drag files with the mouse.** Press on an item and drag: the item goes along, or all the marked items when you drag a marked one. Drop it on a folder row (that folder gets it), on the empty part of the other panel (that panel's folder gets it), on an open zip (the file is added to the zip), or on another program such as Explorer. The folder under the pointer is highlighted. Files dragged in from Explorer are taken too.
- **Move or copy:** with no key, a drop moves on the same drive and copies to another drive; **Ctrl** always copies, **Shift** always moves. Something dragged out of an archive can only be copied out.
- **It is the normal copy engine:** a name that is already taken opens the per-file conflict dialog, progress and Cancel work, a same-drive move can be undone, tags follow. A drop makes no confirmation box unless you ask for one (Settings > Copy and Move > Dragging with the mouse). Dropping on itself, into its own subfolder, on the Home page, or into a place that cannot take files is refused, and the pointer shows it.
- **A plain drag no longer marks; Ctrl+click and drag does.** Before, dragging down the list marked every item the mouse passed. That was a misreading of the specification, which meant Ctrl+click and drag, and it would have fought with dragging files. Now Ctrl+click an item and keep the button down: every item from there to the pointer is marked (dragging back takes the far end off again; starting on a marked item unmarks instead). Space, Insert, Ctrl+click, Shift+click, Shift+arrows and Ctrl+F work as before.
- Not tried against Explorer by hand: the drag to and from other programs uses the standard file-list format and is covered by tests only up to the point where the operating system takes over.

## 2026-10-20#23 -- Starting from source tells you what is missing

- **A clear message instead of a traceback.** If PyQt6, send2trash or the shared Redactor package (redactor_common, tag 2026-10-20-02 or newer) is missing or too old in the Python you start with, Dossier now says which one and what to run (`python -m pip install -r requirements.txt`), in a box on Windows and on the console. A computer can have several Pythons; the message belongs to the one that was started.
- `python -m dossier --check` only checks and says what is missing. `python dossier/__main__.py` and `python path/to/dossier` start the program too, not only `python -m dossier`.
- The package metadata (pyproject.toml) now lists everything the program imports (PyQt6, QScintilla and redactor_common were missing), so `pip install .` brings them. The README has the steps to run it from a checkout.

## 2026-10-20#22 -- Fonts and Bold

- **Settings > Fonts and Bold...** has two bold switches and a font. **Bold in the lists** covers folder names, marked items and the names and section titles on the Home page. **Bold in the bars** covers the address bar, the tabs and the buttons. Both are on by default, as before.
- **Font:** one family and size for the whole program, or the system's own (the default). A sample line shows the choice before you save, and "Back to the defaults" undoes everything. The choice is kept in the settings file and applied at start-up.

## 2026-10-20#21 -- The Home page says why it ignores the column choice

- Adding or removing columns (Settings > Columns, or a right-click on a column header) seemed to do nothing in a panel that was showing the Home page, because that page always has its own three columns (Name, Type, Details). The choice was kept all the time and applied to the folders you open, but nothing said so. Now the status line explains it whenever you change columns while the active panel shows the Home page. In a panel with a folder open the columns change at once.
- New columns are added to the right of the ones already there. In a narrow panel they can sit past the right edge: scroll right, or make the panel wider with the divider.

## 2026-10-20#20 -- A zip that is open elsewhere for a moment is waited for

- Changing a zip (delete, rename, copy in) swaps the new file in for the old one. If another program has the old one open at that moment (the panel's own listing, a virus scanner, a preview), Windows refuses the swap. Dossier now waits for up to a few seconds and tries again; only if the file stays in use does it stop, say "the archive is in use by another program" and leave everything as it was. Found by a full test run in which three tests failed this way.
- The old test that expected Delete and New Folder inside an open zip to be refused now expects the confirmation instead.

## 2026-10-20#19 -- Change a zip from the file lists

- **Copy and move into an open zip:** open a zip or zip-based file (zip, cbz, epub, docx and the like) in one panel, mark files in the other and press F5 or F6. All of them are added in one go. The confirmation says how many files and bytes go in, how many existing entries are replaced, and what happens to the old zip. A move trashes the originals after the zip is written.
- **Delete, rename and New Folder inside an open zip** work with F8, F2 and F7. Each one writes the zip again as a new file that replaces the old one; the old one goes to the recycle bin (a network drive has none, and the confirmation says the old file is deleted there).
- **Safe by construction:** the new zip is written beside the old one under a temporary name and read back before it replaces anything; a failure or a Cancel leaves the original untouched. Entries that stay keep their dates, their method (an epub's `mimetype` stays first and stored), their order and the archive comment. A name that would clash is refused before anything is written.
- Archives Dossier can only read (7z, RAR, tar) say so and point to Convert Archive to Zip. Encrypted zips are not rewritten.

## 2026-10-20#18 -- "Home" means the Home page only

- Your own folder (`C:\Users\<you>`) is now called **`<you> (your folder)`** in the Drive list and under Places on the Home page (with a tooltip, "Your user folder"). Before, three different things were all called Home: the Home page (the house button and the Home tab), the user folder in the Drive list, and the user folder under Places.

## 2026-10-20#17 -- Pack to zip, unpack, and convert other archives to zip

- **Commands > Pack to Zip... (Alt+F5):** packs the marked items (or the one under the cursor) into a new zip, by default in the other panel's folder. Pick the name, the compression (normal, fast, maximum, store only), and whether files that are already compressed (pictures, music, video) are stored as they are. It never overwrites an existing zip, shows progress with Cancel, keeps each file's date, and writes under a temporary name that becomes the zip only when it is complete.
- **Commands > Unpack... (Alt+F9):** unpacks the archive under the cursor (zip, 7z, RAR and the others Dossier can open) into a folder named like it, in the other panel by default; you can change the folder. It goes through the normal copy engine, so the conflict dialog, progress, Cancel and undo behave as for any copy.
- **Commands > Convert Archive to Zip:** writes a zip with the contents of a 7z, RAR, tar or other archive beside it. The original stays where it is.
- **Writing is zip only** (zip, cbz, epub, docx and the other zip-based files; 7z and RAR stay read only). The engine that changes a zip safely is in place: it takes members out, renames them or adds files by writing a new archive beside the old one and swapping it in, so a failure leaves the original untouched; an epub's `mimetype` stays first and stored, comments and dates are kept. Using it from the file lists (copy into an open zip, delete and rename inside one) is the next step.

## 2026-10-20#16 -- The tag colour label in the list

- **Label column** (Settings > Columns, off by default): a filled dot in the label's colour and its name (red, orange, yellow, green, blue, purple, grey). The name is there so the label can be told and sorted without telling colours apart. It is read in the background with the Tags and Rating columns, and any one of the three is enough to switch the reading on.

## 2026-10-20#15 -- One way to add a network share

- **"Add a network share..."** replaces the two Home page entries "Add a network location" and "Mount a network share". One dialog: pick SMB or NFS, type the address, and tick **Also mount it on a drive letter** (drive letter or the next free one). Without the tick an SMB address is only saved on the Home page and opened like a folder, nothing is contacted. With it, Windows mounts the share and it shows up under Network with a light. NFS is always mounted, because Windows cannot open an NFS share by its address; the tick is set and cannot be removed.
- Commands > Add Network Share... and F7 on the Home page open the same dialog. The separate Go > Mount Network Share entry is gone.
- Share names with spaces (`\\nas\my media`) now work for mounting.

## 2026-10-20#14 -- Tags in the lists, tag search, and a Flatten button

- **Flatten button** (the three bars, right next to the sigma button in every panel's address row): every file below the folder as one list in a new tab. Same as Go > All Files Below This Folder (Ctrl+Shift+B).
- **Tags and Rating columns** (Settings > Columns, off by default): the tags and stars of the items in the list, read in the background and only while a tags column is on. They sort like the others and follow a save in Properties.
- **Mark > Mark by Tag...**: marks the items of this list that carry every tag you type (several separated by commas). **Unmark by Tag...** takes the marks off again. The tags are read on a thread with a box.
- **Search by tag:** the Search dialog has Tagged with, Rating (1 to 5 stars or more) and Label. The tag test runs after the cheap name, size and date tests, so only files that already fit are opened.

## 2026-10-20#13 -- Copy and move keep the tags

- **Tags follow the file.** Dossier's copy, move to another drive and paste now put the tags of a file (and of a folder) on its copy. Before this, large files kept them (the system's own copy) but small files lost them, because Python's copy leaves the NTFS stream behind. Copying over an existing file gives it the new file's tags. A move on the same drive never lost them.
- **A drive that cannot hold tags** (FAT, exFAT, memory sticks) does not stop the copy: the files are copied and the status line says once how many were copied without tags.
- Files without tags cost one quick look at their stream and nothing else.

## 2026-10-20#12 -- Tags on files (the Properties Tags tab)

- **Properties > Tags:** put tags, a rating (1-5 stars), a colour label and a note on a file or a folder. Several items at once: add tags to all of them, take tags off all of them, set the rating or label; a field you leave alone is not touched. A "tags you used before" list (this session only) helps you reuse spellings.
- **No database and no extra files.** The tags are kept on the file itself: in an NTFS alternate data stream named `dossier` (on Linux in the extended attribute `user.dossier`, with `user.xdg.tags` and `user.baloo.rating` for other Linux programs). Saving tags does not change the file's content, size or modified time, also not on read-only files.
- **Drives that cannot hold tags** (FAT, exFAT, memory sticks) and archives get a read-only Tags tab that says why.
- Tags are lost when a file is copied by a program that ignores them, or sent by mail or to most cloud services. Carrying tags along in Dossier's own copy and move is the next step (the part that does it, `copy_tags`, is written and tested).

## 2026-10-20#11 -- Copy and move settings in one place

- **Settings > Copy and Move...** is one dialog for everything that changes how files are copied or moved. It replaces three separate Settings entries (Copy Speed Limit, Verify Copies After Copying, Ask When a File Cannot Be Copied) and adds the options that had no way in: how many small files at the same time (or automatic), whether the system copies large local files, when to push the data to the drive (removable and network only, always, never), how many extra tries for a file another program holds, and how long to wait before the first retry.
- The "verify" checkbox in the copy confirmation box still works and stays in step with the dialog. Nothing changes for you until you change a value: the defaults are the old behaviour.

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
