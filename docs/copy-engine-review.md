# Dossier: the copy engine, a critical review (with Ultracopier and TeraCopy as the yardstick)

Date: 2026-10-19. Question from the owner: Windows copying is slow and can freeze; do we need "extra magic" like TeraCopy or Ultracopier? Answer in short: **Dossier never freezes during a copy (it runs on a worker thread with progress and cancel), but its copy engine is sequential and plain, and a measurement on this machine shows that is its real weakness: thousands of small files copy 12 to 25 times faster with parallel workers.** Most of what Ultracopier adds is worth having; hooking the operating system's copy dialogs is not.

## 1. Why Windows copies feel slow and freeze

1. **One file at a time.** Every file costs a create, a close and a metadata update. With real-time virus scanning each of those can take milliseconds, so thousands of small files crawl even when the disk is fast.
2. **The window waits.** Explorer's copy runs in the same shell that draws the window; a slow network share, a locked file or an error dialog stalls it, and "calculating time remaining" scans everything first.
3. **Errors stop everything.** One locked file raises a dialog and the rest waits behind it.
4. **Cache lies.** Progress reaches 100 percent when the data is in memory; the slow part (flushing to a USB stick or share) comes after, so "done" is followed by a hang when the device is ejected.
5. **No queue, no pause, no speed control.** Two copies to the same disk fight each other.

## 2. What Dossier already does right

Copies run on a worker thread; progress and cancel work (a half-copied file is removed, the old target is untouched); each file goes to a temporary name and is renamed into place; conflicts are decided before the run; an overwritten target goes to the recycle bin first; the whole run is undoable; one failing file does not stop the others and everything is reported at the end; navigation never blocks. So the **freezing** half of the complaint is already solved.

## 3. What the measurement says

Run on this PC (a managed Windows laptop, SSD, real-time scanning on), the current `copy_file` against Python's own copy and the operating system's copy call. Indicative, not a benchmark suite: single runs, cache effects, noisy.

| Case | Time |
| --- | --- |
| 1 GiB file, `copy_file` with 1, 4 and 16 MiB chunks | 3.0 s, 1.3 s, 3.2 s (noisy; a larger chunk is not automatically better) |
| 1 GiB file, `shutil.copyfile` | 1.0 s |
| 1 GiB file, Windows `CopyFileEx` | 0.9 s |
| 1 GiB file, `copy_file` then flushed to disk | 3.2 s (the flush is part of the true cost) |
| 3000 files of 4 KiB, `copy_file`, one by one | **44.7 s** (15 ms per file) |
| 3000 files of 4 KiB, `shutil.copyfile`, one by one | 30.6 s |
| 3000 files of 4 KiB, `shutil.copyfile`, 8 threads | **1.7 s** |
| 3000 files of 4 KiB, `copy_file`, 8 threads | 3.7 s |

Findings:

- **Small files are the whole story.** The cost is per file (here about 10 to 15 ms, almost certainly the scanner), not per byte. Eight workers overlap the waiting and give 12 to 25 times the speed. No amount of chunk tuning does that.
- **Big files are fine already**, within a factor of two of the operating system's own call; the OS call is the fastest and also does attributes and timestamps. Worth using for large local-to-local copies.
- **Our per-file overhead is about 1.5 times Python's** (extra temporary file, rename, time stamp). It buys safety; parallelism more than pays it back.

## 4. Ultracopier, as far as its public page tells (read, not run)

A free GPL-3.0 copy manager written in C++17 and Qt 6, with a plugin design (engines and interfaces are loaded as plugins). Features named on its page: a task queue, pause and resume, resuming unfinished jobs, dynamic speed limiting, error handling and file-collision handling, resume after errors. It integrates by **replacing the system's copy and move dialogs**: a Windows Explorer plugin, `.desktop` actions on Linux, plus builds for Android and Haiku. The page does not describe its engine internals, checksums or threading, so none of that is claimed here. TeraCopy (closed source) is known for the same replacement approach plus verification by checksum after the copy.

**Licence and reuse.** Ultracopier's licence (GPL-3.0) matches ours, but it is C++ and Qt with its own plugin machinery: nothing can be lifted into Dossier, only ideas, and ideas need no licence. If an algorithm is ever ported, credit it in CREDITS.md.

## 5. Would it work for Dossier

