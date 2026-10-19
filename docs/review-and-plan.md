# Dossier: critical review and plan for version 0.1

Date: 2026-10-19. Reviewed state: commit `5ac6cc1` (spec, `platform`, `vfs`, `selection`, CI). Two reads: the main session, and an independent review by a Fable-model agent that was given the code and not our conclusions. Items marked (F) come from that agent, which ran probes for the bugs in section 3. A few of them still need a proper failing test, which is step 1 of the plan.

## 1. Verdict

The foundation is sound: Qt-free core, one platform module, shared selection, CI on both systems, clean-room rule. The risk is not the code, it is the scope. The spec describes about five products (window manager, file manager with undo, virtual file systems, viewer suite, notes and metadata editor) plus MCP, themes, i18n and profiles. Only the first two are a file manager. Nothing in the spec yet says what version 0.1 is, so as written there is no finish line.

## 2. Risks, ranked

1. **Scope.** No v0.1 definition. Sections 9-12 (metadata, remote, MCP) are Redactor features in a new window, not file-manager features.
2. **Window model undecided.** Spec section 2 says "windows inside a main workspace" (MDI) but W6 says native chrome. MDI gives arrange/cascade/desktops cheaply with non-native chrome. Separate top-level windows give native chrome but no arrange, and on Wayland the app cannot place or restore window positions. This choice is the product. (F)
3. **VFS is read-only.** `FileSystem` has `list/stat/open_read` only. Plan, undo, progress and cancel (spec step 1) have nothing to sit on. No async or paged listing, so a 100k-file folder blocks the GUI. No filesystem prefix in identity keys, so `zip://` and `dav://` paths will collide with local ones later. (F)
4. **No threading model.** Selection observers are called synchronously (`selection.py:28`); a worker thread that changes the selection will touch widgets off the GUI thread. (F)
5. **Selection keyed by string path.** A rename or move leaves stale entries; `\\?\C:\x`, mapped drive vs UNC and junctions are different keys for one file; `normcase` lowercases on case-sensitive Windows volumes (WSL, Dev Drive); `paths()` sorts on every call. (F)
6. **`redactor_common` pulls in PyQt6.** Its `pyproject.toml` lists PyQt6 as a hard dependency, which defeats the Qt-free core and a headless MCP server. Needs an extras split there first. The pinned tag `2026-10-18-08` does exist (checked with `git ls-remote`). (F)
7. **Two real bugs** (section 3).
8. **Long paths:** O6 claims the prefix is applied automatically; `LocalFileSystem` does not do it yet.
9. **Naming and licensing:** `dossier` is already a PyPI namespace (F, to verify). CLAUDE.md cites pluteus as public MIT, but our notes say the repo went private on 2026-10-11; settle that before copying code. Reuse of the Redactor GPL code is fine.
10. **No GUI test strategy, release workflow, version-bump script, changelog or git hooks.** GUI work would outrun verification.

## 3. Defects in the existing code

- `decode_name(bytes)` raises `UnicodeDecodeError` on Windows (filesystem error handler there is `surrogatepass`). The only test is skipped on Windows. Lone surrogates outside U+DC80-U+DCFF, legal in NTFS names, pass through undisplayable. (`platform.py:33-35`)
- `walk()` loops forever on a Windows junction cycle: `DirEntry.is_symlink()` is False for junctions. One unreadable subfolder also aborts the whole walk. (`vfs.py:102-107`)
- `LocalFileSystem.stat`: three syscalls; reports a size for directories; follows links, so it disagrees with what `walk` skips. (`vfs.py:52-61`)
- `SelectionStore`: `toggle` and `invert([])` always notify while `add/remove/set` only notify on change; an observer that raises stops the remaining observers; `recall` of an unknown name raises a bare `KeyError`. (`selection.py:28-30, 67, 87, 94`)
- Packaging: bare `pytest` fails (no `conftest.py` or editable install; CI works only because it uses `python -m pytest`). `pyproject.toml` has `dependencies = []` but `requirements.txt` lists `send2trash`. CI tests Python 3.12 only while the project says 3.10+.
- Test gaps: nothing covers `stat`, `walk`, `open_read` or observer errors.

