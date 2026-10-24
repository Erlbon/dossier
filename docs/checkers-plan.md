# Dossier: file health checkers, plan

Date: 2026-10-19. Goal from the owner: load up on file checkers of many kinds so the files in the file system stay as healthy as possible. This plan covers the framework, the catalogue, the build waves and the decisions still open. It sits next to the 0.1 plan in `review-and-plan.md`: **checkers are not in 0.1** (decided scope), but the Qt-free framework can be built in parallel because it needs no GUI.

## 1. Principles

1. **Findings, not fixes.** A checker only reports. It never changes a file.
2. **Fixes are plans.** A fix is a proposal that turns into an ordinary `Plan` (rename, move to a quarantine folder, delete to the bin) or a metadata plan (M5), so it is previewed, runs with progress and cancel, and can be undone. A corrupt file is moved to a quarantine folder, never deleted outright.
3. **Cost tiers, cheapest first.** T0 reads only the listing (names, sizes, dates). T1 reads a header or metadata (a few KB per file). T2 reads the whole file (decode, CRC, hash). T3 calls an external tool or the network (ffmpeg, epubcheck, lookups). Only T0 and T1 run on "Check this folder"; T2 and T3 are chosen on purpose and run in the background.
4. **Incremental and resumable.** A 3.6 TB library cannot be rescanned from zero each time. Each result is keyed by path, size and modification time; an unchanged file is skipped. A T2 run can be stopped and continued.
5. **Same rules everywhere.** The GUI, a command line (`dossier check PATH`, so a check can run on the server next to the disks, not over SMB) and later the MCP server call the same core. No behaviour exists only in one front end.
6. **Opt-in memory.** Findings, baselines and ignore lists hold paths, which are user data. They are kept in memory by default; saving them is a Preferences checkbox with a delete button (the rule from the other apps).
7. **No network and no extra dependencies by default.** Checks that need Pillow, pypdf or an external tool are optional extras, found through the tool locator; their absence turns that checker off with a visible note, never an error.

## 2. The contract

```text
Checker        id, name, tier (T0..T3), scope (file | folder | library), extensions (or "any")
               check(context) -> iterable of Finding        (read-only, cancellable, reports progress)
Finding        path, checker id, rule id, severity (error | warning | info), message, evidence,
               fix (optional FixProposal)
FixProposal    label, build_plan() -> Plan                  (a normal operation plan, or a metadata plan)
Context        file system, entry, cancel token, progress callback, settings, shared caches
```

- **Scopes:** a *file* checker sees one file; a *folder* checker sees a listing (structure, naming conventions, sidecars, empty folders); a *library* checker sees many items at once (duplicates, gaps in a series, files that vanished since a baseline).
- **Registry:** checkers register by id like viewers (V9) and metadata handlers (M5); a profile switches sets on and off per library root.
- **Results are a virtual folder** (P3): the Health window lists findings like files (sortable, resizable columns, selectable into the shared selection), grouped by checker or severity. "Select all files with errors" then feeds any file command.
- **Ignores:** a finding can be ignored by path and rule, or by rule for a folder. Stored only if saving is allowed.

## 3. Catalogue

"Reuse" names code that already exists in the user's repos; check it before reuse and promote shared parts to `redactor_common` rather than copying (the no-duplication rule).

### A. File system hygiene (pure standard library, T0 unless noted)

| Rule | What it finds | Fix |
| --- | --- | --- |
| Zero-byte and tiny files | Empty files, files under a per-type size floor | Quarantine |
| Junk and temp files | `Thumbs.db`, `.DS_Store`, `desktop.ini`, `~$*`, `.part`, `.crdownload`, our own `.dossier-part` leftovers | Delete to bin |
| Broken links | Dead symlinks, junctions pointing nowhere | Delete link |
| Name problems | Trailing space or dot, Windows-reserved names, characters illegal on Windows, names that differ only in case, Unicode NFC/NFD mix, mojibake (`Ã©`), over-long paths (over 259), double extensions, upper-case extensions | Rename plan |
| Extension against content | A `.jpg` that is a zip, a `.cbz` that is a rar (T1, magic bytes; reuse `archive_sniff`) | Rename or flag |
| Empty folders | Folders with nothing in them, or only junk | Delete to bin |
| Sidecar orphans | `.srt`, `.nfo`, `.jpg` cover without a media file; `.dossier.md` entries for files that are gone (N4 consistency) | Report, then plan |
| Odd metadata | Dates in the future or at 1970/1980, read-only or hidden flags where unexpected | Report |
| Unreadable | Read errors, permission denied, cloud placeholders not downloaded | Report |

