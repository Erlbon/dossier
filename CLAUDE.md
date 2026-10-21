# Dossier: working notes for Claude

The README says what this is; `docs/spec.md` says what it must do (requirement ids such as S3, F4, V5). This file holds the decisions behind them so a new session does not reopen what is settled. Keep it current when a decision changes.

## Decided (the user, 2026-10-19)
- **Program icon (the user, 2026-10-19): option C, a gold folder with a bold D cut out, on a dark tile.** Master `dossier/gui/appicon/dossier.svg`; after editing it run `python tools/make_icons.py` to regenerate the committed `dossier.ico` (seven sizes) and `dossier-256.png` (a test fails if they are out of date). Use the .ico for the PyInstaller exe.
- **Name:** Dossier. PyPI and domain checks are still to do.
- **Stack:** Python 3.10+ and PyQt6. Shared code comes from the user's `redactor_common` package, pinned to a git tag in `requirements.txt` (never `@main`). If something reusable is written here, promote it to `redactor_common` first, then bump the pin.
- **Licence:** GPL-3.0-or-later. Free and open source, never commercial.
- **Selection:** ONE selection shared by all windows (spec section 3). It is stored by path in `dossier/core/selection.py`, not in any window.
- **Platforms:** Windows primary, Linux (Debian 12+/Ubuntu 22.04+) a tested second. Tests run on both on every push. All OS-specific behaviour lives in `dossier/core/platform.py`; the rest of the core never tests `sys.platform`. Names are never assumed case-insensitive; undecodable file names are shown with a replacement mark and never crash a listing.
- **Architecture:** Qt-free core (`dossier/core`), the GUI and a later MCP server are thin front ends over it. Nothing in `core` imports Qt.
- **Looks:** no blue Norton Commander look; native chrome following the system theme. The visual target is the Design mockup the user approved (workspace board and viewers board); its palette borrows from pluteus's warm night theme (bg #0d0d0f, text #cfc8bd, accent #d9a05b).

## Decided (the user, 2026-10-19, after the review in `docs/review-and-plan.md`)
- **Windows:** separate top-level windows with native chrome, not an MDI workspace.
- **CORRECTION 2026-10-19 (the user): Dossier IS a dual-pane, orthodox (Norton Commander style) file commander.** Two panels side by side, F-key bar, command line, copy/move to the other panel, Tab switches panel, one shared selection. Commander mode (W4) is the CORE of 0.1, not a later extra. My first window mockups (single Explorer-style tree+list window) missed this and are void. Arrange modes (W3) and virtual desktops (W5) stay later. No Ctrl+Alt shortcuts.
- **Folder note behaves like a git repository's README (the user, 2026-10-19):** it sits BELOW the file listing inside the same panel scroll, as the last item of the list. You scroll down past the files to read it; it is NOT a pinned pane at the bottom of the window. No note, no row.
- **Faux Explorer view mode:** the user is open to adding one later as an extra mode; the dual-pane commander is what the app is for.
- **Version 0.1 scope:** as in section 5 of `docs/review-and-plan.md` (tree+list windows, shared selection, copy/move/delete/rename with plan and undo, folder note, text viewer, session restore). Everything else waits for a week of real use.
- **pluteus reuse:** pluteus will be made public soon, so its MIT code may be reused with the notice kept; promote shared pieces to `redactor_common` where sensible.
- **Name:** keep Dossier; ship via GitHub releases (exe, tarball), not PyPI. Domain and trademark check still to do.
- **Ebdac permission:** not blocking; the clean-room rule stands.

## Clean-room rule (important)
The function list follows The Next Tool (Ebdac Software GmbH, discontinued 2007). We reimplement FUNCTIONS only, written in our own words. Never copy its code, help text, graphics or name, never decompile or disassemble its binaries, never translate its documentation, and never put its files in this repo. Whether to ask Ebdac for permission is an open question in the spec.

