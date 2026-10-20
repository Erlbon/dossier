# Changelog

Build numbers have the form `YYYY-MM-DD#NN`, as in the Redactor apps. Each check-in that changes real code runs `python bump_version.py` and adds a section here.

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