## 4. Decisions needed from the owner

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | MDI workspace or separate top-level windows | Separate top-level windows with native chrome. Drop arrange modes and virtual desktops (W3, W5) to "later" |
| D2 | Commander mode (W4) vs multi-window | Later; it is a layout preset on top of two ordinary windows |
| D3 | Version 0.1 scope | As in section 5 |
| D4 | pluteus code: public or private? | Decide; if private, copy only what you are willing to publish under GPL, or promote it to `redactor_common` |
| D5 | Name | Run the PyPI and domain checks now, before a release name is built into the exe and docs |
| D6 | Ask Ebdac for permission? | Do not block on it. The clean-room rule already covers function lists |

## 5. Version 0.1: what it is

**Corrected 2026-10-19: the 0.1 window is a dual-pane orthodox commander (two panels, F-key bar, command line, copy and move to the other panel, Tab to switch); the sentence below about one tree-and-list window is superseded.** One tree-and-list window type, any number of windows. One shared selection with count and total size in the status bar. Copy, move, delete (to trash) and rename with a plan dialog, progress, cancel and undo. A folder note (`README.md` or `about.md`) rendered under the listing, read-only. A read-only text viewer. Open with the system program. Session restore of folders and window geometry. Windows exe and Linux tarball.

Not in 0.1: archives, SQLite, CSV viewer, hex, Markdown editing, metadata, remote, MCP, search, user commands, themes beyond system, languages, desktops, commander mode.

Done means: you would open it instead of Explorer for a real day of work.

## 6. Build plan

Effort is in the owner's scale: small under 2 min of Claude time, medium up to 10 min, large over 10 min. Lane: C = Qt-free core (a cloud session may do it), L = needs a local session to see it running.

| Step | What | Lane | Size | Done when |
| --- | --- | --- | --- | --- |
| 1 | Fix section 3: failing test first for each bug, then the fix. Add `conftest.py` or editable install, Python 3.10 and 3.12 in CI, a `compileall` step, `.githooks` copied from Veritas | C | medium | CI green on both systems, bare `pytest` works |
| 2 | Record D1-D5 in CLAUDE.md and spec section 2 and 14 | C | small | Spec and notes agree |
| 3 (done 2026-10-19) | Extend the VFS to the write contract: `mkdir`, `rename`, `remove`, `open_write`; progress and cancel protocol; filesystem-prefixed identity keys; apply the long-path prefix in `LocalFileSystem`; junction-safe `walk` | C | large | Tests on both OS, including junction and long-path cases (Windows) |
| 4 | Split `redactor_common` into a Qt-free core and a GUI extra, tag, bump the pin | C (other repo) | medium | `pip install` of Dossier core pulls no PyQt6 |
| 5 (done 2026-10-19) | Operation plans: copy, move, delete (trash), rename; conflict handling (F11); undo log, written in Dossier's own core; `redactor_common` `move_plan` is library-pattern specific and its `undo` is in-memory edit undo only, so neither fits (only `trash` is reusable, later) | C | large | Plan, commit and undo tested against `tmp_path` trees; failures leave originals untouched |
| 6 (done 2026-10-19) | Worker model: one executor in the core, a Qt signal bridge in the GUI; selection observers delivered on the GUI thread; selection re-validates paths after operations and refresh | C then L | medium | A background copy updates the status bar without touching widgets off-thread |
| 7 | GUI shell: one tree-and-list window, address bar, back/forward/up, sortable resizable columns, status bar with selection count and size, several windows | L | large | Runs on Windows, offscreen smoke test on both |
| 8 | Selection UI: click, range, invert, pattern select, selected-items pane across windows | L | medium | Selection survives navigation across windows |
| 9 | Folder note pane (N1, N2 read-only) and read-only text viewer (V1 without follow mode) | L | medium | Notes render, big text files open without freezing |
| 10 | Session restore, `pytest-qt` smoke tests, PyInstaller release workflow (from `cbzredactor`), version bump script and changelog, Linux tarball | L | large | Tagged build produces both artefacts; first real use |
| 11 | Use it for a week, collect problems, then choose the next block: ZIP (A1, A4), Markdown edit (N5), metadata read (M1) | owner | n/a | A short list of what hurt |

Steps 1-5 are core work with no GUI and can run in parallel lanes once D1-D5 are settled; the only ordering constraints are 3 before 5 and 4 before anything that imports `redactor_common` core in a headless install.

## 7. House rules that apply while building

Mandatory progress feedback for anything slow; every table resizable and sortable; no Ctrl+Alt shortcuts (Norwegian AltGr); data logging opt-in; edit code with Edit/Write, never through heredocs; commit only after a real exit code from `python -m pytest`; syntax check before every commit.