| Idea | Verdict |
| --- | --- |
| Replace Explorer's copy dialogs through a shell extension | **No.** It is invasive, fragile across Windows updates and out of scope; Dossier is its own file manager, not a shell patch |
| Parallel workers for small files | **Yes, first.** The measured win |
| Queue of operations with pause and resume | **Yes.** Today one operation runs at a time and a second is refused while busy |
| Error policy: retry, skip, abort, apply to all, report at the end | **Yes, extend.** Dossier already continues past failures; add retries for locked and sharing-violation errors and the choice |
| Speed and time remaining, speed limit | **Yes.** Rate and estimate are cheap; a limit helps when a copy must not saturate a link |
| Verify after copy (checksum compare) | **Yes, optional.** Off by default; on for removable media and network targets if the user wants |
| Flush at the end for removable and network targets | **Yes.** Honest "done" |
| Resume unfinished jobs after a restart | **Later.** Needs a journal of paths, which is user data, so opt-in |
| Operating system fast paths (Windows `CopyFileEx`/`CopyFile2`, Linux `copy_file_range`, reflinks) | **Yes** for large local copies; keeps attributes; cancel through its callback |
| Alternate data streams, ACLs, extended attributes | **Decide.** Explorer keeps them; our copy drops them; an option, not silent |

## 6. Risks to design for

- **Parallel writers on a spinning disk or one USB stick make it slower** (seek thrash). Parallelism must be adaptive: workers only for small files, one stream for big ones, a lower count for removable and network targets, user override.
- **Undo journal and progress must stay correct with threads:** steps appended under a lock and ordered; folders created before the files in them; progress summed safely and throttled.
- **Cancel must stay prompt** inside a long write: write in chunks that finish in well under a second, and honour the OS callback's cancel flag for big copies.
- **Antivirus can lock a file the instant it is created:** retry with a short back-off before reporting an error.
- **Two operations to the same disk** should queue rather than compete by default.

## 7. Plan

| Step | What | Size |
| --- | --- | --- |
| C1 | Parallel worker pool inside `execute` for small files (adaptive count), serial for big files and for folders; thread-safe journal and progress; tests with a slow in-memory file system proving overlap, order and cancel | large |
| C2 | Error policy with retry and back-off for sharing violations; per-run choice (skip, retry, abort, apply to all); final report | medium |
| C3 | Speed and time remaining in the progress box; optional speed limit | medium |
| C4 | Operation queue with pause and resume, shown as a small list; one copy per target disk at a time by default | large |
| C5 | Operating system fast path for large local files (Windows `CopyFileEx`, Linux `copy_file_range`) with progress and cancel; 4 MiB chunks elsewhere | medium |
| C6 | Optional verify (hash compare) and flush-at-end for removable and network targets | medium |
| C7 | Attribute options (alternate data streams, ACLs) decided and stated in the plan dialog | medium |
| C8 | Resume after a restart (opt-in journal) | later |

## 8. Decisions needed

| # | Question | Recommendation |
| --- | --- | --- |
| K1 | Parallel copy default | Automatic: workers for small files only, never for one big file; a setting to force 1 |
| K2 | On an error: stop, or continue and report | Continue and report (as now), with retry for locked files |
| K3 | Verify after copy | Off by default; a checkbox in the copy confirmation |
| K4 | One operation at a time or a queue | A queue, one active per target disk |
| K5 | Hook the system's own copy dialogs | No |
| K6 | Run the same measurement on the server's disks and a USB stick before tuning | Yes, before C1 sets defaults |

## 9. Status (2026-10-19)

**C1 is built.** `execute` now works in phases: folders first, then the small files (up to 8 MiB) by several workers at once, then the big files one at a time, then moves, renames and deletes in plan order. The worker count is chosen by the target (8 on a fixed disk, 2 on removable or network, 1 on optical, at most 4 on a virtual system, 1 when fewer than four small files); `ExecOptions(workers=...)` overrides it. Progress is summed safely across workers, the recycle bin is asked one item at a time, results and the undo journal are in plan order, cancel stops new files and removes half-written ones, and a bug in a worker is raised, not swallowed.

Measured through the real `execute` on this PC, 1500 files of 4 KiB in ten folders: **25.2 s one at a time, 1.5 s with the automatic choice (8 workers)**, no failures. A setting to force one at a time, and the rest of the plan (C2 to C8), are still to do.

**C2 and C3 are built (2026-10-19).** A file that fails with a lock-type error (access denied, sharing violation, busy) is tried again up to three times, waiting 0.25, 0.5 and 1 s, cancel-aware; errors that cannot pass (missing file, full disk, read-only) are not retried. After the retries `ExecOptions.on_error` may answer retry, skip or abort; the window uses it only when Settings > "Ask When a File Cannot Be Copied" is on (default off: continue and report, K2). Abort stops steps not yet started and keeps what was done undoable. The progress box shows done of total, speed (measured over the last 4 s) and time left for byte totals. Settings > "Copy Speed Limit" (unlimited, 1, 5, 20, 50 MB/s) throttles all workers together. Still open: queue with pause (C4), fast paths (C5), verify and flush (C6), attributes (C7), resume (C8), and the K6 measurements on the server disks and a USB stick.

