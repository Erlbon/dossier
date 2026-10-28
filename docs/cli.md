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

### tag

`dossier tag path... [--set FIELD=VALUE]... [--clear FIELD]... [--dry-run] [--fields]` shows or changes the tags inside files: mp3, flac, ogg, opus and
m4a files (title, artist, album, album artist, track, disc, year or date, genre, composer) and the ComicInfo of a cbz (series, number, count, volume,
title, summary, year, month, day, the credits, publisher, genre, tags, language, age rating, manga, web). Give files of one kind. With neither `--set`
nor `--clear` it prints what the files carry. A field is named by its key or its label in any case (`album-artist`, `Series`, `year`); `--fields`
lists them. Only the fields you name are touched: cover art, lyrics and tags Dossier does not know stay as they are, and a value that is already
there is not written again. `--clear` (or `--set title=`) takes a field away. A file is never changed in place: the new version is made beside
it, read back and checked, and only then put in its place, and the old one goes to the recycle bin. `--dry-run` lists old and new values and changes
nothing; a file that cannot be changed (read-only, damaged, another kind) is named with the reason and the rest goes on.

### link

`dossier link target link [--kind symlink|junction|hardlink] [--relative]` makes a link. A **symlink** holds a path and can point at a file or a folder
(on Windows it needs Developer Mode or an administrator; the error says so). A **junction** (Windows only) shows another folder of the same computer and
needs no special right. A **hard link** is a second name for the same file on the same drive; it cannot be made for a folder. `--relative` makes a
symlink that stores the path from its own folder, so it still works when both are moved together. If `link` is an existing folder the link is made
inside it, named after its target. Nothing is ever replaced: a name that is taken is refused. `dossier info` shows what a link points at, whether it is
broken, and how many names a hard-linked file has.

### touch

`dossier touch path... (--set DATE | --shift TIME | --from-file PATH | --from-exif | --copy-from FIELD) [--modified] [--accessed] [--created] [-r] [--no-folders]
[--readonly on|off] [--hidden on|off] [--system on|off] [--archive on|off] [--dry-run]` changes dates and attributes of many items at once. `--set` gives
the moment, `--shift` moves the dates (`+2h`, `-1d`, `1d2h30m`), `--from-file` takes the date of another item, `--from-exif` takes the date a photo was
taken, `--copy-from created` copies one date of an item into the others (for example the creation date into the modified date). `--modified` is the
default; `--created` works on Windows only. `-r` (`--recursive`) goes into folders (links are not entered); `--no-folders` leaves the folders' own dates alone. Read-only
files and folders can be changed. Use `--dry-run` first: it lists the old and the new values and changes nothing. The attributes hidden, system and archive
exist on Windows; elsewhere only read-only (the write permission).

### check

`dossier check folder... [--deep] [--only RULE] [--list] [--fix [--delete-junk | --quarantine [--quarantine-folder FOLDER]]] [--dry-run]` looks for files that are not healthy and reports
them, never changing anything unless `--fix` says so. It finds empty files, junk (`Thumbs.db`, `~$` files, half-downloaded files), names that
break on Windows (trailing space or dot, reserved or illegal characters, accents stored in the wrong form, text read in the wrong encoding, paths
over 259 characters), names that differ only in case, dead links, dates in the future, a `.cbz` that is really a rar, subtitle files without a video,
and empty folders. `--deep` also reads every zip-based file (zip, cbz, epub, docx and others) completely and tests its checksums. `--list` names the
checkers; `--only` runs some of them. Each finding has a severity (error, warning, note). `--fix` applies the renames, or with `--delete-junk` moves
the junk and empty folders to the recycle bin, or with `--quarantine` moves empty files and damaged zips into the quarantine folder (on each drive
`<drive>:/Temp/Quarantine`, or the one folder `--quarantine-folder` names; a file keeps its place in the folder tree there, so it can be put back);
`--dry-run` shows the steps. The exit code is 1 when there are errors or warnings.

### compare

`dossier compare left right [--by size_time|size|content] [--no-subfolders] [--tolerance SECONDS] [--exact-hour] [--same] [--sync MODE]
[--dry-run]` lists the differences between two folders: `only-left`, `only-right`, `left-newer`, `right-newer`, `different` (same time,
different content) and `type-differs` (a file against a folder). `--tolerance` is how close two times must be to count as the same
(default 2 seconds); a difference of exactly one hour (summer time on FAT drives) is ignored unless `--exact-hour`. `--same` lists the files that
are alike too. `--sync` makes the folders alike, in a direction: `update_right`, `update_left`, `both`, `mirror_right`, `mirror_left`
(the mirror modes also delete what is only on the other side, to the recycle bin). Combine with `--dry-run` to see the plan first.

### view (the picture viewer, not a command-line command)

`dossier view [--glass LOOK] [--scheme auto|light|dark] picture...` opens only the picture viewer, with no file manager window behind it: a
frameless window over the screen with the desktop showing through. One picture opens it with the other pictures of its folder following
(Right, Page Down and Space for the next, Left, Page Up and Backspace for the previous, the mouse wheel too; Esc closes); several pictures
open just those; a folder opens its first picture. A floating bar fades in when the mouse moves.

`--glass` is `frosted` (the default: a blurred picture of the screen under a dark layer), `dim` (the desktop sharp), `solid` (no transparency), a number 0
to 100 for how much shows through (0 is solid), or both as `frosted:60`. A look the computer cannot do falls back one step: frosted to
dim, dim to solid; a remote desktop session gets solid. Without parameters the look chosen in Settings > Appearance > Picture Viewer Glass
is used. The same viewer opens from the window with Files > View as Glass.

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
