# Fit Columns to Panel (built 2026-11-18#05)

Decided by the owner on 2026-11-18: option A. Built in build 2026-11-18#05, with the switch in the header menu too (his option A for step 3).

## The problem

The right-most columns are hard to resize. In `panel.py` the header has `setStretchLastSection(True)`, so the last column
always fills the panel and has no right edge to grab. When the columns together are wider than the panel, the right ones sit
off-screen behind a horizontal scrollbar. Double-clicking a header divider already fits one column to its contents (Qt's own
behaviour), but that is one column at a time.

## What was chosen (option A)

An on/off switch, **Fit Columns to Panel**, on by default:

- On: all columns share the panel's width, with no horizontal scrollbar while they fit. The Name column takes the slack:
  widening another column takes the room from Name, so every edge stays on screen.
- Off: as today (last column stretches, scrollbar when too wide).
- One choice for both panels, saved in the settings file (suggested key `view/fit_columns`, `"true"`/`"false"`).

Rejected: B, a one-off "Size Columns to Contents" command (tidies once, the problem comes back).

## How to build it

1. **Panel** (`dossier/gui/panel.py`): add `fit_columns = True` and a method `apply_fit(on)`:
   - on: `header.setStretchLastSection(False)`; Name's section (`column_index("name")`) gets `QHeaderView.ResizeMode.Stretch`,
     every other section stays `Interactive`; `table.setHorizontalScrollBarPolicy(ScrollBarAsNeeded)` stays, so if the other
     columns alone are wider than the panel, the scrollbar comes back rather than columns vanishing.
   - off: Name back to `Interactive` with its current width, `setStretchLastSection(True)`.
   - Name keeps a minimum width (for example `header.setMinimumSectionSize` or a check in `sectionResized`) so it cannot be
     squeezed to nothing.
   - The thumbnail view (`icons`) has no columns: nothing to do there.
   - Home page: keeps its own three columns. Check that Stretch on section 0 still looks right there (Name is column 0 on Home
     too); if not, apply fit only when `not self.is_home` (in `_apply_columns`).
2. **Window**: a checkable `QAction` "Fit Columns to Panel" in the View menu, next to Columns... (`menus.py`), with
   `fit_columns_on()` / `set_fit_columns(on)` in the same style as `keep_place_on()` / `set_keep_place()` (build 2026-11-18#02):
   read the setting, apply to `self.left` and `self.right`, say it in the status line.
3. **Header right-click menu** (`dossier/gui/columns.py` `show_column_menu`): the shared menu is redactor_common's
   `show_column_header_context_menu`. Its `top_actions` takes `(label, callback, enabled)`, with no checkable entry.
   Either add an optional fourth item `checked` there (redactor_common change: bump, tag, then pin the new tag in Dossier, as
   the family rule says) or leave the header menu alone and have the switch only in the View menu. Ask the owner which, in
   chat (one decision).
4. **Folder layouts**: the switch is global, not part of a folder layout rule. Make sure `apply_column_layout()` (called on
   every folder change and when a layout rule applies) does not undo the resize modes: call `apply_fit` at its end.
5. **Tests** (`tests/test_columns.py`): with a fixed panel width offscreen: on by default, the header's total length is no
   wider than the viewport and there is no horizontal scrollbar; widening Size narrows Name; switching off restores
   stretch-last; the choice survives a new `MainWindow` on the same settings file.
6. Version bump (`python bump_version.py`), CHANGELOG section, syntax check, tests with their real exit code (no pipe into
   `tail`), local commit; push only when the owner says.

## Facts found while planning

- Column widths are not saved today: each start uses `DEFAULT_WIDTHS` from `dossier/core/columns.py`. Not part of this plan.