### B. Integrity of common formats (T1 and T2)

| Format | Check |
| --- | --- |
| ZIP, CBZ, EPUB, DOCX, XLSX | Central directory readable, CRC of every entry (`testzip`), duplicate entry names, path-escape names, bomb guard (A4), encrypted entries |
| Other archives (TAR, GZ, 7z, RAR) | Header and checksum test; 7z and RAR only through an external tool (T3) |
| Images | Decodes completely (Pillow `verify` plus load), not truncated, plausible dimensions, EXIF sanity |
| PDF | Header, trailer, cross-reference table, page count; deeper with `qpdf --check` if present (T3) |
| Text, JSON, XML, TOML, YAML, CSV | Valid encoding, NUL bytes, mixed line endings, parses cleanly, ragged CSV rows |
| SQLite | `PRAGMA quick_check` on a read-only connection; `integrity_check` as T2 |
| Hash lists | Verify `.sfv`, `.md5`, `.sha256` files that sit next to the data |

### C. Media (T1 for tags, T2 for decoding)

| Type | Check |
| --- | --- |
| Audio | MP3 frame sync errors (reuse `mp3val_runner`), truncated file, ID3 sanity, bitrate against claim (reuse `audio_quality`), full decode to null with ffmpeg (T3) |
| Video | Container errors (reuse `container_check`, `file_check`), missing streams, duration mismatch, `moov` atom position, optional full decode pass (reuse `deep_scan`, `cut_damaged`) |
| Subtitles | SRT parses, encoding, overlapping or negative times |
| Covers | Embedded art present, size sane, same across an album |

### D. Format checkers from the Redactor cores (T1/T2, adapters)

| App | Reuse |
| --- | --- |
| EPUB | `validation_issue`, `content_scan`, `manifest_dedupe`, `nav_repair`, missing cover, bad OPF, language and encoding problems |
| CBZ | `comicinfo_check`, `archive_contents`, `zip_names`, `page_dimensions`, page-number gaps, mixed page sizes, credit pages |
| MP3 | Missing artist, album or year, inconsistent album art, track-number gaps, tag against folder name |
| Video | Missing title or year, tag against file name |

These live in the apps today. Promote the checks themselves into `redactor_common` (plan step 4 of the 0.1 plan makes that package Qt-free) and let both the apps and Dossier call them.

### E. Library structure and naming rules (folder scope, user-defined)

- Port the rule set of the comic structure checker (`C:\Dev\comic-checker\check_comics.py`: name style, country and lineage numbering, duplicate era numbers, loose CBZ beside era folders, wrong container formats, junk, `(N issues)` notes) as the first **rule profile**.
- Rule profiles are data: a TOML file per library with pattern, condition, severity and optional fix (a rename pattern, F2). Nothing library-specific is hard-coded in Dossier.
- Filename against pattern, series-number gaps (reuse `series_numbering`), folder-note presence (`about.md`, `artist.md`, `README.md`).

### F. Duplicates (library scope)

- Exact: same size, then partial hash, then full hash.
- Near: reuse the existing fingerprints (`cbz_fingerprint`, `epub_fingerprint`, `video_fingerprint`, `mp3_duplicates`, `duplicates`).
- Same work in different formats, case-only duplicates, copies left by "keep both".
- Fix: select the redundant copies into the shared selection; keep-best suggestion by format, size, tag completeness. Deleting is always a plan.

### G. Health over time (library scope, needs a saved baseline)

- **Bit rot:** store hash, size and mtime once; a later scan that finds a changed hash with unchanged size and mtime is silent corruption. This is the one check that catches damage nothing else can see, and the strongest reason to allow saved baselines.
- **Vanished files:** what was in the baseline and is gone.
- **Growth and anomalies:** a folder that suddenly shrank, a file that changed size without a date change.
- Compare against a mirror or backup folder (F6) and list differences.
- Out of scope here: disk SMART health and backup scheduling (a separate tool; Dossier could later read SMART values through `smartctl`).

### H. Safety

Executables or scripts inside media libraries, macro-enabled Office files, archives with absolute or parent-relative paths, files whose extension and content disagree in a risky direction (`.jpg.exe`).

## 4. Build waves

Sizes use the owner's scale (small under 2 minutes of Claude time, medium up to 10, large over 10). Lane C is Qt-free core; L needs the GUI or real folders.

