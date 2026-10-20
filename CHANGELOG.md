# Changelog

Build numbers have the form `YYYY-MM-DD#NN`, as in the Redactor apps. Each check-in that changes real code runs `python bump_version.py` and adds a section here.

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
