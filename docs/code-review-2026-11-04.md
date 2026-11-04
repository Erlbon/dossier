# Code review, 2026-11-04 (build 2026-11-03#04, commit eb80478)

A full read-only review, starting from the usability review of the same day (`C:\Temp\Claude\usability-review\05-dossier.md`). Five reviewers each took one area (file operations, freezes and tests, sharing/secrets/MCP, tag writer and Health, structure and docs), and Claude re-read the code behind the top findings. Nothing in the program was changed.

- **Reproduced** means the failure was run and seen, against Dossier's own code in a scratch folder.
- **By reading** means the code path was traced but not run.
- **Sizes** are small (S), medium (M) or large (L).

Order: data loss and wrong files first, then security, then freezes, then correctness, tests, clean-up and docs.

## Summary

- Five ways to lose a file were found. Three were reproduced:
  - a junction moved to another drive empties its target;
  - a folder moved onto itself through a second path name is deleted;
  - a failed verify after an overwrite leaves nothing.
- The other two:
  - the Recycle Bin silently deletes for good on USB sticks, because pywin32 is missing;
  - moves to another drive delete the source before the copy is flushed or verified.
- **Sharing has one real injection hole.** A folder name containing a curly quote (`’`) breaks out of the elevated PowerShell string, and its commands run as administrator after UAC. It should go behind an Experimental switch until that is fixed and the owner has run the flow once.
- **The biggest freeze is new.** Choosing Overwrite in the conflict dialog is quadratic: 250 conflicts froze the window for 20 s and 500 for 57 s (reproduced). Several plans still run on the window's thread: sync, delete, rename, undo, opening files and New Folder.
- **The flaky tests have one main cause.** Tests read the panel right after `set_folder`, but a listing only gets `NAV_BUDGET = 0.15` s before the panel goes "pending". Setting the budget to 0 made 36 of 100 tests fail in five files, including `test_queue`.
- **The tag writer differs from the Redactors' in about 15 places** and has two bugs that can break a file. Both should move to one shared module in `redactor_common`.
- **Health can propose deleting real things.** It treats `desktop.ini` as junk, which would empty Windows shell folders. "Fix" runs delete plans without a preview and without the network warning.
- All 17 findings of the 2026-10-20 review were marked fixed, and all 19 of its "still open" features have since been built. Three of those fixes are only partial (see the last section).

---

## 1. Data loss and wrong files

| # | What | Where | Status | Size |
|---|---|---|---|---|
| D1 | A junction or folder symlink moved to another drive empties the folder it points to | `dossier/core/ops.py:402-420`, `:826-836` | Reproduced | S |
| D2 | "Move to the Recycle Bin" deletes permanently, without a word, where there is no bin | `dossier/core/ops.py:501-507`, `requirements.txt` | By reading send2trash; backend confirmed | S-M |
| D3 | A folder moved onto itself through a second path is deleted after Overwrite | `dossier/core/ops.py:233`, `:822-828` | Reproduced | S |
| D4 | A failed verify after an overwrite leaves the destination empty | `dossier/core/ops.py:861-873` | Reproduced | S-M |
| D5 | A move to another drive removes the source before the copy is flushed; moves are never verified | `dossier/core/transfer.py:73-78`, `ops.py:773-776`, `:800`, `:865` | By reading | M |
| D6 | Writing a ComicInfo value with a control character leaves the cbz with broken XML; the old file is already in the bin, and the batch stops | `dossier/core/metawrite.py:115-130`, `:342-349`, `:368-371` | Reproduced | S |
| D7 | Every zip rewrite garbles entry names that were stored without the UTF-8 flag (`Märchen.jpg` becomes `M├ñrchen.jpg`) | `dossier/core/zipwrite.py:250` | Reproduced | M |
| D8 | Health: `desktop.ini` counts as junk, and a folder holding only `desktop.ini` counts as empty; both are offered for deletion | `dossier/core/health_rules.py:15`, `:43-46`, `:142-147` | Reproduced | S |
| D9 | Health "Fix" runs delete plans with no preview, so the network "permanent" warning is never shown | `dossier/gui/health_window.py:359-370`, `main_window.py:889-910` | Confirmed by reading | S |
| D10 | Health deletes empty folders inside `.git` (`refs/heads`, `refs/tags` after `git gc`) | `dossier/core/health_rules.py:142-147` | By reading | S |
| D11 | Continuing a remembered queue can overwrite a file edited since, and runs deletes again without a confirmation | `dossier/core/queue_journal.py:72-77`, `:111-131`, `dossier/gui/queue_resume.py:85-95` | By reading | S |
| D12 | The "deleted permanently on a network drive" warning drops out of the summary after 8 other warnings; paste and drag-and-drop show no confirmation at all | `dossier/core/ops.py:138-142`, `dossier/gui/main_window.py:885-886`, `:984-990`, `dossier/gui/drop_handler.py:43-45` | By reading | S |
| D13 | Move into Zip from a network drive says the originals go to the bin; they are deleted for good | `dossier/gui/zip_edit.py:99-100`, `:121-124` | By reading | S |
| D14 | A case-only rename in a case-sensitive folder (WSL, or NTFS set case-sensitive) replaces the other file | `dossier/core/ops.py:450-453`, `dossier/core/vfs.py:182-187` | By reading | S |
| D15 | F7, New File, paste-as-file and New Link write into the program's working folder while a panel's first listing is pending or has failed | `dossier/gui/main_window.py:1033` (and the other `fs.join(self.active.path, ...)`), `:1105` | Reproduced by accident (made `C:\Dev\dossier\newdir`) | S |
| D16 | `FINISH_MOVE` compares sizes only, so a source changed in place after its copy loses that change | `dossier/core/ops.py:822-824` | By reading | S |
| D17 | `dossier check --delete-junk` also deletes empty folders and dead links; links to an unplugged drive count as dead | `dossier/cli/commands.py:139`, `:470-471`, `dossier/core/health_rules.py:87` | By reading | S |

