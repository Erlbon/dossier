# Dossier on the command line

`dossier <command> ...` (or `python -m dossier <command> ...`) runs a command and never opens the window. Anything else (no argument, or
a folder) starts the window as before. It is the same program: the commands call the functions the window calls, so nothing happens here
that the window cannot do and nothing is done differently.

## Rules every command follows

- **Preview first.** Everything that changes files has `--dry-run`: it prints the plan (each step, the size) and does nothing.
- **Nothing is overwritten** unless `--on-conflict overwrite` says so (`copy` and `move`). What is deleted, or replaced, goes to the
  recycle bin; `delete --permanent` is the one way to delete for good, and it says so by name.
- **Results** are text on stdout. With `--json` there is **one JSON document** on stdout and nothing else there, so a script can parse
  it: `{"command": ..., "results": [...], "warnings": [...], "errors": [...]}` and the summary of the command. Progress and warnings go to
  stderr (`-q` silences them). `--output FILE` writes the result to a file that is complete when the program ends (use this when a
  script starts the windowed program and cannot read its console).
- **Exit codes:** `0` all went well, `1` some items failed, `2` a mistake in the command or a path that does not exist, `70` a bug
  (the traceback is on stderr), `130` Ctrl+C.
- **Wildcards** (`*.jpg`) are expanded by Dossier, since the Windows command prompt does not do it. A name that exists is always taken as it
  is, so a `[` in a real name is not a pattern.
- **Servers** (SFTP, SCP, WebDAV, FTP) are not available here: they need a login and a key or certificate question that only the window asks.

## Commands

### ls

`dossier ls [path] [-l | --long]` lists a folder, folders first, in natural order (`img2` before `img10`). An archive file is listed like a folder.
`-l` adds size and date.

### info

`dossier info path... [--bytes]` shows what Dossier knows about each file or folder: size, times, tags, and what is inside: the tags and
technical facts of audio, the ComicInfo of a comic, the tracks of a video, the EXIF of a photo. `--bytes` writes sizes in bytes.

### find

`dossier find folder [--name N] [--text T] [--regex] [--case] [--kind files|folders|both] [--min-size S] [--max-size S] [--newer D]
[--older D] [--no-subfolders] [--tag X] [--limit N]` searches a folder tree and prints one path per line. Names: `report`,
`*.jpg;*.png`, or `!*.tmp` to leave out. Sizes: `10K`, `1.5M`, `2G`. Dates: `2024-05-17` or `2024-05-17 10:30`. `--tag` can be repeated.

### checksum

`dossier checksum path... [-a | --algorithm md5|sha1|sha256|sha512]` prints `hash *name` lines (the format of `sha256sum`). `--check LISTFILE`
verifies the files named in such a list (names are relative to the list) and prints `ok`, `FAILED` or `missing` for each; any problem
gives exit code 1. Nothing is written next to the files.

### copy, move

`dossier copy path... destination [--on-conflict skip|overwrite|keep-both|newer] [--create] [--verify] [--dry-run]` and the same for
`move` (without `--verify`). The last path is the destination folder; `--create` makes it. When a name is taken the default is `skip`:
nothing is overwritten. `newer` replaces only a file that is older. `--verify` reads every copy back and compares it with the original.

### delete

`dossier delete path... [--permanent] [--dry-run]` deletes files and folders to the recycle bin. `--permanent` deletes for good.

### dups

`dossier dups folder... [--min-size S] [--name N] [--keep oldest|newest|shortest] [--delete] [--dry-run]` finds files with exactly the
same content (by size, then the first and last 64 KB, then the whole file, so a reported group really is identical). Several folders find
what is in both. Each group shows the copy that stays (`keep`) and the others (`extra`). `--delete` moves the extras to the recycle bin;
one copy of every group always stays; `--dry-run` shows what would be deleted.

### compare

`dossier compare left right [--by size_time|size|content] [--no-subfolders] [--tolerance SECONDS] [--exact-hour] [--same] [--sync MODE]
[--dry-run]` lists the differences between two folders: `only-left`, `only-right`, `left-newer`, `right-newer`, `different` (same time,
different content) and `type-differs` (a file against a folder). `--tolerance` is how close two times must be to count as the same
(default 2 seconds); a difference of exactly one hour (summer time on FAT drives) is ignored unless `--exact-hour`. `--same` lists the files that
are alike too. `--sync` makes the folders alike, in a direction: `update_right`, `update_left`, `both`, `mirror_right`, `mirror_left`
(the mirror modes also delete what is only on the other side, to the recycle bin). Combine with `--dry-run` to see the plan first.

## Examples

```
dossier find D:\Photos --name "*.jpg" --min-size 5M --newer 2024-01-01 --json -o big.json
dossier dups D:\Photos E:\Backup --keep oldest --delete --dry-run
dossier compare D:\Music E:\Music --by content
dossier compare D:\Music E:\Music --sync update_right --dry-run
dossier copy D:\Music\*.flac E:\Music --on-conflict newer --verify
dossier checksum D:\Archive\* > sums.txt
dossier checksum --check sums.txt
```

In a batch file write `%%` for a literal `%`.
