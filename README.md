# Dossier

A multi-window file manager for Windows and Linux (Debian/Ubuntu). Several freely arranged folder windows, one selection shared by all of them, Markdown notes shown under the listing, viewers for text, CSV and SQLite, and in-place metadata editing for EPUB, CBZ, MP3 and video.

## Run it from a checkout

```
git clone https://github.com/Erlbon/dossier
cd dossier
python -m pip install -r requirements.txt
python -m dossier
```

`python -m dossier --check` only checks that everything is installed and says what is missing. 7z archives also need
`python -m pip install py7zr` (or 7-Zip on the path); RAR and the other formats need 7-Zip. Windows 10 or 11, or Debian/Ubuntu,
with Python 3.10 or newer. If you install with `pip install .` the same packages come with it, and `dossier` starts the program.
Updating after a new version: `git pull` and the pip line again, since the shared Redactor package is pinned to a tag that moves.

- Command line: `dossier ls`, `info`, `find`, `checksum`, `copy`, `move`, `delete`, `dups`, `compare` (with `--dry-run` and `--json`); see [docs/cli.md](docs/cli.md)
- Feature specification: [docs/spec.md](docs/spec.md)
- Working notes and decisions: [CLAUDE.md](CLAUDE.md)

Licence: GPL-3.0-or-later. Dossier is free and open source and will not be sold. Its function list follows an older file manager (The Next Tool); no code, text, graphics or name of that program is used.
