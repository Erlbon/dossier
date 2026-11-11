# Dossier

A dual-pane file manager for Windows (and Linux, from a checkout), for people with servers and a tailnet. Four things no other file commander has together:

- **A plan before every change.** Every copy, move, rename and delete is worked out and shown before it happens; a name that is taken is asked about, file by file; nothing is overwritten that you did not choose.
- **Servers and your tailnet as ordinary folders.** SFTP, SCP, WebDAV, FTP, Google Drive and more, and the devices of your Tailscale network on the Home page, with their shared folders.
- **Folder notes.** A `README.md` in a folder is shown under its listing, like a repository page.
- **An assistant that only proposes.** A local MCP server lets an AI assistant look at the folders you list and propose changes; you see them in words and press Run (or, if you allow it, it works on its own inside strict limits).

Everything is built in: no plugins to find, install or keep up to date. Free software, GPL-3.0-or-later.

## Download

From the [releases page](https://github.com/Erlbon/dossier/releases): **`dossier-setup.exe`** installs it for you alone (no administrator rights) and starts in under a second; **`dossier.exe`** is the same program as one file, nothing to install, but it takes about three seconds to start. Either way it keeps its settings in your user profile, in a plain `dossier.ini`, never in the registry, and updates itself from Help > Check for Updates.

## What it does

- **Two panels, tabs, one selection.** Mark files in either panel; commands work on the marks of the panel you start them from. F3 view, F4 edit, F5 copy, F6 move (Ctrl+F5/F6 first show a box to copy elsewhere or only some files), F7 new folder, F8 delete; drag and drop; the clipboard.
- **Safe changes.** Every copy, move, rename and delete is planned, shown, then done; renames and same-drive moves can be undone; a name that is taken is asked about; copies can be read back and compared.
- **A Home page** with your drives (with lights that say whether they answer), places, pinned folders, network shares and servers.
- **Servers as folders:** SFTP, SCP, WebDAV, FTP and FTPS, Google Drive, and read-only OPDS book catalogues and Subsonic music servers. Devices of your Tailscale network are listed on the Home page, with their shared folders. Network drives can be mounted on a drive letter.
- **Sharing folders on the network** (Windows, through one administrator prompt): experimental and off until you switch it on in Settings > Drives and Sharing.
- **Archives as folders:** zip and 7z built in, RAR, ISO, tar and the rest through 7-Zip or NanaZip; change a zip in place; pack, unpack, convert.
- **Search, duplicates, compare and synchronize, batch rename, checksums, saved selections.**
- **A viewer** for text (any size, any encoding, column selection), pictures (with EXIF, in a full-window glass viewer), hex and Markdown; **an editor** for text; **columns and Properties** that read the tags inside music, comic and video files and write those of mp3, flac, ogg, opus, m4a and cbz files (`dossier tag`), and tags of your own on files.
- **Health checks** (Tools > Check Folder Health, `dossier check`): junk, names Windows or other systems cannot hold, empty files and folders, wrong extensions, damaged zips; fixes are plans like any other, and damaged files can go to a quarantine folder instead of the bin.
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

`python -m dossier --check` only checks that everything is installed and says what is missing. RAR and the other formats besides zip and 7z need 7-Zip or NanaZip. Windows 10 or 11, or Debian/Ubuntu, with Python 3.10 or newer. If you install with `pip install .` the same packages come with it, and `dossier` starts the program. Updating: `git pull` and the pip line again, since the shared Redactor package is pinned to a tag that moves. The Windows program updates itself: Help > Check for Updates (or switch on Help > Check for Updates Once a Day) downloads the new version, checks it against the checksum GitHub lists, and puts it in place (a bare `dossier.exe` swaps the file; an installed copy runs the new installer silently and starts again).

To build the exe yourself: `build_exe.bat` (or `python -m PyInstaller dossier.spec`); the installer: `build_installer.bat` (Inno Setup 6). A release is made with the Redactor family's release tool, `python -m redactor_common.release publish` (`RELEASE` in `dossier/core/version.py` names the release and its notes): it builds both with `build_release.bat`, publishes a pre-release with an `update-manifest.json`, checks that the previous release really updates itself to it, and only then makes it the latest.

## More

- What changed, build by build: [CHANGELOG.md](CHANGELOG.md)
- Feature specification: [docs/spec.md](docs/spec.md)
- Servers, the Home page and the reviews behind them: [docs/home-and-servers-review.md](docs/home-and-servers-review.md)
- Working notes and decisions: [CLAUDE.md](CLAUDE.md)
- Credits: [CREDITS.md](CREDITS.md)

Licence: GPL-3.0-or-later. Dossier is free and open source and will not be sold. Its function list follows an older file manager (The Next Tool); no code, text, graphics or name of that program is used.