| Wave | What | Lane | Size | Done when |
| --- | --- | --- | --- | --- |
| 0 | Framework: contract, registry, `Finding`, runner on `JobRunner` with progress and cancel, tier gating, result store (memory, optional save), `dossier check` command line, results as a virtual folder, fix-to-`Plan` bridge, test harness | C | large | A trivial checker runs from the command line and from a job, with cancel, and its fix runs as an undoable plan |
| 0b | A generated "museum of broken files" for tests (`tests/museum.py` builds the tree in `tmp_path`: truncated zip, bad CRC, zero-byte file, mojibake name, dead link, orphan sidecar, wrong extension) | C | medium | Every later checker has a failing case to start from |
| 1 | Group A and the ZIP integrity of B, extension against content, exact duplicates, sidecar orphans. Standard library only | C | large | The museum's issues are all found; none reported on a clean tree |
| 2 | Rest of B: images, PDF, text and data files, SQLite, hash lists (Pillow and pypdf as optional extras) | C | large | Same, with extras absent and present |
| 3 | The bit-rot baseline and "vanished files" (G), with the opt-in save | C | medium | A flipped byte under unchanged mtime is found |
| 4 | Health window: findings list, grouping, severity filter, select-into-selection, fix preview, ignore | L | large | Walk from finding to previewed fix to undo on real folders |
| 5 | Redactor adapters (D): promote the checks to `redactor_common`, wrap them | C | large | Apps and Dossier report the same findings for the same files |
| 6 | Media (C) through the tool locator: mp3val, ffmpeg decode pass, container checks | C | medium | Run on a sample set with and without the tools installed |
| 7 | Rule profiles (E): TOML loader, the comic profile ported from `comic-checker`, fix patterns | C | large | The profile reproduces the old checker's summary on its sample folder |
| 8 | Near-duplicate fingerprints (F) and the mirror compare (G) | C | medium | Known near-duplicates in the sample set are paired |
| 9 | Scheduling and trends: resumable T2 runs, "check on idle", history of health per folder, MCP read tools (list findings), later an AI helper that explains a finding and proposes a fix through the same plan rule | C then L | large | A night run over a large folder resumes after interruption |

Order logic: wave 0 first because everything hangs off it; wave 1 gives the biggest visible value for no dependencies; wave 3 early because a baseline only protects files from the day it is taken; the GUI arrives at wave 4 so checkers are tested without a window first.

## 5. Risks

1. **False positives** erode trust. Every rule has a severity, an explanation of the evidence, and an ignore; a rule that cries wolf on the museum's clean tree does not ship.
2. **Scale:** 3.6 TB and tens of thousands of folders. Incremental keys, tiers and resumable T2 runs are required, not optional. A full-content pass over a library is a night job.
3. **Over SMB** a content check crawls. The command line exists so the same core runs on the server.
4. **Duplication with the Redactor apps.** The same check in four places drifts. Promote first, then call (wave 5 depends on the Qt-free split of `redactor_common`).
5. **External tools** differ between Windows and Linux and may be missing. Found through the tool locator, reported when absent.
6. **Fixes that destroy.** Quarantine instead of delete, plan before commit, undo journal, as everywhere else.
7. **Privacy:** saved findings and baselines are path lists. Off by default, deletable.

## 6. Decisions needed from the owner

| # | Question | Recommendation |
| --- | --- | --- |
| H1 | Allow saving the findings and baseline between runs (opt-in checkbox, delete button)? | Yes as opt-in. Without it bit-rot detection (G) and incremental scans are impossible |
| H2 | Which library first for real tests: comics (CBZ), EPUB, music, or video? | Comics: the structure checker and rules already exist and the library is the largest |
| H3 | Run checks where: on this PC, or also on the server through the command line? | Both. The core is Qt-free, so this costs nothing extra |
| H4 | Optional dependencies (Pillow, pypdf) acceptable as extras, or standard library only? | Extras, off when missing |
| H5 | Quarantine folder policy: one folder per library root, or beside the file? | **Decided (owner, 2026-10-24) and built:** by default `<drive>:\Temp\Quarantine` on each drive, or one folder of the owner's choice (Settings > Quarantine); mirrored paths, so a file can be put back. `core/quarantine.py` |
| H6 | Start the framework (wave 0) now in parallel with the 0.1 GUI work, or after 0.1? | Now; it is Qt-free and does not touch the GUI lane |