**C4 is built (2026-10-19), in a first form.** Copy, move, paste and delete are queued instead of refused while another operation runs; they run one after the other, which also means never two at once on one disk (a stricter rule than "one per target disk"; per-disk parallelism can come later). The progress box of an operation appears when it starts. Commands > "Pause or Resume Operations" (Ctrl+Shift+P) pauses the running copy at its next chunk and holds the queue; "Cancel Waiting Operations" drops those not started. The status line shows what runs and how many wait. Known limits: a queued plan is made when it is queued, so if it depends on an earlier queued operation (for example moving a file the earlier one creates) it fails with a clear error instead of guessing; there is no list dialog to reorder the queue yet; moves, renames and deletes are not interrupted by a pause, only copies.

**C5 is built (2026-10-19).** Local files of 8 MiB and up are copied by the operating system: `CopyFileExW` on Windows (progress routine, pause and cancel through it), `os.copy_file_range` on Linux (falls back to the plain copy when the kernel or the file pair refuses). Not used for memory or archive paths, nor when a speed limit is set, nor when `ExecOptions(native_copy=False)`. Side effects: Windows now carries alternate data streams and attributes across (C7 still to decide on ACLs). Measured here, 1 GiB, four rounds each on a managed SSD laptop: plain 1.3 to 2.7 s (mean 1.9), native 0.8 to 2.4 s (mean 1.5): about 20 percent, inside the noise. Expect more on network shares and on file systems that can copy on the server or by reference (ReFS, Btrfs, XFS). The Linux branch is covered by a skipped test on Windows and has not been run on Linux yet.

**C6 is built (2026-10-19).** Settings > "Verify Copies After Copying" (off by default, K3): every copied file is read back and compared byte for byte with the original; a copy that differs is deleted and reported with the byte where it differs, the good ones stay. The read-back counts in the progress bar (the bar's total grows by the copied bytes). Honest limit: a file just written may be answered from the system's cache, so the check proves the data that was written and that it reads back, not that the device holds it; the flush is what pushes it out. Flush: after the copies, every copied file gets an `fsync`, automatically when the target is a removable or network drive (`ExecOptions(flush=True/False)` forces it); the last 2 percent of the bar is kept for it, so "100 percent" is not followed by a hang when the stick is ejected; a file that cannot be flushed is reported as failed. Not done: bypassing the cache on read-back (`FILE_FLAG_NO_BUFFERING` / `O_DIRECT`), a flush setting in the window, and checksums to a file for later.

**Progress box (2026-10-19, owner request: "so the user does not feel abandoned").** The box shows four things: the item being worked on and its number (`holiday.mkv  (2 of 5)`), the size done of the whole and what remains (`100 MB of 400 MB, 300 MB remaining`), the speed over the last 4 s, and the time left. The sizes are the real bytes of the plan, not the bar's own total (which also counts reading back and flushing). A move to another drive used to report nothing while it copied; moved files now count in bytes like copies. Jobs that are not bytes (delete, rename) show the item and its number only.

**Verify checkbox (2026-10-19, owner: "we just do this").** The Copy and Move confirmation now has the checkbox "Verify the copies afterwards". It starts as last chosen (off at first), and the choice is stored in the same setting as Settings > "Verify Copies After Copying", so the two always agree. Paste (Ctrl+V) has no dialog and uses that setting.

**Folder moves across drives (2026-10-19, owner hit "not supported yet").** When the destination is on another volume (another drive letter or network share on Windows, another device on Linux), moving a folder is planned as a copy of the whole tree (folders merge, as in a copy) plus one finishing step. The finishing step runs last and removes the originals only if every file of the folder was copied and has the size of its original; the originals are removed permanently, file by file, then the folders that are empty by then. If any copy failed, nothing is removed from the source and the finishing step reports it. A conflict the user chose to skip leaves that original, and so its folder, in place. The undo journal gets one "moved" entry and never the copies (undoing them would delete the only copy), so Ctrl+Z reports that the move cannot be undone across drives and deletes nothing. Progress, speed, verify and flush all work as for a copy. Tested with simulated drives and the volume detection; not yet with a real second drive.
