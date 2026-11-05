# Dossier against the other file commanders, 2026-11-05

A critical comparison of Dossier (build 2026-11-05#01) with Total Commander 11 (TC), Directory Opus 13 (DOpus), Double Commander 1.1 (DC) and Far Manager 3 (with far2l, its Linux port). Section 4 adds FreeCommander XE and Just Manager, the two you have used for five years, which are the comparison that counts. It covers what Dossier does that they do not (its selling points), where it is behind (its weaknesses), and a few decisions that follow from both.

**How it was checked.**
- **Dossier:** facts come from the code and the repository:
  - 37,000 lines of Python and 1,879 tests;
  - first commit 2026-10-19, 212 commits, two releases (0.4 and 0.5);
  - `dist\dossier.exe` is 61 MB;
  - starting it only to print `--version` took 3.3 and 3.7 seconds (measured twice today on this PC).
- **The others:** from their known feature sets. Five facts were checked on the web today (sources at the end):
  - TC's SFTP is a separate plugin;
  - DOpus has FTP built in, while SFTP/SSH is a paid extra, and its updates now need a subscription;
  - DC has SFTP built in and uses TC's plugins;
  - far2l has NetRocks (SFTP, SCP, FTP, SMB, NFS, WebDAV);
  - no other commander has an MCP server.
- **Not measured:** listing speed on huge folders and memory use. Nothing below claims either.

**Effort:** small = under 2 minutes of work, medium = up to 10, large = more than 10, decision = your call, no code.

**Decisions (the owner, 2026-11-05, on the decision page).**
- **Yes:**
  - 1: lead the README with what is unique, at the next release;
  - 2: make it start fast;
  - 3: core before new areas;
  - 4: measure big folders;
  - 5: no plugins, features built in;
  - 9: colour files by type.
- **Later (stay open):** 6 (every key can be changed), 8 (a Linux package), 10 (one panel, or panels stacked).
- **No:** 7 (Norwegian as a second language).
- **What follows for the code and docs:**
  - **Card 3** means no new feature area until the functionality review's Yes cards are built and a release has had a week of use. Cards 33 and 34 of that review (the assistant acting on its own, commands on the server) are decided cards, not new areas.
  - **Card 5** goes into the spec and CLAUDE.md "Decided": A7 is dropped, and V9 keeps only the mapping of a file type to a program.
  - **Card 7** goes into the spec: C10 is not planned.

**The measure (the owner, 2026-11-05).** Total Commander is not the benchmark: "It is technically strong, but the usability is low." The question for Dossier is whether an ordinary user can do the job without learning a system, not how many features it matches. Plugins count against usability: "complicated and often outdated". So a feature the others only have through a plugin counts as missing from them, and building it in counts for Dossier.

**Overall.**
- **Different, yes:** Dossier does not try to match Total Commander feature for feature, and should not. It is a different kind of commander:
  - safety first (a plan before every change);
  - servers and the tailnet as ordinary folders;
  - text inside folders (notes);
  - an assistant that can only propose.
- **Where it is unique:** no competitor checked has all four, and none has the tailnet list, the folder notes or the MCP server.
- **Where it loses, plainly:**
  - **Maturity:** 17 days old against 30 years. Five ways to lose a file were found and fixed only yesterday.
  - **Start-up:** seconds against instant.
  - **Everyday commander depth:** the gaps of today's functionality review.
  - **Reach:** one language, Linux only from a checkout.
- **What would sell it:** being the safe commander for people with servers and a tailnet, that works without setup, plugins or a manual. That depends on the core being as dependable as the others first.

---

## 1. Selling points (what the others do not have)

- **Every change is a plan you see first.** Copy, move, delete, rename, sync, Health fixes and the assistant's proposals are all planned, shown, then run (`core/ops.py`). Around the plans:
  - a real per-file conflict dialog;
  - verify by reading back;
  - a queue that pauses and resumes after a crash;
  - warnings that say when a delete or an overwrite is permanent (network drive, USB stick).

  TC, DC and Far copy straight away and ask per conflict. DOpus has an undo list. None shows the whole plan first.
- **Servers and the tailnet are folders.** SFTP, SCP, WebDAV, FTP/FTPS and Google Drive are built in. So are the read-only OPDS book catalogues and Subsonic music servers. The Home page also has:
  - Tailscale devices, with their shared folders;
  - another computer's shares;
  - mounting on a drive letter.

  How the others compare: TC needs plugins (SFTP is one), DOpus charges extra for SFTP, DC and far2l have SFTP built in, and none lists tailnet devices or reads OPDS or Subsonic. For the audience you named (programmers and tailscalers) this is the lead feature.
- **Folder notes.** A folder's `README.md` or `about.md` is shown under its listing, like a repository page, and can be edited in place (`core/notes.py`). None of the four does this (DOpus has file descriptions, not rendered notes).
- **An assistant that can only propose.** `dossier mcp` lets an AI assistant read your files and propose changes. The window rebuilds each proposal as a plan, and nothing runs until you press Run. It is off by default and limited to the folders you list. No other commander has an MCP server. DOpus's scripting is more powerful, but it is scripting, not an assistant with a guard.
- **A command line that is the same program.** `dossier ls/find/copy/dups/compare/check/tag` run on the same core as the window, with `--dry-run` and `--json`. TC and DC have command-line switches, not a scriptable CLI. Far is a console program, but its commands are its panels.
- **Library-aware.** Several features read the files themselves:
  - tag columns and tag writing (mp3, flac, ogg, opus, m4a, cbz) through the shared Redactor writer;
  - Health checks (junk, unsafe names, wrong extensions, damaged zips);
  - quarantine;
  - checksums and duplicates.

  DOpus matches the tag columns and editing, and TC needs plugins for them. The Health checks are Dossier's own.
- **One selection across panels and folders.** Marks are kept by path, survive leaving a folder, can be saved by name, and work across both panels (`core/selection.py`). In TC and DC the marks go when you change folder.
- **Built in, not plugged in.** The servers, archive formats, tag columns, checksums and viewers that TC users fetch as plugins are part of Dossier, made and updated with it, in the same menus and settings. Nothing to find, install, match to a version or see go stale. For an ordinary user this is the difference between a feature that exists and one that does not.
- **Free, GPL, Windows and Linux.**
  - TC is paid (a lifetime licence, about 42 euros plus VAT).
  - DOpus is paid, with a subscription for updates.
  - DC (GPL) and Far (BSD) are free as well.

## 2. Weaknesses (where the others are ahead)

- **Start-up and size.** The one-file exe is 61 MB, and printing its version takes 3.3-3.7 seconds: Windows unpacks Python and Qt before anything runs. TC (a few MB) and Far open at once; DC and DOpus well under a second. A commander is opened and closed all day, so this is felt every time. The per-user installer you are building should help (it installs unpacked), but that is not measured yet.
- **The everyday commander flows are behind.** These are today's functionality review, decided but not built:
  - F5 cannot be pointed anywhere but the other panel;
  - F4 cannot use another editor or reach a server file;
  - Unpack takes one archive;
  - tabs have no menu;
  - no folder tree, no Quick View.

  TC, DC and Far users notice these in the first hour.
- **Young, so not yet trusted.** Dossier is 17 days old, has one user and two releases. The code review of 4 Nov found five ways to lose a file, fixed that day. TC dates from 1993 and Far from 1996: millions of users have found their bugs. Trust in a file manager is earned by time without accidents, and no feature replaces that.
- **Less to customise.**
  - **Keys:** only the function keys can be reassigned (`core/fkey_config.py`), not every key (spec C1).
  - **Menus and toolbars:** there is no user menu or button bar beyond the tools bar.
  - **Looks:** light or dark only (sepia and high contrast, spec C9, are not built).

  DOpus can change almost everything, and TC and DC have editable button bars and menus. Under the usability measure this weighs less than it looks: good defaults matter more than settings most users never open.
- **English only.** No translations (spec C10). TC, DC and Far ship in dozens of languages, Norwegian included.
- **Linux is a checkout, not a package.** It runs from source on Debian/Ubuntu, but the tarball has never been built. DC ships AppImage, deb and rpm, and far2l is in the distributions.
- **Breadth before depth.** Seven protocols, Windows sharing through UAC, Health, tag writing, an MCP server and a glass picture viewer arrived in 17 days. The usability review of 4 Nov already warned that features arrive faster than they are used. Sharing has not yet been run for real.
- **One developer.** Dossier depends on you (and Claude). TC is also one developer, but after 30 years. DC and Far have teams and forks.
- **Undo is small on purpose** (renames, same-drive moves, new folders). This is a choice, not a fault: the plan and the bin are the safety. But DOpus users used to undoing a copy will miss it, and the README should say why.

## 3. Feature by feature

- **Two panels, tabs, F-key bar, command line:** all five have them (Far's tabs come from plugins, DOpus's two panels are a mode).
- **A plan shown before every change:** Dossier only.
- **Undo:** Dossier: small, on purpose. TC and DC: none. DOpus: an undo list. Far: none.
- **SFTP and SCP:**
  - Dossier and DC: built in;
  - TC: a plugin;
  - DOpus: a paid add-on;
  - Far: NetBox (Windows) or NetRocks (far2l).
- **WebDAV, Google Drive:** Dossier built in. The others mostly through plugins, or not at all.
- **Tailnet devices, OPDS, Subsonic:** Dossier only.
- **Archives as folders:** all five. Writing into zips: all five. Writing into 7z and RAR: TC, DC and DOpus, with external tools.
- **Folder tree:** TC, DOpus, DC and Far. Dossier: not yet (card 26 of the functionality review).
- **Quick View panel:** TC, DC, Far and DOpus (as a viewer pane). Dossier: not yet (card 24).
- **Text compare:** TC, DC and DOpus. Dossier: decided, not built (card 7).
- **Multi-rename with tags:** TC, DOpus and DC. Dossier: decided, not built (card 5).
- **Plugins:** TC, DC, Far and DOpus depend on them for much of the list above. Dossier builds those features in and has no plugins, on purpose (card 5).
- **Scripting:** DOpus (JScript/VBScript), Far (Lua), and TC and DC through user commands. Dossier: the CLI, and the MCP server for assistants.
- **Folder notes (rendered Markdown):** Dossier only.
- **Health checks and quarantine:** Dossier only.
- **Languages:** the others many, Dossier English only.
- **Linux:** DC (packaged), far2l (packaged), Dossier (from a checkout). TC and DOpus: no (TC has Android).
- **Price:** TC paid once, DOpus paid with a subscription for updates, DC, Far and Dossier free.

## 4. Against what you use: FreeCommander XE and Just Manager

You have used these two for the last five years, so they are the yardstick that matters (added 2026-11-05, facts checked on the web the same day):
- **FreeCommander XE** (freeware, Windows):
  - two panels side by side, one above the other, or one panel alone; tabs;
  - an optional folder tree for one or both panels;
  - Quick View, quick search and quick filter;
  - FTP, and SFTP in the 64-bit version, built in;
  - archives (zip, cab, rar, nested ones too);
  - portable.
- **Just Manager** (free, Windows; its own downloads still say alpha or release candidate):
  - one to sixteen panels, and tabs;
  - an FTP client;
  - files coloured and set in other fonts by extension and attribute;
  - quick search as a filter;
  - a clean, uncluttered look.

What they tell about your taste: both build their features in (no plugins), both are free, and both are simpler to look at than TC.

**Where Dossier is ahead of both:**
- the plan before every change, verify, resume, and permanent-delete warnings;
- SCP, WebDAV, Google Drive, OPDS and Subsonic, with the tailnet and other computers' shares on the Home page;
- folder notes, the assistant, the command line, tags and Health;
- open source, and Linux.

**Where both are ahead of Dossier:**
- **Start-up:** both open at once.
- **Maturity:** both have years of use behind them.

**Where one of them is ahead:**
- **FreeCommander:**
  - a folder tree beside a panel (functionality review card 26, answered Later);
  - Quick View (card 24, Later);
  - panels one above the other, or one panel alone (card 10 below).
- **Just Manager:**
  - more than two panels;
  - colour by file type (card 9 below).

Worth knowing: the tree and Quick View, which you answered Later, are both things FreeCommander has given you for five years, so you may miss them sooner than the other Later cards.

## 5. What follows: decisions

### 1. Lead with what is unique
- **What:** the README and the landing page open with the four things no other commander has together:
  - the plan before every change;
  - servers and the tailnet as folders;
  - folder notes;
  - the assistant that can only propose.

  Then a line that everything is built in: no plugins to find. A short "Dossier and the others" section then says honestly where another commander is the better choice today.
- **Why:** today the README opens with "two panels, tabs, one selection", which every commander says. The usability review of 4 Nov said the tailnet and servers should lead.
- **Where:** `README.md` (at the next release, not now; the landing page follows your rule of updating at release time).
- **Effort:** small. **Recommendation:** Yes (at the next release).

### 2. Make it start fast
- **What:** measure the time from start to a window you can type in, for the one-file exe and for the installed one. Then cut it: the installed (unpacked) build, imports done later (viewers, servers, mutagen, the MCP code), and the first listing before the Home page lights are read.
- **Why:** 3.3-3.7 seconds before Python has even printed the version, against instant for TC and Far. It is the first thing any new user notices.
- **Where:** `dossier.spec` and `installer\dossier.iss` (the build), `dossier/__main__.py` and `gui/app.py` (what is imported at start).
- **Effort:** large. **Recommendation:** Yes.
- **Measured (build 2026-11-05#13, `tools/time_startup.py`, start of the process to a window that can be typed in, offscreen):**

  | How it starts | first start | then, median of 5 |
  |---|---:|---:|
  | from the source | 1.23 s | 1.41 s |
  | one-file exe (what releases ship today) | 3.83 s | 3.38 s |
  | one-folder exe (unpacked, 140 MB in a folder) | 2.21 s | 1.08 s |

  **Most of the 3.4 s is the one-file exe unpacking itself into a temporary folder at every start.** The one-folder build starts in about a second, as fast as the source. Of that second, importing the window's modules is about 0.7 s (the update check alone pulls in `urllib` and `http`, 0.1 s); later imports can cut more, but the build is the big step. The catch: the installer would then install the folder, and Help > Check for Updates swaps only `dossier.exe`, so an installed copy needs another way to update (run the new installer silently). That is the owner's call.

### 3. Core before new areas
- **What:** no new feature area until the functionality review's Yes cards are built and a release has run for a week of real use. New areas here means new protocols, new checkers, new viewers and new kinds of tags. The Yes cards include F5 to any folder, F4 with another editor or on a server, tabs, Unpack of many archives, and the small ones. Fixes and those cards go on as normal.
- **Why:** the weaknesses above are depth and trust, not breadth. This is the usability review's advice once more, now with a list of what "depth" means.
- **Effort:** decision. **Recommendation:** Yes.

### 4. Measure big folders
- **What:** a repeatable test of listing, sorting, marking and copying folders of 10,000 and 100,000 files, local and on the NAS, timed for Dossier, with Explorer, TC and DC alongside as yardsticks for speed only. The numbers go into the review.
- **Why:** this review cannot say whether Dossier is slow or fast on big folders, because it was never measured. A commander that stalls on a big folder loses users as surely as one that loses files.
- **Where:** a script in `tools\` (scratch folders in `C:\Temp\Claude`), and the slowness log for the window.
- **Effort:** medium. **Recommendation:** Yes.
- **Measured (build 2026-11-05#13, `tools/time_big_folders.py`, the owner's laptop, local SSD, Defender on; files of 1 byte to 2 KB):**

  | Step | 10,000 files | 100,000 files |
  |---|---:|---:|
  | list the folder (on a thread) | 0.08 s | 1.04 s |
  | sort by name, folders first | 0.01 s | 0.16 s |
  | show it in the list | 0.01 s | 0.14 s |
  | sort the list by size (window thread) | 0.02 s | 0.31 s |
  | sort the list by date (window thread) | 0.04 s | 0.64 s |
  | mark every file / invert the marks | 0.01 s | 0.09 s / 0.12 s |
  | plan the copy | 0.31 s | 3.25 s |
  | copy it | 18.8 s | 178.9 s |

  Listing, sorting and marking scale well. Two things to look at: **sorting 100,000 by date takes 0.6 s on the window's thread** (a stall you can feel), and **copying small files runs at about 550 a second**, which is likely slower than Explorer for many small files (the copy goes one file at a time through Python's file calls; the virus scanner counts too). Explorer, Total Commander and Double Commander were not timed yet: run the script with `--keep` and time them on the same folders by hand. Not timed on the NAS yet either: `--where \\nas\share\dossier-timing --sizes 10000`.

### 5. No plugins: build features in
- **What:** Dossier gets no plugin system, neither its own nor TC's. A format or a source of files that is worth having is built in (`core/vfs.py` is one interface for every source), with tests, in the normal menus and settings. Spec A7 (a plug-in interface for file systems) and the plug-in part of V9 are dropped; V9's mapping of a file type to a program stays (functionality review cards 2 and 3).
- **Why:** you said it: plugins are complicated and often outdated, and many ordinary users cannot understand them. A built-in feature is updated with the program and found where the other commands are. TC's plugins would also be native DLLs inside the program, where a bad one can crash it or harm files.
- **Where:** the spec (A7, V9) and CLAUDE.md "Decided", once you say yes.
- **Effort:** decision. **Recommendation:** Yes.

### 6. Every key can be changed
- **What:** Settings > Keys, for every command rather than only the function keys (spec C1), with the menu rules' checks for clashes and no Ctrl+Alt.
- **Why:** people coming from another program bring their own keys, and a few of Dossier's defaults may not suit you either. Against it: under the usability measure, good default keys matter more than a page of key settings.
- **Where:** `core/fkey_config.py` grows into a key table for all commands, and `gui/fkey_settings.py` into a Keys page.
- **Effort:** large. **Recommendation:** Later.

### 7. Norwegian as a second language
- **What:** spec C10: the menus and dialogs through translation files, with English and Norwegian first.
- **Why:** every competitor is translated. But the audience (programmers, tailscalers) mostly works in English, and every new text would then need two versions.
- **Effort:** large. **Recommendation:** No for now (it slows every change, for a small gain with this audience).

### 8. A Linux package
- **What:** build the Linux tarball (or an AppImage) once in the `redactor-build-tools` toolchain, and test it on a clean Debian 12 and Ubuntu 22.04.
- **Why:** "Windows and Linux" is a selling point only if Linux users can install it. DC and far2l are packaged in the distributions.
- **Effort:** large. **Recommendation:** Later (after the Windows installer is done).

### 9. Colour files by type
- **What:** names coloured by rule, as Just Manager does: by extension group (pictures, video, music, archives, documents, code, programs), with hidden and system files dimmed. A short default set that follows the light and dark schemes, editable in Settings > Appearance. Marked files keep their own colour on top.
- **Why:** you see a folder's make-up at a glance without reading the Type column. Just Manager has had it for the years you used it.
- **Where:** `gui/models.py` (the colour of a row's name, beside the marked and folder colours at `:538`), a rule list in the settings, and a page in Settings > Appearance.
- **Effort:** medium. **Recommendation:** Yes.

### 10. One panel, or panels one above the other
- **What:** View > Layout: two side by side (as now), two stacked (for a tall or narrow screen), or one panel alone (Tab or F9 brings the other back). FreeCommander has all three.
- **Why:** on a laptop screen or with long names, side by side halves the width of everything. The commander keys keep working, since the other panel still exists.
- **Where:** `gui/main_window.py:158`, the splitter between the panels (its direction, and hiding one side), and the layout saved with the window.
- **Effort:** medium. **Recommendation:** Later (after the functionality review's Yes cards).

## Sources (web, checked 2026-11-05)
- TC's SFTP plugin: https://ghisler.ch/wiki/index.php/Secure_FTP_plugin
- TC price and updates: https://www.ghisler.com/order.htm and https://hn.svelte.dev/item/43099230
- DOpus 13, FTP built in, SFTP extra, update subscription: https://en.wikipedia.org/wiki/Directory_Opus and https://www.filehorse.com/download-directory-opus
- DC protocols, TC plugins, platforms: https://doublecmd.sourceforge.io/ and https://alternativeto.net/news/2024/11/double-commander-1-1-20-improvements-and-fixes
- far2l and NetRocks: https://github.com/elfmz/far2l/issues/247 and https://community.linuxmint.com/software/view/far2l
- FreeCommander XE: https://freecommander.com/fchelpxe/en/FreeCommander.html?Icons.html and https://www.filehorse.com/download-freecommander
- Just Manager: https://www.softpedia.com/get/File-managers/Just-Manager.shtml and https://www.addictivetips.com/windows-tips/just-manager-clutter-free-dual-pane-file-explorer-with-an-ftp-client
- No commander with an MCP server found: a web search for MCP file managers and dual-pane commanders, 2026-11-05