## Conventions (as in the Redactor apps)
- Sync (`git pull`) before editing or pushing.
- Slow operations show progress (`redactor_common` `run_with_progress()` / `run_busy()`); labels word-wrap.
- Secrets only through the system keyring (`redactor_common.core.secret_store`), never in config files.
- Guard Windows-only code with the platform module; keep the Linux build working.
- **Version bump at check-in (the user, 2026-10-19):** the build number is `YYYY-MM-DD#NN`, as in the Redactor apps (`dossier/core/version.py`, shown in the status line and Help > About). Any commit that changes real code runs `python bump_version.py` and adds a matching `CHANGELOG.md` section in the same check-in, before pushing, without being asked. Never edit `APP_VERSION` by hand. A test fails when the CHANGELOG has no section for the current build.
- Edit code with the Edit/Write tools; tests are plain `pytest` (`python -m pytest -q`).

## Decided (the owner, 2026-10-20)
- **Undo is small on purpose.** Only renames, same-drive moves and new empty folders can be undone (`core/undo_log.py`). Never undo a copy by deleting what it made; an overwrite or a delete has no undo (older file in the recycle bin, or gone on a network drive). Do not grow it again without asking.
- **Network drives have no recycle bin.** Delete there is permanent and an overwrite deletes the older file; both say so in the confirmation (`drives.is_network_path`).
- **The window is split into mixins** (`gui/ops_queue.py`, `stall_log.py`, `going_places.py`, `folder_sizes.py`, `unpack.py`) and the one background-job helper `gui/background.py`. New background work uses `run_in_background`; do not hand-roll another holder/box/finished pattern. Sizes are formatted by `core/sizefmt.py`, a missing file is `vfs.stat_or_none`.
- **The window's thread never touches the disk.** Listing, notes, sizes, planning, unpacking and the status line's sizes all run on threads.

## Lanes between sessions
- A **local** session (the user's PC) owns everything that must be seen running: the GUI, the exe build, anything touching real folders, the Windows behaviour.
- A **cloud** session may own the Qt-free core and its tests, specs and CI files.
- Before building something not clearly in your lane, `git pull` and read the top of this file; if it is shared or unclear, add a line `Taking: <task> (local|cloud)` under "Open items" and push it first.

## Reuse map (where code already exists)
- `redactor_common` (github.com/Erlbon/redactor_common): `core/move_plan`, `undo`, `trash`, `rename_log`, `rename_pattern`, `case_conversion`, `field_order`, `secret_store`, `pipeline.commit_in_place`; `gui/sortable_table`, `table_columns`, `remembered_layout`, `command_palette`, `progress`, `media_preview`, `theme`.
- `pluteus` (github.com/Erlbon/pluteus, MIT): `ziputil.py` (zip listing with a bomb guard), `fs.py` (`natural_key`, `longpath`, `check_segment`), `markdown.py` (front matter parser), the notes format in `docs/notes-format.md`, `meta.py`/`mediainfo.py` for fast read-only tags.
- Veritas scanner `gui/csv_viewer_tab.py` (private repo): the CSV viewer to promote into `redactor_common` (generic table model, sort key, TSV copy, encoding fallback, row-checker hook), with delimiter sniffing and lazy loading added.
- Metadata cores: `epubredactor`, `cbzredactor`, `mp3redactor`, `videoredactor` (read the cores, do not copy).

## Open items
- Icon sets are swappable (Settings > Appearance > Icon Set, user sets in the settings folder `icon-sets`). Tabler and Lucide draw the ebook and comic glyphs the other way round (Tabler `book` is open, Lucide `book` is closed): a set's manifest `map` fixes that per set; a Preferences page for per-file-type icon overrides is a possible later step (user, 2026-10-19).
- Later idea (user, 2026-10-19): a mix-and-match icon set, "developer's choice": each icon picked from whichever set draws it best (e.g. Tabler files, Lucide drives). Fits the manifest format if a `map` value may name another set (`lucide:hard-drive.svg`); not built, mind the rule that a set can never point outside its own folder when doing it (only built-in set ids).
- Push access to `redactor_common` for promoting shared modules.
- Which metadata format comes first (EPUB, CBZ, MP3, video).
- Remote sources read-only until phase 2 is stable?
- PyInstaller spec and release workflow (copy the pattern from `cbzredactor/.github/workflows/release.yml`).

## State
Done 2026-10-19: spec (`docs/spec.md`), core skeleton with tests (`platform`, `vfs`, `selection`), CI for Windows and Ubuntu. Not started: operations with plan/undo, any GUI, viewers, notes, metadata, remote, MCP. Next in build order: operations with plan, progress and undo; then the GUI shell on Windows.
