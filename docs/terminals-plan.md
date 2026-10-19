# Dossier: terminals, interpreters and administrator mode

Date: 2026-10-19. Requests (owner): buttons that open a command session in the working directory; a setting that chooses the interpreter; a decision on how administrator mode is handled. This also fixes how the one-line command line under the panels (C4) picks its shell.

## 1. Interpreter profiles

A **profile** says how to run one command and how to open one interactive session in a folder.

| Profile | System | Run one command | Open a session in the folder |
| --- | --- | --- | --- |
| Command Prompt | Windows | `cmd.exe /d /c <command>` | `cmd.exe /k` with the folder as working directory |
| Windows PowerShell 5.1 | Windows | `powershell.exe -NoProfile -Command <command>` | `powershell.exe -NoExit` |
| PowerShell 7 | Windows, Linux, macOS, if `pwsh` is found | `pwsh -NoProfile -Command` | `pwsh -NoExit` |
| Git Bash | Windows, if Git for Windows is found | `bash.exe -c` | `bash.exe --login -i` |
| WSL | Windows, if `wsl.exe` is found | `wsl.exe --cd <folder> -- <command>` | `wsl.exe --cd <folder>` |
| The login shell | Linux, macOS | `$SHELL -c` | in a terminal emulator |
| Custom | any | a user template with `{dir}` and `{command}` | a user template with `{dir}` |

- **Hosts for a session:** on Windows, Windows Terminal (`wt.exe -d <folder>`) when installed, else the classic console window; on Linux, the first emulator found (`x-terminal-emulator`, `gnome-terminal`, `konsole`, `xfce4-terminal`, `kitty`, `alacritty`, `xterm`) or one the user names.
- **Detection** runs when the settings page opens, not at startup; a profile whose program is missing is listed greyed with the reason.
- **Quoting follows the profile.** `%f`-style placeholders in the command line are quoted for the chosen interpreter (PowerShell, cmd and sh quote differently; a wrong quote is how a file called `a&b.txt` becomes a command injection). Placeholder expansion is per-profile code with tests for hostile names.
- **Settings:** a **Settings > Terminal** page: default profile, host, the custom template, and whether the command line under the panels uses the same profile (default yes).

## 2. The buttons

- **Terminal here** (button next to the command line, menu entry, shortcut): opens the default profile in the active panel's folder. A small drop-down on the button picks another profile once. A second entry opens the other panel's folder.
- Works only for local folders. On a server or archive the button says why it is unavailable instead of opening a terminal in a wrong place.
- Dossier starts the terminal and lets go; it does not stay attached to the session, never reads its input or output, and never sees anything typed there.

## 3. Administrator mode, decided

**Dossier itself runs as the normal user. It never raises its own rights.** Reasons: an elevated process cannot take drag and drop from normal windows; an elevated process does not see the user's mapped network drives (a separate logon session on Windows, solved only by a system registry change that Dossier must not make); and every file operation would then run with full rights, which turns a mis-click into a disaster.

| Case | Behaviour |
| --- | --- |
| **Open an administrator terminal here** (second button) | Windows: start the profile through the shell's `runas` verb, which shows the system's UAC prompt; the new window is elevated, Dossier stays normal. Linux and macOS: open the terminal and run `sudo -s` as its first command, so the password is typed into the terminal and never passes through Dossier. If `sudo` is not available the button says so |
| **The command line under the panels** | Always as the normal user. There is no "run this one command elevated": it would need a prompt per command and a way to pass the command across privileges, which is a security surface for little value. Use the administrator terminal |
| **A file operation fails with "access denied"** | The error is reported with the item and the reason. A later "retry as administrator" would need an elevated helper process; **not built, not planned** (open question). Meanwhile the message suggests the administrator terminal |
| **The user starts Dossier elevated themselves** | Detected (`IsUserAnAdmin` on Windows, effective user id 0 on Linux). The title bar shows "Administrator", the active-panel bar changes to the danger colour, and a one-time notice names the consequences (mapped drives missing, drag and drop limits, everything runs with full rights). Nothing is blocked |
| **Passwords** | Never requested, stored or logged by Dossier for this feature |

Profiles from a custom template are code the user wrote. A profile is never imported from a downloaded or shared file, and the settings file is not a trust boundary (a program that can edit it can already run programs as the user), but the settings dialog shows the full command a template will run.

## 4. Build steps

| Step | What | Size |
| --- | --- | --- |
| T1 | `core/terminals.py`: profile table, detection (with an injectable "which"), command and session command-line construction, per-profile quoting; tests for every profile on both systems, including hostile file names | medium |
| T2 | Command line under the panels uses a profile (run one command, capture output, placeholders `%f %p %s %d %o`) | medium |
| T3 | Buttons, menu entries and shortcut for "Terminal here" and "Administrator terminal here" with an injectable launcher so tests never open a window or a UAC prompt | medium |
| T4 | Settings > Terminal page (default profile, host, custom template with a preview of the exact command) | medium |
| T5 | Elevated-Dossier detection and the visible warning | small |

## 5. Open questions

| # | Question | Recommendation |
| --- | --- | --- |
| A1 | Offer "retry as administrator" for failed file operations through an elevated helper? | No. Too much privileged surface; use the administrator terminal |
| A2 | Shortcut for "Terminal here" | `Ctrl+Shift+T` (never Ctrl+Alt; AltGr on Norwegian keyboards) |
| A3 | One shared profile for command line and terminal, or two settings? | One, with a checkbox to split |
| A4 | Windows Terminal as the default host when installed? | Yes |
