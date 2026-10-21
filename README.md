# Dossier

A dual-pane file manager for Windows (and Linux, from a checkout). Two folder panels side by side with tabs, one selection shared by both, a command line, the F-key bar, Markdown notes shown under the listing, and servers as folders. Free software, GPL-3.0-or-later.

## Download

The Windows program is `dossier.exe`, one file, on the [releases page](https://github.com/Erlbon/dossier/releases). Nothing is installed: put it where you like and start it. It keeps its settings in your user profile, in a plain `dossier.ini`, never in the registry.

## What it does

- **Two panels, tabs, one selection.** Mark files in either panel; commands work on the marks of the panel you start them from. F3 view, F4 edit, F5 copy, F6 move, F7 new folder, F8 delete; drag and drop; the clipboard.
- **Safe changes.** Every copy, move, rename and delete is planned, shown, then done; renames and same-drive moves can be undone; a name that is taken is asked about; copies can be read back and compared.
- **A Home page** with your drives (with lights that say whether they answer), places, pinned folders, network shares and servers.
- **Servers as folders:** SFTP, SCP, WebDAV, FTP and FTPS, and read-only OPDS book catalogues and Subsonic music servers. Devices of your Tailscale network are listed on the Home page.
- **Archives as folders:** zip, 7z and the rest through 7-Zip; change a zip in place; pack, unpack, convert.
- **Search, duplicates, compare and synchronize, batch rename, checksums, saved selections.**
- **A viewer** for text (any size, any encoding, column selection), pictures (with EXIF), hex and Markdown; **an editor** for text; **columns and Properties** that read the tags inside music, comic and video files, and tags on files.
- **Folder notes** (`README.md`, `about.md`, ...) shown under the listing, and folder layouts that remember how each folder is shown.
- **A command line** in the same program (`dossier ls`, `find`, `copy`, `dups`, `compare`... with `--dry-run` and `--json`), see [docs/cli.md](docs/cli.md), and a local **MCP server** (`dossier mcp`) that lets an AI assistant look at your files and propose changes you approve, see [docs/assistant.md](docs/assistant.md). Both are off or read-only until you say otherwise.
- **Looks yours:** light, dark or the system's scheme, two icon sets (or your own), fonts, bold on or off, and every bar (programs, function keys, command line) can be dragged to where you want it.

## Run it from a checkout

```
git clone https://github.com/Erlbon/dossier
cd dossier
python -m pip install -r requirements.txt
python -m dossier
```

`python -m dossier --check` only checks that everything is installed and says what is missing. 7z archives also need `python -m pip install py7zr` (or 7-Zip on the path); RAR and the other formats need 7-Zip. Windows 10 or 11, or Debian/Ubuntu, with Python 3.10 or newer. If you install with `pip install .` the same packages come with it, and `dossier` starts the program. Updating: `git pull` and the pip line again, since the shared Redactor package is pinned to a tag that moves.

To build the exe yourself: `build_exe.bat` (or `python -m PyInstaller dossier.spec`). A release is made by pushing a tag `v` + `RELEASE` from `dossier/core/version.py`; the workflow tests, builds and publishes it.

## More

- What changed, build by build: [CHANGELOG.md](CHANGELOG.md)
- Feature specification: [docs/spec.md](docs/spec.md)
- Servers, the Home page and the reviews behind them: [docs/home-and-servers-review.md](docs/home-and-servers-review.md)
- Working notes and decisions: [CLAUDE.md](CLAUDE.md)
- Credits: [CREDITS.md](CREDITS.md)

Licence: GPL-3.0-or-later. Dossier is free and open source and will not be sold. Its function list follows an older file manager (The Next Tool); no code, text, graphics or name of that program is used.
