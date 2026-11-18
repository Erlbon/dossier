# Dossier against the Mac and Linux file managers, 2026-11-18

A comparison of Dossier (build 2026-11-18#09, the first build ready for a Mac and a Linux tarball) with the file commanders and file managers people use on macOS and Linux. It asks one question, the owner's yardstick: **what does a Mac or Linux user miss in Dossier, without learning a system?** Total Commander's depth does not count; what an ordinary user takes for granted does.

**Compared with:**
- **Cross-platform:** Double Commander (DC), muCommander, Midnight Commander (mc), far2l, fman.
- **Mac:** Commander One, Marta, ForkLift, Path Finder, and Finder itself.
- **Linux:** Krusader, Dolphin, Nautilus (GNOME Files), Thunar.

**How it was checked.**
- **Dossier:** from the code, not the docs, for every gap below (file and line given where it matters). Read first: `README.md`, `docs/spec.md`, `CLAUDE.md` (including "Mac and Linux builds", cards 35-44), `CHANGELOG.md`, `docs/comparison-review-2026-11-05.md` and `docs/functionality-review-2026-11-05.md`, so nothing built or decided is proposed again.
- **The others:** from their public descriptions and documentation, and from their known feature sets. A few facts were checked on the web today (sources at the end). Nothing was downloaded, installed or decompiled; everything here is in our own words.
- **Not checked on a real Mac or Linux desktop:** the owner's colleague tries the first Mac build. Where a gap depends on how the system behaves at run time, it says "to check".

**Two kinds of gap.** Each item below is marked:
- **[Platform]:** behaviour the system itself teaches, which a Mac or Linux user expects of any program that shows files (Quick Look on Space, the Trash and Put Back, Open With, eject, the desktop's own folder names). Missing one feels like a bug, not a missing feature.
- **[Feature]:** an ordinary feature some of the others have. Missing one is a choice.

**Effort:** small = under 2 minutes of work, medium = up to 10, large = more than 10, as in the earlier reviews.

**The decisions** go on the decision page as questions 45-56 (the last card was 44). This file holds the same proposals and the reasons.

---

## Overall

- **The commander part is not where Dossier is behind.** Two panels, tabs, F-keys, a command line, compare and sync, batch rename, archives as folders, servers as folders, search, duplicates and checksums are all there, and most are built in where DC, Krusader and mc reach them through plugins or external tools.
- **The gap is the desktop around it.** Dossier was built on Windows, and on the Mac and Linux it does not yet do several things that Finder, Nautilus and Dolphin do without being asked:
  - it cannot open the Trash or put a file back from it;
  - it cannot eject a USB stick or unmount a share;
  - shares and phones mounted by the Linux desktop (GVfs) are invisible to it, and its own Mount... works only on Windows;
  - Open With on the Mac and Linux offers only the tools bar's programs, not the system's;
  - a Mac `.app` opens as a folder, and a Linux `.desktop` launcher as a text file;
  - there is no Quick Look;
  - permissions cannot be changed;
  - the Home page uses English folder names, so a Norwegian Ubuntu's `Skrivebord` and `Nedlastinger` are not found.
- **None of these is large on its own,** and most live in `core/platform.py`, as the platform rule wants. Together they decide whether a Mac or Linux user feels at home in the first ten minutes.

## 1. What the others have and Dossier lacks

### 1.1 Looking at a file

- **[Platform] Quick Look with Space (Mac); GNOME's previewer with Space (Nautilus with Sushi).** Finder, ForkLift, Path Finder and Marta show the system's preview on Space; Nautilus does the same when the Sushi previewer is installed. In Dossier, Space marks the item and adds up a folder's size (`gui/panel.py:373`, card 20), as in every orthodox commander. Commander One faced the same clash and kept Space for marking, moving Quick Look to another key (Macworld's review of 2.1). Quick View in a panel was dropped (card 24); this is the system's own preview window, not a panel. **Card 45.**
- **[Feature] A preview pane beside the list** (ForkLift, Path Finder, Finder's preview column, Dolphin's Information panel). Dropped as card 24 (Quick View); not proposed again.

### 1.2 Deleting and the Trash

- **[Platform] Open the Trash, Put Back, Empty.** Finder has Put Back; Nautilus, Dolphin and Thunar show the Trash as a place with each item's original location and a Restore button, and an Empty button. DC and Krusader open the Trash too. Dossier sends files to the bin (`send2trash`) and says so in every plan, but cannot show the bin, restore from it or empty it. The undo of an overwrite even tells the user to go and find the older file in the bin themselves. On Linux the bin's format is a published standard (a `files` folder and a `.trashinfo` record per item, under `~/.local/share/Trash` and each drive's `.Trash-<uid>`); on Windows Dossier already reads the `$I` records (`core/forensic.py`). On the Mac the original place of a file is kept in Finder's own private records, and reading `~/.Trash` needs Full Disk Access, so Put Back there belongs to Finder. **Card 46.**

### 1.3 Drives, shares and phones

- **[Platform] Eject and unmount.** Every Mac and Linux file manager has an eject button beside a removable drive or a share (Finder's sidebar, Nautilus and Dolphin's places, Thunar's side pane, Commander One's drive list). Dossier lists drives and shares (`core/platform.py:175-275`) but has no Eject or Unmount anywhere (no code for it). Pulling a stick out without ejecting it is how files get lost on both systems. **Card 47.**
- **[Platform] Shares and phones mounted by the Linux desktop.** On GNOME, Cinnamon and Xfce, a share opened in the file manager, a phone (MTP), a camera or a Google account is mounted by GVfs under `/run/user/<uid>/gvfs/`. Dossier skips everything under `/run/user` (`core/platform.py:141`), so none of them appears on the Home page, though they are ordinary folders a program can read. KDE mounts through KIO, which other programs see only when it is set to mount through FUSE (`kio-fuse`); then they appear under `/run/user/<uid>/kio-fuse-*`, also skipped. **Card 48.**
- **[Platform] Mount a share on the Mac and Linux.** Network > Mount... works only on Windows: on the others it says "Mounting from Dossier is only built for Windows" (`core/mounting.py:73-75`). On the Mac, `open smb://server/share` lets the system mount it under `/Volumes` with its own password prompt and Keychain; on Linux, `gio mount smb://server/share` does the same through GVfs and the desktop's keyring. No password ever passes through Dossier, as its rule for mounting requires. **Card 48.**
- **[Feature] Phones on the Mac (MTP), iPhones** (Commander One Pro, ForkLift). A new protocol: waits behind card 3 (core before new areas). Not proposed. On Linux, card 48 makes the desktop's own phone mount visible without a new protocol.
- **[Feature] Cloud services as folders** (Commander One Pro and ForkLift: Dropbox, OneDrive, S3 and more; Dolphin and Nautilus through KIO and GNOME Online Accounts). Dossier has Google Drive and WebDAV (and so Nextcloud). Further services are new protocols: card 3. Not proposed. On Linux, a Google account added to GNOME appears through GVfs once card 48 is built.

### 1.4 Opening files and programs

- **[Platform] Open With the system's programs.** Finder lists every program that says it opens the type, the default first, then "Other..."; Nautilus, Dolphin and Thunar list the programs whose `.desktop` files name the type, from the shared XDG MIME database. Dossier's Open With is the tools bar's programs, plus "Choose Another Program..." on Windows only (`core/platform.py:481-486` returns None elsewhere). Enter already opens the default program on all three (`open`, `xdg-open`). **Card 49.**
- **[Platform] Mac apps and packages are files.** Finder shows `Mail.app`, a `.bundle`, a Photos library or a Keynote document as one file; double-clicking an app starts it, and "Show Package Contents" goes inside. Commander One and ForkLift do the same. Dossier knows no bundles (`.app` appears only in `core/terminals.py`), so Enter on an app walks into its `Contents` folder. **Card 50.**
- **[Platform] Linux launchers and programs.** Nautilus, Dolphin and Thunar show a `.desktop` launcher by its own name and icon and start it on a double-click (Nautilus asks once, "Trust and Launch"); an executable script asks whether to run it, run it in a terminal, or show it. Dossier shows the launcher as `firefox.desktop` and opens it as text. **Card 50.**
- **[Feature] Make Dossier the program that opens folders.** On Linux a file manager registers for `inode/directory`, so "Show in folder" in a browser or an editor opens it (Dolphin, Nautilus, Thunar, DC and Krusader can all be the default). The Linux tarball has no launcher at all yet, so Dossier is in no application menu and in no Open With. On the Mac this cannot be done for Finder's own folder opening without hacks, and no Mac commander claims it. **Card 52 (Linux only).**

### 1.5 Keys

- **[Platform] Finder's and the Linux desktops' own keys.** Card 39A made the Mac follow the Mac (Ctrl becomes Cmd) and kept the F-keys. What Mac users press without thinking is still missing: Cmd+Backspace to move to the Trash (in Dossier, Cmd+Backspace is "Root of the Drive", `gui/menus.py:229`, the one clash that surprises), Cmd+Up for the parent folder, Cmd+Down to open, Cmd+Shift+G for Go to Folder, Cmd+Shift+. for hidden files, Cmd+I for Get Info, Cmd+Shift+N for a new folder. On Linux, Nautilus, Dolphin and Thunar share Alt+Up, Alt+Left and Alt+Right, Ctrl+Shift+N, and F2 to rename; Dossier already has Ctrl+H for hidden files and Ctrl+L to type a path, as they do. **Card 51.**

### 1.6 Properties and permissions

- **[Platform] Change permissions.** Finder's Get Info (Sharing and Permissions), Nautilus, Dolphin, Thunar, DC, Krusader, mc (Ctrl+X C, chmod) and muCommander all change who may read, write and run a file. Dossier shows the permissions in the Attributes column (`rwxr-xr-x`) but can change only read-only (`core/filetimes.py:162`). Most often missed in practice: making a downloaded script runnable. **Card 53.**

### 1.7 Sharing and sending

- **[Platform] The Mac's Share menu** (AirDrop, Mail, Messages, Notes), found in Finder's right-click menu and in ForkLift and Path Finder. Linux has no common equivalent (KDE's Share menu, Nautilus's "Send to..." through `nautilus-sendto`, Thunar's "Send To"). Dossier has none. Calling the Mac's share sheet needs the system's Objective-C classes, which Dossier reaches today only through small `ctypes` calls. **Card 54.**
- **[Platform] Services and folder actions** (the Mac's Services menu, Nautilus scripts, Dolphin service menus, Thunar custom actions). Dossier's own tools bar, with its placeholders, covers the same need in its own menus. Not proposed.

### 1.8 Terminal

- **[Feature] A terminal inside the window that follows the folder** (Dolphin's F4 panel, Krusader's, Marta's two-way synced terminal, mc's Ctrl+O, far2l's). Dossier has the command line under the panels and opens the system's terminal there (Terminal or iTerm on the Mac, card 38A). An embedded terminal is a new area under card 3. **Card 55.**

### 1.9 Smaller platform behaviour that one of the owner's rules already decides (no card; fixes)

These follow from rules already set, so they are listed once and built as fixes:
- **The desktop's own folder names on the Home page.** `core/home.py:40` looks for `Desktop`, `Documents`, `Downloads`, `Pictures`, `Music` and `Videos` by their English names. On Linux the real names are in `~/.config/user-dirs.dirs` (on a Norwegian Ubuntu: `Skrivebord`, `Dokumenter`, `Nedlastinger`...), so they are not found. On the Mac the folders are English on disk, but iCloud Drive (`~/Library/Mobile Documents/com~apple~CloudDocs`) and Applications are missing from a page that already lists OneDrive, Dropbox and Google Drive. Rule: Linux is a tested second platform, and names are never assumed (CLAUDE.md, Platforms).
- **The Mac's hidden flag.** Finder hides `~/Library` and other items by a file flag, not by a dot. Dossier hides only dot-names on the Mac, so View > Show Hidden and System Files off still shows them. Rule: the same switch already hides Windows' hidden attribute; the Mac's flag is its counterpart (`core/platform.py`).
- **AppleDouble files (`._name`).** A Mac writes them beside every file it copies onto a USB stick or a share that cannot hold its metadata. They should count as hidden on all three systems, and as junk in Health, beside `.DS_Store`, which is already there (`core/health_rules.py:16`). Rule: Health's junk list.
- **To check on the Mac: do Finder tags survive a copy?** Card 37A put Dossier's tags in Finder's own extended attribute. Python's own copy on the Mac copies the data only, not the extended attributes, so a copy made by Dossier may lose the tags, the colour labels and "where from". To check with the colleague's first build; if they are lost, the copy keeps them (rule: 37A, tags that show in Finder).

### 1.10 Already decided, so not proposed again

- **A Quick View panel** (DC, Krusader, Dolphin, ForkLift): dropped, card 24.
- **A folder tree beside the panel** (Finder's sidebar is not a tree; Dolphin, Krusader, DC, Thunar have one): built as the popup only, card 26.
- **Panels stacked, one panel, more panels:** dropped, card 10. This covers Finder's column view and Marta's one-panel mode too.
- **Synchronized browsing** (DC, Krusader, mc): dropped, card 27.
- **Every key editable** (DC, Marta, Krusader): dropped, card 6.
- **Plugins** (DC, mc's VFS, Marta's Lua, fman, Krusader's KIO, Dolphin's service menus): no plugin system, ever (card 5).
- **The system's search index** (Spotlight in Finder, Baloo in Dolphin, Tracker in Nautilus). The Windows counterpart, Everything, was dropped with card 31 ("just drop it"). Not proposed; the owner can raise it for the Mac or Linux if he wants it.
- **Translations** (all of them ship in many languages): not planned (C10).
- **Disk usage maps** (Krusader's Disk Usage, Dolphin with Filelight): Folder Sizes and the share column, card 32 (no bars).
- **Undo of copies and deletes** (Finder and Nautilus undo more): undo is small on purpose (2026-10-20).
- **Recents and Starred** (Finder's Recents, Nautilus's Recent and Starred): Dossier has the Last Opened column and tags on files. Not proposed now; a candidate after card 3's week of real use.

## 2. What Dossier has that they lack

Against this group the four selling points of the November review hold, and three more stand out:
- **A plan before every change.** None of the twelve shows the whole plan first. Finder, Nautilus and Dolphin copy at once and ask per conflict; DC, Krusader and mc the same; ForkLift and Path Finder have a transfer queue, not a plan.
- **Servers and the tailnet as folders, built in and free.** SFTP, SCP, WebDAV, FTP and FTPS, Google Drive, OPDS and Subsonic, plus the Tailscale devices on the Home page. Commander One puts its servers behind the Pro licence; ForkLift and Path Finder are paid; Marta has none built in; Finder has only SMB, AFP, NFS and WebDAV. Nobody lists tailnet devices or reads OPDS or Subsonic.
- **Folder notes** rendered under the listing: none of them.
- **An assistant that only proposes** (the MCP server): none of them.
- **Health checks and quarantine:** none of them. Krusader's checksum tools and Path Finder's are the nearest.
- **Tags on music, comics and books read and written in place,** with columns: Dolphin reads some through Baloo, the Mac commanders mostly not at all.
- **The same program on all three systems, free and GPL, with no plugins.** DC and muCommander are cross-platform and free too, but depend on plugins (DC) or are Java (muCommander). Commander One, ForkLift, Path Finder and fman are paid; Marta is in beta with a licence expected later; Krusader and Dolphin are tied to KDE, Nautilus to GNOME, Thunar to Xfce; mc and far2l are text-mode.
- **Finder tags and the Linux desktop's tags in the same column** (cards 37A and the `user.xdg.tags` attribute), with Windows' own store beside them: no other cross-platform manager writes tags that the Mac's Finder and the Linux desktop both see.

## 3. The decisions (questions 45-56)

### 45. Quick Look on the Mac (and the GNOME previewer on Linux)
- **A:** File > Quick Look with Cmd+Y (Finder's other key for it) opens the system's own preview window for the item under the cursor (`qlmanage -p` on the Mac; on Linux the GNOME previewer when it is installed, else the entry is not shown). Space keeps marking, as card 20 decided.
- **B:** on the Mac only, Space becomes Quick Look as in Finder, and marking moves to Insert and Cmd+click.
- **Keep as is:** F3 is the viewer.
- **Recommendation: A.** Mac users get the preview they know under Finder's second key, and the commander keys stay the same on all three systems. Effort: small.

### 46. The Trash: open it, put back, empty
- **A:** a Trash place on the Home page (the Recycle Bin on Windows) opens as a read-only folder: each item with where it came from and when it was deleted; Put Back as a plan (asking when the old place is taken now) and Empty the Trash (one confirmation with the count and size, permanent). On all three systems; on the Mac Put Back only for what Dossier itself deleted (it would keep its own record of where from), and reading the Trash asks for Full Disk Access.
- **B:** as A on Linux and Windows, whose bins have open formats. On the Mac, the Home page's Trash opens the Trash in Finder, where Put Back works for everything.
- **Keep as is.**
- **Recommendation: B.** Linux and Windows get the whole thing from records Dossier can read; on the Mac the right Put Back is Finder's, and a Full Disk Access prompt for it would put users off. Effort: large.

### 47. Eject and unmount
- **A:** an eject mark on each removable drive and network mount on the Home page and in the drive menu, and Eject in its right-click menu, on all three systems (the Mac's `diskutil eject`, Linux's `udisksctl` or `gio mount --eject`, Windows' safe removal). It first waits for Dossier's own copies to that drive and says so; when another program holds a file open, it says the system's reason.
- **B:** as A, on the Mac and Linux only; Windows keeps its tray icon.
- **Keep as is.**
- **Recommendation: A.** The same button on all three is easier to explain, and Windows users unplug sticks too. Effort: medium.

### 48. Shares and phones mounted by the Linux desktop, and Mount... on the Mac and Linux
- **A:** GVfs mounts (and KDE's through `kio-fuse`) appear on the Home page: shares as network drives, with the "delete is permanent" warning; phones and cameras as removable. Network > Mount... works on Linux through `gio mount` and on the Mac through the system's own `open smb://...`, with the system's password prompt and keyring.
- **B:** only show the GVfs mounts; mounting stays with the system's own file manager.
- **Keep as is.**
- **Recommendation: A.** Today a Linux user who opens a share in Files does not see it in Dossier at all, and the Mount... that Windows users have is a dead end. Effort: medium.

### 49. Open With on the Mac and Linux
- **A:** Open With lists the programs the system knows for the type, the default first (Linux: the `.desktop` files and `mimeapps.list` of the XDG standard, read directly; Mac: Launch Services through the system library), then the tools bar's programs, then Other Program... to pick any program.
- **B:** only Other Program...: a file picker in Applications (Mac) or a list of installed launchers (Linux), run on the clicked file.
- **Keep as is.**
- **Recommendation: A.** It is what every Mac and Linux file manager shows, and it needs no setup. Effort: medium.

### 50. Mac apps and packages, Linux launchers and programs
- **A:** on the Mac, apps and packages show as one file with their own name and icon; Enter starts or opens them, and the right-click menu has Show Package Contents. On Linux, a `.desktop` launcher shows its own name and icon and Enter starts it (asking once per launcher, as Files does); a runnable file of no known type asks Run, Run in a Terminal or View.
- **B:** the Mac part only.
- **Keep as is.**
- **Recommendation: A.** Walking into `Mail.app` or reading `firefox.desktop` as text is the first thing a Mac or Linux user would call a bug. Effort: medium.

### 51. Finder's and the Linux desktops' own keys, as second keys
- **A:** on the Mac, Finder's keys as second keys: Cmd+Backspace moves to the Trash (Root of the Drive moves to Cmd+Shift+Up), Cmd+Up, Cmd+Down, Cmd+[ and Cmd+] (back and forward), Cmd+Shift+G, Cmd+Shift+., Cmd+I, Cmd+Shift+N. On Linux: Alt+Up, Alt+Left, Alt+Right, Ctrl+Shift+N. The F-keys stay first everywhere; the menu-rule test checks clashes, and none uses Ctrl+Alt.
- **B:** the Mac part only.
- **Keep as is.**
- **Recommendation: A.** Muscle memory from Finder and Files is the first thing people bring; as second keys they cost nothing to those who use the F-keys. Effort: small.

### 52. A launcher for the Linux tarball, and Dossier as the folder program
- **A:** Dossier offers, on its first start from the tarball, to add itself to the application menu (a launcher and its icon in the user's own folders, nothing system-wide). Settings has "Open folders with Dossier" (off by default), which makes other programs' "Show in folder" open Dossier, with a way back.
- **B:** the launcher and icon only.
- **Keep as is:** run it from the unpacked folder.
- **Recommendation: A.** A program missing from the menu is not installed in a Linux user's eyes; the folder switch is off until he turns it on. Effort: medium.

### 53. Change permissions on the Mac and Linux
- **A:** a Permissions part in Properties: owner, group, and read, write and run for owner, group and others as ticks; "also for everything inside", with folders keeping their run bit; done as a plan. The owner can be changed only where the system allows it (no `sudo`).
- **B:** only one tick, "Allow running as a program", in Properties and the right-click menu.
- **Keep as is.**
- **Recommendation: A.** Every Linux and Mac file manager has it, and Dossier already shows the bits it cannot change. Effort: medium.

### 54. The Mac's Share menu
- **A:** File > Share on the Mac opens the system's share sheet (AirDrop, Mail, Messages) for the marked files; on Linux, Share > Send by Mail through the desktop's mail program.
- **B:** the Mac part only.
- **Keep as is:** Show in Finder, then Share there.
- **Recommendation: Keep as is for now.** It needs a larger bridge to the Mac's Objective-C classes than anything Dossier has, and Show in Finder already gets there in one step; ask again after the colleague's report. Effort: large.

### 55. A terminal inside the window
- **A:** a terminal panel under the two panels (Dolphin's F4 panel, mc's Ctrl+O), following the active panel's folder, shown and hidden by one key.
- **B:** later, after card 3's condition (the Yes cards built and a week of real use).
- **Keep as is:** the command line, and the system's terminal opened in the folder.
- **Recommendation: B.** Developers like it, but it is a new area, and the command line already covers the everyday case. Effort: large.

### 56. Do the platform cards count as core under card 3?
- **A:** yes. Cards 45-53 are platform behaviour that makes the Mac and Linux builds do what their users take for granted; they go on beside the colleague's report as fixes do, not after the week of real use.
- **B:** no. They wait like new areas, until the Yes cards are built and a release has had a week of use.
- **Recommendation: A.** Card 35A already put "fix what the Mac breaks" first; most of these are what an ordinary user would report as broken.

## Sources (web, checked 2026-11-18)
- Commander One: Quick Look on another key than Space, Finder tags since 3.2, servers and MTP in Pro: https://www.macworld.com/article/3409155/commander-one-2-1-review-mac-file-manager-now-works-with-ios-devices.html, https://pcweenies.com/?p=16369, https://wiki.eltima.com/user-guides/commander/commander-one-from-the-mac-app-store.html, https://en.wikipedia.org/wiki/Commander_One
- ForkLift 4: preview pane and info, sync, Share from the right-click menu: https://blog.binarynights.com/2023/04/04/forklift-4-beta-is-finally-here/, https://alternativeto.net/news/2024/11/forklift-4-2-introduces-improved-color-tags-remote-pane-control-and-sftp-updates/
- Marta: Lua API, themes, built-in terminal synced with a pane, beta: https://marta.sh/, https://www.wearedevelopers.com/magazine/760-tool-showcase-marta-sh-a-fast-native-fully-customisable-and-extensible-two-panel-file-commander
- Path Finder: dual pane, Drop Stack, batch rename: https://cocoatech.io, https://tidbits.com/watchlist/path-finder-10-0/
- Dolphin: split view, terminal panel, KIO, Places with mount and unmount: https://en.wikipedia.org/wiki/Dolphin_(file_manager), https://apps.kde.org/dolphin
- Krusader: Synchronizer, KrViewer, UserActions, Disk Usage: https://docs.kde.org/trunk_kf6/en/krusader/krusader/index.html
- The rest (DC, muCommander, mc, far2l, fman, Finder, Nautilus, Thunar, the freedesktop Trash and XDG user-dirs standards, GVfs): from their known feature sets and the published standards, not opened today.