**D1.**
- **Scenario:** `src\link` is a junction to `precious\`. Moving `link` to another drive gives a plan that copies `precious`' files and then `FINISH_MOVE` removes them. `precious\` is left empty and the link is gone.
- **Cause:** `plan_copy` checks `e.is_link`, but `plan_move` does not. The stat follows the link, so `e.is_dir` is true.
- **Linux:** a symlink to a folder on another filesystem behaves the same.
- **Fix:** block a top-level link moved to another drive ("a link cannot be moved to another drive"). On the same drive it is a plain rename.

**D2.**
- **Cause:** pywin32 is not in `requirements.txt` or the release build, so `send2trash` uses `send2trash.win.legacy` (checked on this PC). That backend calls `SHFileOperation` with "allow undo" and "no confirmation". Windows then deletes for good any item it cannot recycle, and says nothing.
- **Where it happens:**
  - **certain:** USB sticks (removable drives have no bin);
  - **probable:** WinFsp/rclone drive letters, files too big for the bin, and drives with the bin switched off.
- **Scope:** this applies to delete and also to the older file an overwrite replaces, the zip swap and metadata writes.
- **Fix:**
  - Bundle pywin32. The modern backend refuses an item that cannot be recycled, so the delete fails instead of destroying the file.
  - Treat removable drives like network drives in the confirmation (`drives.is_network_path`, or a new `has_recycle_bin`).

**D3.**
- **Scenario:** one panel is at `\\nas\share\docs`, the other at `Z:\docs` (Z: is mapped to `\\nas\share`). The same happens with a subst drive.
- **What happens:**
  1. Moving a folder between the two panels counts as another drive, so it becomes copy plus `FINISH_MOVE`.
  2. Every file conflicts with itself, shown as identical.
  3. The user picks Overwrite, so each file is copied onto itself.
  4. `FINISH_MOVE` then removes the source, which is the only copy.
- **Fix:**
  - In `_placed`, compare file identity (`os.path.samefile`) and report "same item".
  - In `_finish_move`, never remove when `samefile(src, dst)`.

**D4.**
- **What happens:** `copy_file` has already swapped the new file in and sent the old one to the bin (or deleted it, on a network drive). Then `VerifyFailed` removes the new copy too.
- **Fix:** verify the `.dossier-part` before the swap.

**D5.**
- **Single files:** `move_item` across drives checks the size, then removes the source. The copy is never flushed, and never verified even with Verify ticked (`ops.py:865` verifies COPY steps only).
- **Folders:** `FINISH_MOVE` runs before `_flush_pass`.
- **Risk:** the stick is pulled or the power goes, and the source is already gone.
- **Fix:** flush, and verify when the setting is on, before removing the source.

**D6.**
- **Cause:** `check_value` only refuses `\x00`. The read-back check runs after `zipwrite.rewrite` has swapped the file in. Its `ET.ParseError` is not an `OSError`, so `apply` does not catch it and the rest of the batch is lost.
- **Fix:** parse the new XML before the swap, and use `redactor_common.cli.values.check_text`.

**D7.**
- **Cause:** `ZipInfo(name)` is built from zipfile's cp437 reading of a name that was really stored as UTF-8 or Shift-JIS bytes without the UTF-8 flag. The original bytes are lost.
- **Scope:** every zip edit (cbz, epub, docx).
- **Fix:** cbzredactor already solves this (`core/zip_names.py` `RawNameInfo`, used in `zip_rewrite.py:272`). Promote it (see section 6).

**D8.** Run on a user profile, this proposes deleting `Music`, `Videos`, `Favorites\Links`, `Startup` and the like, with their localized names and icons. **Fix:** take `desktop.ini` out of `JUNK_NAMES`, and out of the "empty" test.

**D9.**
- **Cause:** `_planned` shows `PlanPreview` only when Preview was pressed or a plan is blocking. `_settle` asks only about conflicts.
- **Effect:** junk, empty folders and dead links on a share are deleted permanently without the confirmation CLAUDE.md requires.
- **Fix:** always show the plan for delete fixes, or at least the network warning.

**D11.** This only applies when "remember unfinished operations" is on.
- **What happens:** the journal stores `overwrite=True`, and the rebuilt plan has no conflicts, so `_settle` runs it at once. A destination the user edited after the crash is overwritten, and a sync's delete steps run again on whatever is at those paths now.
- **Fix:** store the destination's size and time, re-raise a conflict if either changed, and confirm before continuing.

---

## 2. Security

| # | What | Where | Status | Size |
|---|---|---|---|---|
| S1 | **Command injection into the elevated PowerShell** through a folder name with a curly quote | `dossier/core/sharing.py:519-521` (used at `:548`, `:560-566`, `:571`, `:582`; and unelevated at `:290`) | Reproduced (parsed with PowerShell's parser, not run) | S |
| S2 | The MCP scope check opens UNC paths before refusing them, which leaks the user's NTLM hash to any host the model names | `dossier/assistant/scope.py:33` | Reproduced (a 21 s wait on `\\192.0.2.1\share\x`, then Denied) | S |
| S3 | Renaming a share drops its deny entries, so a denied user gains access | `dossier/core/sharing.py:556-558` | Reproduced (generated script) | S |
| S4 | Linux: "Everyone" sets `guest ok = yes`, which allows anonymous access with no password (on Windows, Everyone means signed-in users) | `dossier/core/sharing.py:664` | By reading | S |
| S5 | The whole-drive confirmation names the drive but not who gets access; there is no stronger warning for the system drive or for Change/Full to Everyone | `dossier/gui/sharing.py:471-474` | By reading | S |
| S6 | A saved server's user name may start with `-`, so `-oProxyCommand=...` becomes an ssh option and runs on connect | `dossier/core/sshlink.py:219-221`, `dossier/core/servers.py:94` | argv reproduced; ssh not run | S |
| S7 | `powershell.exe` and `net` are started by bare name, so the elevated one could be a planted copy found first | `dossier/core/sharing.py:576`, `:624` | By reading | S |
| S8 | The Subsonic token and salt appear in error messages (`FileNotFoundError.filename` holds the full `/rest/download.view?u=&t=&s=`) and can be replayed | `dossier/core/davclient.py:305-310`, `subsonicclient.py:120`, `catalogclient.py:197` | By reading | S |
| S9 | FTPS with a pinned certificate: only the control connection is checked; data connections accept any certificate | `dossier/core/ftpclient.py:52` | By reading | S |
| S10 | The assistant may change the shared selection without `allow_file_changes`; a later F8 by the owner deletes what the model chose | `dossier/assistant/tools.py` (selection tools), `dossier/gui/assistant.py:225` | By reading | S |
| S11 | The elevated script reports errors through a file in `%TEMP%`; a 120 s timeout is reported as failure while the script may still be running | `dossier/core/sharing.py:589-607`, `:634` | By reading | S-M |

**S1.**
- **Cause:** `ps_quote` doubles only the ASCII `'`. PowerShell also ends a single-quoted string at U+2018, U+2019, U+201A and U+201B.
- **Attack:** a folder from a download, an unpacked zip or a USB stick is named `a’; <cmd>; New-SmbShare -Name b -Path ’x`. The owner picks Share... and approves UAC, and `<cmd>` runs as administrator.
- **Also affected:**
  - A `%TEMP%` with `’` in it (a user name like O’Brien) breaks every share action.
  - `dossier/core/scripts.py:34` has the same quoting for Enter on a `.ps1`. It runs unelevated, so it is low risk.
