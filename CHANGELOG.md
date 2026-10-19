# Changelog

Build numbers have the form `YYYY-MM-DD#NN`, as in the Redactor apps. Each check-in that changes real code runs `python bump_version.py` and adds a section here.

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
