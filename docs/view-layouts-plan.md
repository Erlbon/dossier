# Folder layouts: columns, view mode and sort that apply per folder (plan)

Owner's idea, 2026-10-20: when the metadata columns arrive, a columns choice should have a **scope**, so an expensive column (artist,
album, resolution...) is on only where the owner works with that kind of file.

Scopes, in the Add or Remove Columns dialog and the header menu:

1. **All folders** (the default, what exists today).
2. **This folder and all its subfolders.**
3. **This folder only.**

Resolution when a folder is shown: a rule for exactly this folder (either of the two folder scopes), else the nearest parent folder with
a "subfolders" rule, else the all-folders choice. "Back to the default for this folder" removes the rule. The status line (or the header
menu) says when a folder rule is in force, so a column that "disappeared" is explained.

The same rule carries more than the columns: the **view mode and thumbnail size** (details or thumbnails) and the **sort order**. A photo
folder can be thumbnails sorted by date while everything else stays details. One store, one resolution, one dialog.

Storage: a JSON list in the settings file, ``{path, scope, columns_hidden, columns_order, mode, size, sort}``, keyed by the normalised
path (the same key the marks use). Only folders the owner explicitly set are in it; it is not a history of visited folders. A "Forget
folder layouts" button deletes the list. Paths on archives, search results and the Home page have no rule.

Why it matters beyond looks: a metadata column reads every file in the list, so it is switched on only where it is wanted; nothing is
read in the other folders.

Order of work: thumbnails first (a per-panel mode, remembered), then this rule store carrying columns and mode, then the metadata
columns on top of it.