- **Fix:** pass each value as base64 and decode it inside the script, or escape all four quote characters. Add a test with `’`.

**S2.**
- **Cause:** `os.path.realpath` runs before the root comparison, so Windows connects to the host (SMB or WebDAV) before the path is refused.
- **Fix:** refuse `\\` and `//` paths, and drives no root lives on, by text before calling `realpath`.

**Sharing as a whole.** Put it behind Settings > Experimental, off by default, until both of these are done:
1. S1 is fixed.
2. The owner has run the real flow once on Windows: create, change, rename, stop, a cancelled UAC prompt, a failure halfway, and ideally a non-English Windows (the "Jeder" path).

Also checked and fine:
- A failure halfway: creating a share is one `New-SmbShare` with its permissions, so a share never exists without them. A same-name change revokes first and grants after, so a failure leaves less access, not more.
- Stop Sharing removes the exact listed name.
- Default permission: Everyone, read only.
- `check_name` blocks share-name metacharacters.
- `-EncodedCommand` is used and no script file is written.
- Remote share names never reach PowerShell.
- The IPC$ login uses Windows' own prompt; Dossier never sees the password.

**Secrets and remote access: fine apart from S6, S8 and S9.**
- Passwords, the Google client secret and the refresh token are in the keyring only. `dossier.ini` holds `user@host`, and a password in a pasted URL is dropped.
- The SSH password goes through the askpass environment variable, never the command line. Host keys are strict, with Dossier's own known_hosts and a warning on change.
- WebDAV, OPDS, catalogues and Google verify TLS. `CERT_NONE` is used only with a pinned fingerprint, which is checked first.
- FTPS has no fallback to plain FTP, and plain FTP is labelled "not encrypted".
- Subsonic sends token plus salt, never the password.
- OAuth: 127.0.0.1 only, PKCE S256, `state` checked.
- The slowness log records key names only, never typed text.
- Convention: secrets go through `keyring` directly (`dossier/core/servers.py:193-216`), not `redactor_common.core.secret_store` as CLAUDE.md asks.

**MCP: fine apart from S2 and S10.**
- Off by default, and `allow_file_changes` is off by default.
- The model cannot approve its own plan. The window reloads the settings, re-checks the paths, rebuilds the plan and shows a modal Run/Reject. The model's reason is shown as "not checked".
- These are all refused (reproduced): `..`, a junction inside a root pointing outside, a sibling folder like `root2`, `C:foo`, `\foo`, `\\?\` and `\\.\`.
- `read_text` is capped at 1 MB, and `://` paths are refused, so saved servers cannot be reached.

