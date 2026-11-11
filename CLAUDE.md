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
The function list follows The Next Tool (Ebdac Software GmbH, discontinued 2007). Why the rule exists (the owner, 2026-11-11): Dossier is not a clone of TNT; TNT was an inspiration. We reimplement FUNCTIONS only, written in our own words. Never copy its code, help text, graphics or name, never decompile or disassemble its binaries, never translate its documentation, and never put its files in this repo. Whether to ask Ebdac for permission is an open question in the spec.

## Conventions (as in the Redactor apps)
- Sync (`git pull`) before editing or pushing.
- Slow operations show progress (`redactor_common` `run_with_progress()` / `run_busy()`); labels word-wrap.
- Secrets only through the system keyring (`redactor_common.core.secret_store`), never in config files.
- Guard Windows-only code with the platform module; keep the Linux build working.
- **Version bump at check-in (the user, 2026-10-19):** the build number is `YYYY-MM-DD#NN`, as in the Redactor apps (`dossier/core/version.py`, shown in the status line and Help > About). Any commit that changes real code runs `.venv/Scripts/python bump_version.py` and adds a matching `CHANGELOG.md` section in the same check-in, before pushing, without being asked. Never edit `APP_VERSION` by hand. A test fails when the CHANGELOG has no section for the current build.
- Edit code with the Edit/Write tools; tests are plain `pytest`, run in this repo's own venv: `.venv/Scripts/python -m pytest -q`, as the pre-push hook does. `python ../redactor-build-tools/devenv/venv_sync.py .` makes the venv at the redactor_common pin; never `pip install -r requirements.txt` into the shared Python (one repo's pin then breaks the others, 2026-11-04).

## Decided (the owner, 2026-10-20)
- **Undo is small on purpose.** Only renames, same-drive moves and new empty folders can be undone (`core/undo_log.py`). Never undo a copy by deleting what it made; an overwrite or a delete has no undo (older file in the recycle bin, or gone on a network drive). Do not grow it again without asking.
- **Network drives have no recycle bin.** Delete there is permanent and an overwrite deletes the older file; both say so in the confirmation (`drives.is_network_path`).
- **The window is split into mixins** (`gui/ops_queue.py`, `stall_log.py`, `going_places.py`, `folder_sizes.py`, `unpack.py`) and the one background-job helper `gui/background.py`. New background work uses `run_in_background`; do not hand-roll another holder/box/finished pattern. Sizes are formatted by `core/sizefmt.py`, a missing file is `vfs.stat_or_none`.
- **The window's thread never touches the disk.** Listing, notes, sizes, planning, unpacking and the status line's sizes all run on threads.

## Function keys (the owner, 2026-11-11, layout A)
Grouped by kind; Total Commander's history does not count ("TC is unwieldy for new users"). F5/F6 copy and move at once into the other panel; Ctrl+F5/F6 show the box first; Shift+F5/F6 plan a copy or a move for later; Ctrl+F3 opens the planned list; Ctrl+F7/F8 compare files and folders; Ctrl+F9-F12 sort by name, type, date, size. The planned operations (Shift+F5/F6, Ctrl+F3) are not built yet. Defaults in `core/fkey_config.py`.

## Planned operations (the owner, 2026-11-11; being decided point by point)
Shift+F5/F6 put a copy or move on a list to review and launch later, together with planned operations from other folders.
- A planned operation remembers the **intention** (which items, from which folder, to which folder), not a frozen file list: the plan is made again at launch from what is on disk then (option A, as the resume list in `core/queue_journal.py` does).
- The list is **kept on disk** (the settings folder) until an operation is run or removed; not opt-in, because the owner builds it on purpose (option A). A "Clear the list" button is the privacy switch.
- **Reusable copies** (raised by the owner the same day), option A: one list. A planned operation can be marked "keep after running"; it stays on the list, shows when it last ran and how it went, and runs again on request (re-planned, as every planned operation is). Kept entries have a name, so a command-line run (`dossier run <name>`) can come later without a second list.
- Open: what a rerun does with files already there (skip the same, newer only, or ask).

## Menus (the owner, 2026-11-05, after the menu review)
Each menu answers one question; a new command goes in the menu whose question it answers, at the end of the group it belongs to, never just at the bottom of Tools.
- **File**: what can I do to the files under the cursor (open, view, edit, rename, copy, move, new, dates, links, delete, properties).
- **Edit**: undo and the clipboard.
- **Mark**: which files are marked. The word is *mark*, never *select*.
- **View**: how a folder is shown (mode, sort, columns, layout, filter, notes, bars).
- **Go**: where am I and where to next (history, Home, the other panel, tabs, drives).
- **Tools**: the bigger jobs on many files, in submenus (Compare, Batch Rename, Archives, Checksums, Quarantine, Operations), and the terminals.
- **Network**: servers, shares, network drives, sharing.
- **Settings**: how Dossier looks (Appearance) and behaves. Explanations are tooltips, never greyed lines.
- **Help**: shortcuts, documentation, updates, About.
The right-click menu takes the label and the key hint of a menu-bar command from its action (`MenusMixin.bar_command`); give it its own text only when the clicked thing makes a better label ("Properties of This Folder"). `tests/test_menu_rules.py` holds the rules (headings, at most 16 entries a menu, no one-entry submenu, separators only between groups, no grey sentences, every shortcut in a menu, right-click = menu bar). The Redactor family lint (`redactor_common` `lint_menu_bar`) is not used: Dossier keeps Ctrl+S (Quick Filter), Ctrl+Shift+A (Unmark All), Ctrl+Shift+E and Ctrl+Shift+O.

