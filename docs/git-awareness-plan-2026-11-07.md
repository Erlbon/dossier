# Git awareness plan, 2026-11-07 (build 2026-11-07#06)

A plan for the read-only parts of git that survived the critical review of the same day: Dossier **shows** what git knows about a folder
that already is a repository, lets you **browse its past** like an archive, and **hands off** to real git tools. Dossier never writes to a
repository: no `git init`, no commit, no sync, no restore. Nothing is built yet; the answers go on the decision page (one card per
proposal, Yes / No / Later).

**How it was checked.** Read the code each card builds on (file and line given): the columns (`core/columns.py`), the file system router
(`core/home.py`), archives as folders (`core/zipfs.py`), Compare (`core/compare.py`), the tools bar (`core/tools.py`), the terminals
(`core/terminals.py`), the Windows shell menu (`core/shellmenu.py`), thumbnails' network switch and auto refresh. Git's own commands
(`status --porcelain=v2`, `log`, `ls-tree`, `show`) are the standard ones and were not run against Dossier for this plan.

**Compared with** FreeCommander XE and Just Manager (your yardsticks), and VS Code's explorer for the git column. From knowledge, not a
fresh check: neither FreeCommander XE nor Just Manager shows git status that I know of; VS Code and TortoiseGit's Explorer overlays do.

**Left out on purpose** (critical review, 2026-11-07): creating repositories, a commit after every Dossier plan, git mirroring over
Tailscale, restoring old versions over current files, and a git with its words hidden. Previous Versions (shadow copies) is out too:
listing them needs administrator rights, and Dossier never asks for them.

**Effort:** small = under 2 minutes of work, medium = up to 10, large = more than 10.