---

## 3. Freezes

| # | What | Where | Status | Size |
|---|---|---|---|---|
| F1 | Choosing Overwrite for many conflicts is quadratic: `resolve_each` calls `resolve` once per conflict, and each runs `is_network_path` (one `list_drives`, 0.36 ms) for every overwrite step. It runs on the window's thread | `dossier/core/ops.py:94-100`, `:139`, `dossier/gui/main_window.py:902` | Reproduced: 250 conflicts 20 s, 500 conflicts 57 s | S |
| F2 | Compare > Synchronize plans on the window's thread (walks, stats, resolve, `plan_delete`) | `dossier/gui/compare_folders.py:260` | By reading | S |
| F3 | Disconnect, Remove server and closing the window hang while a request is stuck: SFTP/SCP up to about 60 s (closing a pipe another thread reads), WebDAV/FTP up to about 60 s (`close()` waits for the request's lock) | `dossier/core/sshlink.py:318`, `davclient.py:201`, `ftpclient.py:255` | Pipe-close behaviour reproduced in plain Python | M |
| F4 | Closing the window waits for a running copy (`runner.shutdown(wait=True)`). With "ask on error" on, a cancelled job still asks, and the two threads wait on each other for ever | `dossier/gui/main_window.py:1158`, `dossier/core/ops.py:744`, `dossier/gui/ops_queue.py:199-200` | By reading | S |
| F5 | Ctrl+Z undo runs on the window's thread, at four calls per step: 2,000 renames on a NAS take 10-40 s, and on SFTP about 160 s | `dossier/gui/main_window.py:1081` | By reading | S |
| F6 | F8 delete, F2 rename, batch rename and Move into Zip plan on the window's thread (two stats and one `list_drives` per item) | `dossier/gui/main_window.py:1007`, `:1057`, `dossier/gui/batch_rename.py:89`, `dossier/gui/zip_edit.py:122` | By reading | S |
| F7 | Opening files touches the disk on the window's thread: F3 stats every target, F4 stats and loads up to 10 MB, and Notepad save is synchronous. Enter on a picture lists the whole folder (1-3 s on a 20,000-photo share). Enter reads the file head for the view mode | `dossier/gui/main_window.py:394`, `:407`, `:429`, `:449`, `dossier/gui/notepad.py:516`, `dossier/gui/open_files.py:82`, `dossier/gui/unpack.py:26` | By reading | M |
| F8 | F7 New Folder calls `fs.mkdir` on the window's thread, 30-60 s on a hung server | `dossier/gui/main_window.py:1035` | Confirmed by reading | S |
| F9 | Dragging a server or archive file out to Explorer downloads it (up to 64 MB) inside the drop, on the window's thread | `dossier/gui/dragdrop.py:34`, `dossier/gui/panel.py:1271` | By reading | M-L |
| F10 | Enter on an archive-named file and Ctrl+PageDown open the file to check its format, on the window's thread | `dossier/gui/panel.py:1643`, `:1661` | Confirmed by reading | S |
| F11 | Low: network auto-refresh adds watches from the window's thread (default off); share login (`WNetAddConnection3`) connects there; `openUrl` for files on shares; the dragged image is decoded on every mouse move | `dossier/gui/auto_refresh.py:84`, `dossier/core/mounting.py:125`, `dossier/gui/panel.py:282` | By reading | S-M |

**F1:** read the drive list once per plan and count the network overwrites once, after the loop. This is the cheapest big win in the review.

**F2, F5, F6 and F8:** use the existing `_plan_in_background` or `run_in_background`.

**F7:** one background "prepare to open" job.

**Remote timeouts as they are:**

| Client | Timeout | Worst case per call |
|---|---|---|
| WebDAV, OPDS, Subsonic, catalogues | 30 s, retried once | about 60 s |
| FTP | 30 s | can double with reconnect |
| Google Drive | 30 s × 4 tries + backoff | about 127 s |
| SFTP and SCP | no socket timeout; ssh ServerAlive 15 s × 4 | about 60 s |

`shellclient.run(timeout=120)` is checked only between reads, so it never fires while a read is blocked.

**Fine:**
- Listing and notes run on a thread (0.15 s budget, Esc cancels).
- Free space, drive lights and folder sizes run on threads.
- Another computer's share list is read on the listing thread.
- Properties, thumbnails, tags and metadata columns run on threads, and so do every connect flow and the shell menu.
- Startup with a dead share does not freeze, but see D15.

---

## 4. Correctness

| # | What | Where | Size |
|---|---|---|---|
| C1 | Comic tag values are written unstripped but read back stripped: `dossier tag --set "Series= X"` replaces the file, then reports a failure | `dossier/core/metawrite.py:327`, `:348`, `dossier/cli/tagging.py:32` | S |
| C2 | `plan` crashes on a superscript digit (`"²".isdigit()` is true, `int("²")` raises) | `dossier/core/metawrite.py:122-126` | S |
| C3 | A `MutagenError` (not an `OSError`) escapes `apply` and stops the batch; the file itself is safe | `dossier/core/metawrite.py:368-371` | S |
| C4 | ID3v2.3 files are silently upgraded to v2.4 (TYER becomes TDRC); some car stereos do not read 2.4. mp3redactor keeps the version | `dossier/core/metawrite.py:286` | S |
| C5 | `dossier check --deep` crashes on a Deflate64 zip (Explorer makes these) or an encrypted one: `NotImplementedError`/`RuntimeError` are not caught, and the whole run ends | `dossier/core/health_rules.py:107-127`, `dossier/core/health.py:134-137` | S |
| C6 | Health false positives: `zero_byte` flags `py.typed`, `.nojekyll`, `_SUCCESS` and `*.lock`; name rules skip folders, so a folder ending in a dot or space is never reported; `sidecar_orphans` flags `movie.nfo`, `tvshow.nfo` and `*.forced.srt` | `dossier/core/health_rules.py`, `dossier/core/health.py:126-128` | S |
| C7 | A continued cross-drive folder move skips files copied before the crash as identical, so their originals stay, and it still says Done | `dossier/core/ops.py` (`skip_identical` with `FINISH_MOVE`) | S |
| C8 | Zip edit temp names (`.dossier-part`, `.dossier-old`) are not shortened like `transfer.side_name`, and have no long-path prefix, so edits fail near 255 characters or past 260 (the original is safe) | `dossier/core/zipwrite.py:221`, `:304` | S |
| C9 | `Swap.rollback` fails silently; the error does not say the old file may be left as `.dossier-old` | `dossier/core/transfer.py:116-122` | S |
| C10 | A late listing failure at startup leaves the panel empty rather than going Home (see D15) | `dossier/gui/main_window.py:1105` | S |

---

## 5. Tests (the "1 run in 4" flake)

| # | What | Where | Size |
|---|---|---|---|
| T1 | **Main cause.** Tests call `refresh()` or `set_folder()` and read the model at once. If the listing thread needs more than `NAV_BUDGET = 0.15` s (antivirus, load), the panel goes pending and the test sees the old rows. With the budget set to 0, `test_queue` failed 2 of 4 runs, and 36 of 100 tests failed in `test_gui_commander`, `test_marking`, `test_context_menu`, `test_dragdrop` and `test_thread_fixes` | `dossier/gui/panel.py:465`, `:1051`; the tests above, plus `test_planning_background` and `test_navigation` | S |
| T2 | **Whole-run abort (0xC0000409).** There is no `sys.excepthook` in the tests, so any exception in a Qt callback makes PyQt6 call `qFatal`. These callbacks assert on `activeModalWidget()` with no guard: `test_fkeys.py:130`, `:166`, `test_frost.py:88-114`, `test_glass_viewer.py:243-252`, `test_owned_dialog.py:126-133`. A dialog that never opens leaves a timer that fires in a later test. Product code: `QTimer.singleShot(0, lambda: self.refresh_tailnet(...))` without an owner | `dossier/gui/tailnet.py:34` | S |
| T3 | Fixed waits for thread results: `test_glass_viewer` `qWait(300)`, `test_notepad_markdown` 450 ms against a 300 ms delay, and the fade tests `FADE_MS + 150` | as named | S |
| T4 | `test_auto_refresh::test_a_burst_of_changes_is_one_or_two_refreshes_not_one_for_each` depends on a 150 ms debounce | | S |
| T5 | `test_thread_fixes::test_shutdown_can_drop_the_jobs_that_have_not_started` uses `sleep(0.1)` to assume the first job has started | | S |
| T6 | Wall-clock assertions: `test_parallel_copy::test_parallel_is_clearly_faster...`, `test_stallwatch::test_the_real_thread_catches_a_real_stall...`, and `test_navigation` (under 0.5 s) | | S |
| T7 | `QT_QPA_PLATFORM=offscreen` is set in only some test modules, so whether a run is offscreen depends on what is collected; single-file runs steal focus | `tests/conftest.py` | S |
| T8 | `test_shellmenu::test_the_whole_show_path...` sends Escape to any `#32768` pop-up menu on the desktop, the owner's own included | | S |
| T9 | `tests/helpers.wait_planned` returns silently on timeout, so a slow plan later fails with a confusing assertion | | S |

**Fix for T1 and T2:**
- an autouse fixture that sets `panel.NAV_BUDGET` to about 10 s, with only the slow-path tests overriding it;
- a `wait_listed(panel)` helper;
- a conftest excepthook that fails the current test instead of aborting the run.

That should remove most of the "1 in 4".

---

## 6. The duplicate tag writer (usability finding 2)

`dossier/core/metawrite.py` and `dossier/core/zipwrite.py` against `C:\Dev\cbzredactor\core\comicinfo.py` (with `cbz_file.py`, `zip_rewrite.py` and `zip_names.py`) and `C:\Dev\mp3redactor\core\tag_writer.py`. The bugs are D6, D7 and C1 to C4 above. These are the places where the two would write the same file differently:

**ComicInfo.xml**

| Aspect | Dossier | cbzredactor | Should win |
|---|---|---|---|
| xsi/xsd namespace declarations | Dropped (a new file gets a bare `<ComicInfo>`), `metawrite.py:311-329` | Always declared, `comicinfo.py:255` | Redactor |
| Root attributes (`xsi:noNamespaceSchemaLocation`) | Kept | Dropped | Dossier |
| Element order | Only new elements go to their schema slot; the rest stay put | Rebuilt in schema order; unknown elements go before CommunityRating, `comicinfo.py:92-109`, `:269-272` | Redactor's order, Dossier's minimal diff |
| Empty elements | Only the cleared one is removed | All removed on save, `comicinfo.py:260-262` | Redactor |
| Whitespace in values | Kept (C1) | Stripped | Redactor |
| Number fields | Count/Volume/Year/Month/Day must be digits, Month and Day range-checked | No check in the writer | Dossier, with `is_ascii_number` |
| Declaration and final newline | `encoding="utf-8"`, no newline | lxml `encoding='utf-8'`, newline | Either; pick one |
| Pretty-printing | `ET.indent` re-indents everything, `<Pages>` too | lxml `pretty_print`; extra elements keep their whitespace | Redactor |
| PageCount | Untouched | Recomputed on every save, `cbz_file.py:553` | Redactor |
| Nested `ComicInfo.xml` (in a subfolder) | Rewritten where it is | Written at the root, nested one dropped, `cbz_file.py:559` | Redactor |
| Compression of ComicInfo.xml | Deflated | Stored (its `_make_info` ignores `NewEntry.compress_type`, `zip_rewrite.py:368`, `:415`: a cbzredactor bug) | Deflate |
| Other entries' extra fields and `internal_attr` | Dropped, `zipwrite.py:250-261` | Kept, `zip_rewrite.py:252-292` | Redactor |
| Legacy (non-UTF-8-flagged) names | Garbled (D7) | Kept, `zip_names.py` | Redactor |
| Names differing only in case (`Page.jpg`, `page.jpg`) | Refused, `zipwrite.py:239-240` | Allowed | Redactor (such cbz files exist) |
| Check before the swap | `testzip()` CRC of every entry | Entry count only | Dossier |
| List separator (Writer, Genre, Tags) | Free text | Free text, ", " by convention | One shared constant ", " |

**MP3**

| Aspect | Dossier | mp3redactor | Should win |
|---|---|---|---|
| ID3 version | Always 2.4 (C4) | Kept, `tag_writer.py:218`, `:260` | Redactor |
| Multiple values | Read joined with "; " (`metawrite.py:149`), though Dossier's own columns join with ", " | First value only (`tag_reader.py:167`) | Neither: lists in, lists out |
| Frames | EasyID3 set (TIT2 TPE1 TALB TPE2 TRCK TPOS TDRC TCON TCOM) | Same, plus TLAN, sort frames, TPUB, COMM, USLT, TXXX, UFID, APIC | Shared map |
| Genre "(17)" | Read as "Rock" (`TCON.genres`) | Raw text | Raw, for compare and write |
| Temp file and swap | Copy beside, edit, read back, old file to the bin; a symlink is replaced by a file | `mkstemp`, `os.replace`, follows symlinks, no bin | Dossier's read-back and bin, plus `realpath` |
| FLAC, Ogg, Opus, M4A | Written | No writer | Dossier's code moves as it is |

The same in both: APIC and unknown frames are kept, frames are UTF-8, ID3v1 is updated but never created, and default padding is used. EPUB is not written by metawrite, so the epubredactor EPUB 3 bug does not apply; only D7 reaches epubs.

**Proposed shared module (L).**
- **Where:** `redactor_common/core/comicinfo_write.py`, `audio_write.py` and `zip_rewrite.py`.
- **Zip rewrite:** promote cbzredactor's `zip_rewrite`, `zip_names` and `RawNameInfo`. Add `verify_crc=True` as the default, a `trasher` hook, and progress/cancel.
- **ComicInfo:**
  - `parse_comicinfo`, `apply_comicinfo_edits`, `serialize_comicinfo`;
  - `check_comicinfo_value`, built on `check_text` and `is_ascii_number`;
  - `COMICINFO_ORDER`, `LIST_SEPARATOR` and `find_comicinfo_member`;
  - `write_comicinfo_into_cbz`, which checks the XML before the swap.
- **Audio:** `read_audio_tags` / `write_audio_tags(keep_id3_version=True)`.
- **Tests:** in each of the three repos, a test that fails if the app writes ComicInfo or mutagen tags or opens a zip for writing outside the shared module.
- **Before that:** fix D6 and C1 to C4 in Dossier first, each size S.

## 7. Health overlap with the Ⅎolder Redactor (usability finding 5, plan D23)

`dossier/core/health.py` and `health_rules.py` have no Qt imports. These rules are generic hygiene and could become pure functions in `redactor_common/core/hygiene.py`, with each app keeping its own walk and fixes:

| Rule | Generic? | What blocks moving it |
|---|---|---|
| `junk` (JUNK_NAMES, JUNK_SUFFIXES, `~$`) | Yes: the list D23 needs most | Fix D8 first; `.dossier-part` stays in Dossier's own list |
| `zero_byte` / KEEP_EMPTY | Yes | Extend KEEP_EMPTY (C6) |
| `name_problems`: trailing dot or space, reserved name, illegal characters, long path | Yes (the Ⅎolder Redactor's `unsafe-name`) | None (pure string checks) |
| `name_problems`: not NFC, mojibake, upper-case extension | Yes (overlaps `name-style`) | None |
| `odd_dates` | Yes | Pass `now` in |
| `broken_link` | Yes | Uses `ctx.fs.scheme`; pass a flag |
| `extension_against_content` (MAGIC, EXPECTED) | Yes | Take a `read_head(path, n)` callable instead of `ctx.fs.open_read` |
| `zip_integrity` | Yes | Same, and fix C5 |
| `case_twins` | Yes | None |
| `empty_folder` | Yes | Pass `is_root` and roots in; fix D8 and D10 |
| `sidecar_orphans` | No: media-specific, better as a profile setting | |
| Framework (`Finding`, `Fix`, tiers, `run_checks`, `fix_plan`, `IgnoreList`) | Dossier's own | `fix_plan` needs `ops` and `quarantine` |

Size: M to move the lists and checks, after D8, D9, D10, C5 and D17 are fixed (each S).

---

## 8. Clean-up

| # | What | Where | Size |
|---|---|---|---|
| K1 | The core tests the OS outside `core/platform.py` (against the project rule) | `sys.platform` in `columns.py:76`, `drive_identity.py:20`, `fastcopy.py:36`, `filetags.py:178`, `mounting.py:39,72`, `netlogin.py:46,62`, `properties.py:128`, `sshlink.py:49,57,173,182,196`, `tailnet.py:52,56,95`, `tools.py:188`; `os.name` in `archives.py:201`, `transfer.py:48`; own `IS_WINDOWS` in `sharing.py:26`, `shellmenu.py:27` | S |
| K2 | The "no console window" flag is copied 8 times (one is a bare `0x08000000`) | `archives.py:202`, `commandline.py:87`, `covers.py:146`, `mounting.py:82`, `sharing.py:296,457`, `sshlink.py:57`, `tailnet.py:95` | S |
| K3 | The holder/box/finished pattern is still hand-rolled 3 times, against the rule to use `run_in_background` | `dossier/gui/viewer.py:355-380`, `:407-432`, `:470-496` | M |
| K4 | A quiet thread + dispatcher + generation counter pattern is open-coded 7 times | `panel.py:477,1326,1356`, `main_window.py:141,851`, `sharing.py:378`, `tailnet.py:74` | S-M |
| K5 | Dead code, no caller outside tests (checked by grep) | `cli/helpers.py:48 size_text`, `:101 first_line`; `platform.py:346 quote_arg`, `:367 is_hidden`; `columns.py:39 is_meta`; `servers.py:124 parse_authority`; `sftpfs.py:245 mode_text`; `sshlink.py:289 error_text`; `sftp_proto.py:112 u8`; `floating_bar.py:135 set_stepping`; `notepad.py:509 current_text`; `zip_edit.py:41 _in_zip` | S |
| K6 | Copies: `cli/helpers.py:94 sort_entries` copies `vfs.py:296`; `zip_edit.py:33 _size_text` and `cli/commands.py:210` format sizes outside `sizefmt`; `covers.py:27-31` is a second natural sort; `sharing.py:62 path_key` copies `platform.path_key`; `home.py:108` and `layouts.py:59` hand-roll it | as named | S |
| K7 | Archive extension lists drift: `health_rules.py:22 ZIP_EXTENSIONS` (9 types) against `zipwrite.py:26 ZIP_BASED`; cbz defined twice (`properties.py:24`, `metawrite.py:29`) | as named | S |
| K8 | `gui/panel.py` is 1800 lines (the `Panel` class 1140). The tabs section (1433-1713) and the metadata/tags columns (1296-1432) are natural mixins. `MainWindow` has 43 base classes | | M |
| K9 | Half-built: the custom terminal template (`core/terminals.py:69 custom_profile`) has no way in from the GUI | | S |

**Fine:**
- No Qt imports in `core`, `cli` or `assistant`.
- `redactor_common` is pinned to a tag.
- The remote clients share TLS, error and transport code properly.
- Every settings key written is also read.
- There are no TODO, FIXME or stub actions.

---

## 9. Docs and code disagree

| # | Doc says | Code says |
|---|---|---|
| 1 | `CLAUDE.md` "State": no GUI, viewers, notes, metadata, remote or MCP yet | All built, and 0.5 released. Rewrite the section |
| 2 | `CLAUDE.md` "Open items" and `docs/spec.md:228-230`: metadata order and "remote read-only?" open | Settled: mp3, cbz, video (`docs/metadata-plan.md:57`); every server has a read-only switch, on by default (`core/servers.py:58`) |
| 3 | `README.md:33`: the release tag is `v` + RELEASE | The build's tag since 2026-11-02 (`core/version.py:24`, `release.yml:54`) |
| 4 | `README.md:14` leaves out Google Drive, and the README never mentions Health/`dossier check`, tag writing/`dossier tag`, sharing, quarantine, mounting or the glass viewer | All built |
| 5 | `docs/tags-plan.md:7`: "PLAN ONLY. Nothing is built." | `core/filetags.py`, the Tags tab and columns, `find --tag` (builds 2026-10-20#12-#16) |
| 6 | `docs/checkers-plan.md:3`, `docs/spec.md:246`: checkers not in 0.1 / planned | Waves 0 and 4 and part of 1 are built (10 checkers); bit-rot baseline, hash lists, the museum fixture and waves 2, 3 and 5-9 are not |
| 7 | `docs/spec.md:84`: "Not done: writing into archives"; `spec.md:3` "status as of 2026-10-19" | `core/zipwrite.py`, `gui/zip_edit.py` |
| 8 | `docs/spec.md` lists requirements with no code and not marked Later: C2 command palette, C7 hotkeys/O7, C8 profiles, C10 languages, V5 CSV viewer, V6/A5 SQLite, N3/N4 `.dossier.md` sidecar notes, V2 hex editing, W1 tree view, V9 file-type mapping. V7 says "image preview pane only" | A full glass picture viewer was built |
| 9 | `docs/spec.md:179` X4: separate write switches for files, metadata and notes | One `allow_file_changes`; `docs/assistant.md` agrees with the code |
| 10 | `docs/home-and-servers-review.md:28`: Google Drive through rclone, later | A native client was built |
| 11 | `docs/cli.md` has no section for `mcp` | `cli/__init__.py:18` |
| 12 | `docs/code-review-2026-10-20.md`: features 5-20 "still open" | All built (batch rename, search, compare/sync, checksums, duplicates, resume, thumbnails, properties, viewer modes, named selections, note editing, MCP, remote sources, conflict dialog) |

These agree: `docs/cli.md`'s flags and `cli/commands.py`, the 24 MCP tools in `docs/assistant.md` and `assistant/tools.py`, and the README's F-keys and `core/fkey_config.py`.

There is no user guide. A one-page "Using Dossier" (F-keys, marks across two panels, why undo is small, what is permanent on a network drive or USB stick) would also be the place to explain D2 and D12.

---

## 10. The 2026-10-20 review, looked at again

All 17 findings were marked fixed. These three are only partly so:
- **#5 (undo on the window's thread).** Undo was scaled down, so it is instant locally, but it still runs on the window's thread and blocks on a NAS or server (F5).
- **#13 (closing).** The 2-second exit after the window closes works (`gui/app.py:10-24`), but `closeEvent` itself still waits for the running copy before that (F4), and server disconnects can hang (F3).
- **#16 (timing tests).** Timing assertions were replaced by events, but most GUI tests still depend on the 0.15 s listing budget (T1).

## Suggested order

1. **Data-loss fixes, each S:** D1, D3, D4, D8, D9, D15, and D2 (bundle pywin32 and warn on removable drives). Then D5 (M).
2. **Sharing:** fix S1 and S3, add the Experimental switch, then one hands-on run by the owner.
3. **Freezes:** F1 (one line of caching, the biggest win), then move F2, F5, F6 and F8 onto `_plan_in_background`; F4.
4. **Tests:** T1 and T2. This should end the "1 run in 4".
5. **Tag writer:** D6 and C1 to C4 now; then the shared `redactor_common` module (L).
6. **Health:** D10, D17 and C5, then the shared hygiene lists (M).
7. **Clean-up and docs:** K1 to K7, rewrite CLAUDE.md "State", and a one-page user guide.

## Status

Fixed in build 2026-11-04#01 (owner's choice: the data-loss fixes first): D1, D2, D3, D4, D5, D8, D9, D10 and D15, each with a test that fails on the old code. D13 is fixed with D2 (Move into Zip now says when originals are deleted for good). D2 also brings in pywin32 on Windows, which makes the release exe bigger.

Fixed in builds 2026-11-04#02 and #03 (owner's choice: sharing next): S1, S3, S4, S5, S7 and S11. Sharing is now behind Settings > Network Sharing > Allow Sharing Folders (Experimental), off by default; reading shares still works with it off. Still to do for sharing: one hands-on run of the real elevated flow by the owner (create, change, rename, stop, a refused prompt).

Fixed in build 2026-11-04#04 (owner's choice: freezes next): F1, F2, F4, F5, F6, F8 and F10, with tests that fail on the old code. D12 is partly fixed with F1: the "permanent" note now comes first among the warnings (paste and drag-and-drop still have no confirmation). T5 is fixed. Still open among the freezes: F3 (server disconnect), F7 (opening files: F3, F4, Enter on a picture), F9 (drag out of servers) and F11.

Fixed in build 2026-11-04#08 (owner's choice: tag writer fixes): D6, D7, C1, C2, C3 and C4, each with a test that fails on the old code. The rest of section 6 is still open: the differences from cbzredactor and mp3redactor (namespaces, element order, empty elements, PageCount, extra fields) and the shared module in redactor_common, which spans three repositories.

Fixed in build 2026-11-04#07 (owner's choice: Health and security leftovers): S2, S6, S8, S9, S10 (a delete of marks the assistant set says so), C5, D17 and most of C6 (empty markers; links to a missing drive or share). Still open there: folder names are not checked by the name rules, `sidecar_orphans` noise, secrets through `keyring` directly instead of `secret_store`, and the elevated script's result file in `%TEMP%` (S11).

Fixed in build 2026-11-04#06 (owner's choice: the remaining freezes): F3 and most of F7 (F3, F4 and Enter prepare on a thread), and the drag-over decoding of F11. Still open: the viewer reading its first page and Markdown on the window's thread, notepad save, F9 (a drag out of a server copies the file at the drop: it needs staging before the drag starts, or a virtual-file drop), and the rest of F11 (network auto-refresh watches, share login, opening a file on a share with its Windows program).

Fixed in build 2026-11-04#05 (owner's choice: flaky tests next): T1 to T9. With them, two full runs in a row passed (1882 tests each).

Everything else is still open.
