# Copy robustness: closing the gap with robocopy

Written 2026-11-05 after comparing the copy engine (`core/transfer.py`, `core/ops.py` `execute`) with robocopy for a 50 GB, 15,000-file
transfer from one PC to a home server over the LAN.

**Status (build 2026-11-05#02):** steps 1 to 3 are built, except reconnecting a dropped SFTP session inside step 1 (a dropped server
session still fails its files; SMB network drives are covered). Steps 4 to 6 are open.

## Where the engine stands

Already as good as robocopy or better:
- Every file is written as `name.dossier-part` and renamed at the end; an existing target moves aside only when the new data is complete
  (`Swap`). A crash never leaves a half file under the real name.
- Verify (C6) reads every copy back before the part takes its name. robocopy has no read-back.
- Large local files go through `CopyFileExW` (attributes, times, alternate data streams); small files run in a worker pool.
- Conflicts are planned and shown first; the opt-in queue journal continues an operation after a restart; long paths are handled.
- With *ask on error* off (the default) a failed file is skipped and the rest goes on, so an unattended copy is not held by a dialog.

The gaps:

| # | Gap | robocopy | Dossier now |
|---|-----|----------|-------------|
| G1 | A network blip (SMB session reset, Wi-Fi drop, server sleeping) | `/R:n /W:s`, minutes of patience | `is_transient` only knows locks; the file fails at once |
| G2 | A big file interrupted halfway | `/Z` continues where it stopped | the part file is deleted; the file starts over |
| G3 | Folder times | `/DCOPY:T` | a made folder gets today's time |
| G4 | A record of what happened | `/LOG`, `/TEE`, a summary table | the window's messages; nothing to keep or compare |
| G5 | Re-running to finish the job | `/E /XO` style: skip what is already the same | a second copy of the same tree asks about every taken name |
| G6 | Files the account may not read | `/B` backup mode | access denied, skipped |
| G7 | Permissions and owner | `/SEC`, `/COPYALL` | not copied (normal for a home archive) |

## The plan, in order of value

### Step 1: retry network failures with patience (G1)
- `is_transient` learns the network errors: Windows `ERROR_NETNAME_DELETED` (64), `ERROR_UNEXP_NET_ERR` (59), `ERROR_SEM_TIMEOUT` (121),
  `ERROR_BAD_NETPATH` (53), `ERROR_NETWORK_UNREACHABLE` (1231), `ERROR_CONNECTION_ABORTED` (1236), and `ETIMEDOUT`, `ECONNRESET`,
  `EHOSTUNREACH`, `ENETUNREACH` on Linux; for servers, `NotConnected` and an SFTP channel that closed.
- Two retry classes in `ExecOptions`: the existing short one for locks (3 tries, 0.25 s doubling) and a new long one for the network
  (`network_retries`, default 10, `network_wait` 30 s, capped backoff), as robocopy `/R:10 /W:30`.
- While it waits the queue says so ("waiting for homeserver3, try 3 of 10"), and a pause or cancel still works at once.
- A server connection that dropped is reconnected before the retry (`gui/servers.py` `connect_server` with the saved login; never a
  prompt in the middle of an unattended run: no saved login means the file fails as now).
- Settings > Copy and Move: the two numbers. Tests: a fake file system that fails N times with each error.

### Step 2: resume a big file instead of starting over (G2)
- For files above a threshold (say 64 MB), a failed or cancelled copy keeps its `name.dossier-part` and writes a small sidecar
  `name.dossier-part.json` (source path, size, mtime, bytes known good).
- The next try (a retry, a restart through the journal, or a re-run) finds the part, checks the source has the same size and mtime,
  re-reads the last chunk of both to be sure they match, and continues by seeking both streams. Anything doubtful starts over.
- `CopyFileExW` cannot continue a part, so a resumed file goes through the plain loop; with Verify on, the read-back still covers the whole file.
- Part files left behind are listed by the Health window (they are already named so they can never be taken for the real file).

### Step 3: folder times (G3)
- After the copies of a tree are done, a final pass sets each made folder's modified time to the source folder's, deepest first (writing
  into a folder changes its time, so it must come last). Also over SFTP where the server allows it.

### Step 4: a copy report (G4)
- Every run of more than, say, 100 steps writes a CSV next to the queue journal: path, size, result (copied, skipped as the same,
  failed and why, retried n times), and seconds. The queue shows a summary line and a "Show the Report" button.
- The same columns as the assistant's manifest reports, so the report and a manifest of the target can be compared.

### Step 5: "finish the job" mode (G5)
- A copy option *Skip what is already there and the same* (size and time, with the one-hour summer-time allowance from `core/compare.py`,
  or by content with Verify): a re-run after a failed night copies only what is missing or changed, with no questions. This is robocopy's
  most common use; `plan_sync` `update_right` already does much of it, so this may be a matter of offering it from the copy dialog.

### Step 6: later, only if needed (G6, G7)
- Backup mode (`SeBackupPrivilege`) needs an elevated program and is rarely needed for one's own files: leave out unless asked.
- Permissions: leave out; a home archive wants the target's own permissions.

## How to check it

- A soak test on the real case: copy the Maritime folder from erbo2 to Homeserver3 while pulling the network cable twice and putting
  the server to sleep once. Expect no failed files, two resumed big files, and a report that a fresh manifest of the target agrees with.
- Compare the time against `robocopy /E /Z /R:10 /W:30 /MT:8` for the same tree.