**Decided by the owner, 2026-11-07:** cards 1, 2, 3, 4 and 8 Yes (built in build 2026-11-07#07); cards 5, 6 and 7 Later. Card 2's
"status line" became each panel's own bar, beside the item counts: the two panels can be in different repositories, and the window's
status line is about the marked items.

**Overall.** Two phases. Phase 1 (cards 1-4) is what a programmer sees every day: the branch and what changed, in the status line and a
column, without leaving the file manager. Phase 2 (cards 5-7) is the novel part, and fits Dossier's WinFS line ("a layer on ordinary
files"): any commit opens as a read-only folder, so F3, F5 and Compare work on the past with nothing new to learn. Card 8 is a small
hand-off. Everything is read-only, so the worst a bug can do is show something wrong, never lose a file. Recommendation: phase 1 first,
use it for a while, then decide phase 2.

---

## 1. Seeing git in a folder that is a repository

### 1. The engine: the installed git.exe, read-only commands only
- **What:** Dossier would run the `git` that is already installed (Git for Windows), as it runs 7-Zip for RAR, and only commands that
  read: `rev-parse`, `status`, `log`, `ls-tree`, `cat-file`/`show`. When git is not installed, a folder simply shows no git
  information; nothing asks to install it. A repository git refuses (`safe.directory`, a share owned by another user) says so in one
  plain line instead of an error.
- **Why:** every repository stays an ordinary one that VS Code, TortoiseGit and servers read the same way; no git library to bundle
  (dulwich or pygit2 would add size and their own bugs); read-only means no data can be lost.
- **Fix/Where:** a new Qt-free `core/gitinfo.py`: find the repository root (walk up to a `.git` folder or file, so worktrees and
  submodules count), run a command with a timeout and the `-z` output form, parse it. Each call on a thread, never on the window's.
- **Effort:** small. **Recommendation:** Yes (everything else stands on it).

### 2. The branch and what changed, in the status line
- **What:** inside a repository the status line (`gui/panel.py:1836`, `_update_counts`) gains "git: main · 3 changed, 1 new", and the
  branch's state against its remote when git knows it ("2 ahead"). Outside a repository nothing changes.
- **Why:** the one fact a programmer wants when opening a project folder, without opening a terminal. VS Code shows the same in its
  status bar.
- **Fix/Where:** `core/gitinfo.py` (`status --porcelain=v2 --branch`), run when a folder opens and again when auto refresh sees a change
  (`gui/auto_refresh.py:29`); cached per repository for a few seconds so moving between its folders asks git once.
- **Effort:** medium. **Recommendation:** Yes.

### 3. A Git column
- **What:** a column "Git" (off until switched on, like the metadata columns) that shows, for each item, changed / new / staged /
  ignored / conflict, and for a folder whether anything below it changed. Sortable, so "what did I change" is one click.
- **Why:** VS Code's explorer and TortoiseGit's overlays give exactly this; in a file manager it shows what changed before you copy a
  project somewhere.
- **Fix/Where:** a new key at the end of `LATER_KEYS` (`core/columns.py:20`, so no older column moves), filled from the same one
  `status` answer as card 2 (one call per repository, not per file).
- **Effort:** large. **Recommendation:** Yes, after card 2.

### 4. Off on network drives and servers until switched on
- **What:** git information is read only on local drives unless the owner switches it on for network drives, as thumbnails do
  (`gui/thumbnails.py:124`, `on_network`). Never on servers (`sftp://` and the rest) or inside archives.
- **Why:** `git status` on a big repository over a share can take seconds, and a slow share must never make a folder feel stuck.
- **Fix/Where:** one switch in Settings next to the thumbnail one; `core/gitinfo.py` checks it.
- **Effort:** small. **Recommendation:** Yes (part of cards 2-3).

## 2. The past of a repository as folders

### 5. Open any commit as a read-only folder
- **What:** a commit opens as a folder, `git://C:/Dev/dossier@a194f42/dossier/core`, read-only like a zip (`core/zipfs.py:57`): browse it,
  F3 a file, F5 copy a file out, drag it out. The address bar shows which commit it is.
- **Why:** the "browse the past like an archive" idea with nothing new to learn: the same keys as everywhere else. Getting an old file
  back becomes "open the commit, F5 it out", and nothing is ever written into the repository.
- **Fix/Where:** a new `core/gitfs.py` file system (`ls-tree` to list, `cat-file` to read), routed like `zip:` in `RouterFileSystem.fs_for`
  (`core/home.py:228`).
- **Effort:** large. **Recommendation:** Later (phase 2: decide after phase 1 is used).

### 6. History of a file or folder
- **What:** right-click > "History..." on an item in a repository lists its commits (date, author, message, a filter box). Opening one
  goes to card 5's folder for that commit, with the cursor on the item.
- **Why:** the way in to card 5: nobody types commit names.
- **Fix/Where:** `git log --follow --format=... -- <path>` in `core/gitinfo.py`; a small list dialog.
- **Effort:** medium. **Recommendation:** Later (with card 5).

### 7. Compare and view against an old version
- **What:** with card 5, Compare (`core/compare.py:122`, which works through any file system) compares a folder now with the same folder
  in a commit, and F3 shows an old file beside the current one.
- **Why:** "what changed since last week" in the tools Dossier already has.
- **Fix/Where:** nothing new in Compare; the History list gets "Compare with now".
- **Effort:** small. **Recommendation:** Later (with card 5).

## 3. Handing off to git tools

### 8. Git tools as suggestions on the tools bar
- **What:** Add a Program's suggestions (`core/tools.py:203`) gain the git tools found on the computer: TortoiseGit's log for this
  folder (`TortoiseGitProc.exe /command:log /path:{dir}`), GitHub Desktop, VS Code on this folder (`code {dir}`), lazygit in a terminal.
- **Why:** committing, branching and syncing belong in those tools; one click from the folder you are in is the right hand-off.
- **Fix/Where:** entries in `SUGGESTED`, shown only when installed (as now).
- **Effort:** small. **Recommendation:** Yes.

## Already there (no work)

- **The Windows shell menu** at the end of Dossier's right-click menu (`core/shellmenu.py`) already shows what TortoiseGit and Git
  for Windows added to Explorer's menu (Git Bash Here, TortoiseGit's commit and log).
- **Git Bash** is one of the terminal choices (`core/terminals.py:55`).
- **Search** already skips `.git` folders by default.

## Considered and not proposed

- Creating repositories, committing, a commit after each Dossier plan, pushing or pulling, mirroring over Tailscale, and restoring an
  old version over the current file: rejected in the critical review (data risk, wrong audience, other tools do it better).
- A git library inside Dossier instead of git.exe (card 1 says why).
- Previous Versions (shadow copies): needs administrator rights to list; Dossier never asks for them.