## Decided (the owner, 2026-11-05, after the comparison review in `docs/comparison-review-2026-11-05.md`)
- **The yardstick is usability, not Total Commander:** can an ordinary user do the job without learning a system. FreeCommander XE and Just Manager are the owner's daily references; TC is "technically strong, but the usability is low".
- **No plugin system, ever** (neither Dossier's own nor TC's): plugins are "complicated and often outdated". A format or a source of files worth having is built in (`core/vfs.py`), with tests, in the normal menus. Spec A7 is dropped; V9 keeps only mapping a type to a program.
- **Core before new areas:** no new feature area (protocols, checkers, viewers, kinds of tags) until the functionality review's Yes cards are built and a release has had a week of real use. Fixes and decided cards (including the assistant cards 33 and 34) go on as normal.
- **No translation** (spec C10 not planned).
- **The README leads with what is unique** (a plan before every change, servers and the tailnet as folders, folder notes, the assistant that only proposes), then "everything built in, no plugins". Done at the next release, not before.

## Lanes between sessions
- A **local** session (the user's PC) owns everything that must be seen running: the GUI, the exe build, anything touching real folders, the Windows behaviour.
- A **cloud** session may own the Qt-free core and its tests, specs and CI files.
- Before building something not clearly in your lane, `git pull` and read the top of this file; if it is shared or unclear, add a line `Taking: <task> (local|cloud)` under "Open items" and push it first.

## Reuse map (where code already exists)
- `redactor_common` (github.com/Erlbon/redactor_common): `core/move_plan`, `undo`, `trash`, `rename_log`, `rename_pattern`, `case_conversion`, `field_order`, `secret_store`, `pipeline.commit_in_place`; `gui/sortable_table`, `table_columns`, `remembered_layout`, `command_palette`, `progress`, `media_preview`, `theme`.
- `pluteus` (github.com/Erlbon/pluteus, MIT): `ziputil.py` (zip listing with a bomb guard), `fs.py` (`natural_key`, `longpath`, `check_segment`), `markdown.py` (front matter parser), the notes format in `docs/notes-format.md`, `meta.py`/`mediainfo.py` for fast read-only tags.
- Veritas scanner `gui/csv_viewer_tab.py` (private repo): the CSV viewer to promote into `redactor_common` (generic table model, sort key, TSV copy, encoding fallback, row-checker hook), with delimiter sniffing and lazy loading added.
- Metadata cores: `epubredactor`, `cbzredactor`, `mp3redactor`, `videoredactor` (read the cores, do not copy).

## Releases (the owner, 2026-10-21)
- **0.4 is the first release.** A release has its own name, `RELEASE` in `dossier/core/version.py`; the owner decides the main numbers. **Since 2026-11-02 the tag is the build's tag** (`v2026-11-02-01`, as in the Redactor apps; 0.4 kept its old tag `v0.4`), because Help > Check for Updates (`redactor_common` `selfupdate`, the owner's choice) compares the newest release's tag with `APP_VERSION`. The tag is always this build's (the release tool makes it), and `tools/release_check.py` refuses a RELEASE number already released under another tag. The build number still says which check-in a program is made from (`Build 2026-10-21#20` in About, `--version` and the status line).
- **To release (the family's update framework since 2026-11-07, redactor_common `docs/update-framework.md`):** change `RELEASE` (when the owner says so), write `docs/releases/v<RELEASE>.md` (the notes, by hand: what is new since the last release and what to know), bump, check in and push as usual (the pre-push runs the tests), then on this PC: `.venv\Scripts\python.exe -m redactor_common.release --repo C:\Dev\dossier publish`. It runs `build_release.bat` (both builds, then `tools/release_check.py` tries them), writes `update-manifest.json`, tags, publishes a **pre-release** titled "Dossier <RELEASE> (build ...)" with the notes file, checks every asset, runs the **gate** (the previous release, installed for real in a scratch folder, updates itself to the new one and uninstalls cleanly; the same for the exe), and only then makes it Latest. Dossier must not be installed on the PC that runs the gate. The first framework release (after 0.7) needs `--first-framework-release`. GitHub Actions no longer releases (`release.yml` is gone: a pushed tag would have published a second, different build). Only the owner asks for a release.
- **Not in 0.4:** a Linux tarball (the sibling workflow's Linux job needs the Docker toolchain and its first run on Dossier is untried), code signing.
- **The installer (the owner, 2026-11-05):** `installer/dossier.iss` (Inno Setup 6), per user only (`%LOCALAPPDATA%\Programs\Dossier`, no administrator rights, no "for all users" choice). It ships the **one-folder build** (`DOSSIER_BUILD=folder`, starts in 0.9 s against 3.4 s for the one-file exe; option A of 2026-11-05). The release publishes `dossier-setup.exe` beside the one-file `dossier.exe`, and `update-manifest.json` names both. Each copy declares how it updates in an `update-channel` file: the one-file exe carries `windows-exe` inside (it swaps itself), the folder build gets `windows-zip` beside it, and the installer's copy of redactor_common's contract (`#include UpdateContract` at the end of the `.iss`, path passed by `build_installer.bat`) overwrites that with `windows-installer` and starts Dossier again after a silent update (`/relaunch=yes`, and 0.7's `/RESTARTAPP=1`). Keep both asset names: 0.7 copies still look for exactly those, which is how they reach the framework without a hand update. Silent: `/VERYSILENT /SUPPRESSMSGBOXES`, optional `/TASKS="desktopicon,addtopath"`. Local build: `build_exe.bat`, then `build_installer.bat` (or `build_release.bat` for both). `dossier --check-update` / `--update` (with `--result-file`) and `REDACTOR_CONFIG_DIR` are the framework's command line and scratch profile; a plain `dossier --version` stays the command line's. Keep the AppId (a test checks it against `pyproject.toml`).
- **No UPX** (the owner, 2026-11-07, as in the Redactor apps since 2026-10-30): Defender flags UPX-packed, unsigned exes as malware, so `dossier.spec` has `upx=False` and a test keeps it so. 0.7 (built by the old Actions workflow) was still packed: 54.4 MB; the first release without UPX is about 64 MB for that reason alone. Tell the owner when a release exe is 5 percent bigger than the one before for any other reason.

## Open items
- Icon sets are swappable (Settings > Appearance > Icon Set, user sets in the settings folder `icon-sets`). Tabler and Lucide draw the ebook and comic glyphs the other way round (Tabler `book` is open, Lucide `book` is closed): a set's manifest `map` fixes that per set; a Preferences page for per-file-type icon overrides is a possible later step (user, 2026-10-19).
- Later idea (user, 2026-10-19): a mix-and-match icon set, "developer's choice": each icon picked from whichever set draws it best (e.g. Tabler files, Lucide drives). Fits the manifest format if a `map` value may name another set (`lucide:hard-drive.svg`); not built, mind the rule that a set can never point outside its own folder when doing it (only built-in set ids).
- Push access to `redactor_common` for promoting shared modules.
- Generic hygiene rules (junk, unsafe names, empty folders) shared with the Ⅎolder Redactor through one Qt-free module (code review 2026-11-04, section 7).
- One shared tag writer (ComicInfo, ID3, zip rewrite) in `redactor_common`, used by Dossier, cbzredactor and mp3redactor (review 2026-11-04, section 6).
- Later (the owner, 2026-11-11): **outside tools offered for download, never bundled.** When a tool is not found, the installed Dossier may offer to download it, on the user's say-so; it is not shipped in the exe or the installer as standard. First candidates: `unar` (unpacks the old archives that are only named and listed today: ARC, ZOO, ACE, HA, StuffIt, Amiga DMS/LZX; option B of the old-archives choice, see `docs/reader-review-2026-11-11.md`) and `ffmpeg` (video frames for thumbnails, decode checks; used today only when found and switched on). Same idea as 7-Zip/NanaZip, which Dossier finds but does not ship. Not built. For unar the owner's **preferred route is to port its source** (MacPaw/XADMaster, LGPL, which may go into GPL Dossier with a credit) for the formats that matter, ARC and ZOO first, rather than rely on a binary: "to keep better control over integrated parts. If we do not trust compilated versions, building from source is better" (2026-11-11). The official Windows unar is a stale Cocotron cross-build (Chocolatey 1.8.1, 2019; upstream 1.10.8, 2023). Its source is published, so no decompiling is needed; the owner sees decompiling as the last resort when no source exists ("making the best out of a bad situation"). The clean-room rule above is about not cloning The Next Tool, not about decompiling in general.

## State
2026-11-04: releases 0.4 and 0.5 are out; the build is `dossier/core/version.py`. Built: the dual-pane window, operations with plan, progress, resume and small undo, viewers and the notepad, folder notes, archives (zip written), search, duplicates, compare and sync, batch rename, checksums, metadata read (and written for mp3 and cbz), tags on files, servers (SFTP, SCP, WebDAV, FTP, Google Drive, OPDS, Subsonic), the Tailnet list, network sharing (experimental, off by default), the Health window and `dossier check`, the command line and the MCP server. `CHANGELOG.md` has every build. Open work is in `docs/code-review-2026-11-04.md` (its Status section says what is fixed). Remote sources: each server has a read-only switch, on by default. Metadata order: mp3, cbz, then video (`docs/metadata-plan.md`).
