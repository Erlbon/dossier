# Dossier: the Home page, remote drives and servers, critical review

Date: 2026-10-19. The idea (owner): a "home" page that lists local drives, remote drives (SMB and whatever else exists) and other servers (FTP, SSH, WebDAV, open to suggestions). This review says what is cheap, what is dangerous, what the existing code cannot do yet, and in which order to build it. Short version: **the Home page itself is cheap and valuable; the servers behind it are the largest single item in the whole project, and the current code is not ready for them.**

## 1. What "Home" should be

A virtual folder at the root of every panel (`home://`), the place Backspace reaches from a drive root, like the drive list of the classic commanders. It has sections:

| Section | Entries | Cost |
| --- | --- | --- |
| Local drives | Fixed, removable, optical drives with label and free space (already in `core/drives.py`) | done |
| Places | Home folder, Documents, Downloads, user-pinned folders, cloud sync folders (OneDrive, Dropbox, Google Drive show up as ordinary local folders) | small |
| Network drives | **Shares the operating system handles** (decided with the owner, 2026-10-20): SMB (mapped drives, UNC `\\server\share`, CIFS mounts) and NFS (Windows Client for NFS, Linux mounts). Same label and free-space line as local drives, plus a "Mount..." button for NFS and SMB | small |
| Remote sources | **Protocols Dossier speaks itself** (decided 2026-10-20): saved connections for SFTP, SCP, WebDAV, FTP/FTPS, later S3-compatible and others. SMB and NFS are not here: they are network drives | the big one |
| Services | Catalogues that are not file systems: OPDS, Subsonic (spec R2, R3) | medium, read-only |

The drive dropdown and button strip are the same list in a smaller form: **one registry of "places", two views of it**, so a connection added once appears in both.

## 2. What is out there (the standards)

| Kind | Notes | Verdict |
| --- | --- | --- |
| SMB/CIFS | Windows speaks it natively: a UNC path works through the ordinary file APIs, so `LocalFileSystem` already handles it. Linux needs a mount (gvfs, cifs) or a pure-Python client (`smbprotocol`, MIT) | Windows: free. Listing shares is the only work |
| NFS | Mounts only; appears as a mount point. Goes under Network drives with a Mount helper (Windows `mount \\server\share Z:` once Client for NFS is enabled; Linux `mount`/gvfs). No native client. **Settings check (owner, 2026-10-20):** Settings shows whether Client for NFS is on. Test without admin rights: `mount.exe` exists in System32 only when the feature is installed (and the `NfsClnt` service is present). When it is off, the Mount button explains why and shows how to switch it on (Windows Features dialog, or `Enable-WindowsOptionalFeature -Online -FeatureName ServicesForNFS-ClientOnly` in an administrator PowerShell). Dossier never switches it on itself: that is a system setting | Free through the drive list |
| SFTP (SSH) | The most useful server protocol for a developer. Needs `paramiko` (LGPL) or `asyncssh` | Phase 3, first server |
| WebDAV | Spec R1 phase 1. HTTP plus XML; easy to read, uneven in write semantics between servers | Phase 3, with SFTP |
| FTP, FTPS | `ftplib` in the standard library. Plain FTP is cleartext; listing formats are a swamp (prefer MLSD) | Phase 4, with a warning |
| S3-compatible, Azure Blob, Backblaze B2, Google Drive, OneDrive, Dropbox | Cloud APIs, OAuth, rate limits | Through an `rclone` bridge, optional, later |
| SCP | Owner asked for it (2026-10-20). The SCP protocol only copies files (no listing, rename or delete), so it runs over the same SSH connection as SFTP: browse and change with SFTP, and use SCP as the transfer mode for servers where the SFTP subsystem is switched off (paramiko exec of `scp -t`/`scp -f`, or the `scp` module). Shown as its own scheme `scp://` in the connection list | Phase 3, with SFTP |
| AFP | Dead | Skip |
| iSCSI | Appears as a local disk once the OS has connected it; not relevant for Dossier (owner, 2026-10-20) | Nothing to do: it is just a local drive |
| WebDAV mounted by Windows (`\\host@SSL\DavWWWRoot`) | Works, flaky, size limits | Do not rely on it |
| SSHFS, rclone mount | Appear as a drive or mount | Free |
| MTP (phones) | Windows shows them as shell folders, not paths | Out of scope |
| OPDS, Subsonic | Catalogues, not file systems | Services section, read-only |
| TFTP, Gopher, IPFS, Git | No | Skip |
| Tailscale (a VPN, not a protocol) | Tailnet hosts get ordinary addresses and names, so SFTP, WebDAV and SMB work over it with no extra code. See section 7 | Free; a light discovery section is cheap |

## 3. Critical review

### 3.1 The existing code is not ready for remote file systems

1. **Navigation blocks the window.** `Panel.set_folder` lists synchronously on the GUI thread (`panel.py`). A remote listing takes seconds or hangs, and the project rule is that everything slow shows progress and can be cancelled. A non-blocking navigation path (list in a job, loading state, cancel, back to the previous folder on failure) must exist **before** the first remote file system, or every dead server freezes Dossier.
2. **Paths are built with `os.path` everywhere.** `ops.py`, `panel.py`, `notes.py`, `selection.py` join with the local separator. A remote path (`sftp://host/a/b`) must use forward slashes on Windows too. The `FileSystem` interface needs its own `join`, `split`, `basename`, `dirname`, and the ops layer must call those, not `os.path`. This is a real refactor across the core, and the path identity work (scheme-prefixed keys) was only the first half.
3. **Operations are one file system only.** Plans copy and move within one `fs`. Server work needs cross-file-system copy (the copy helper already takes two systems; the planner does not), and a move across systems is copy then delete.
4. **Delete has no safety net.** Local delete goes to the recycle bin; a server has none. Remote delete is permanent: the plan must say so and ask for stronger confirmation, and `undo_log` entries for remote moves and copies must understand scheme paths.
5. **The viewer and checkers assume a local path.** `TextSource` reads a local file; the planned checkers hash and decode whole files. Remote needs ranged reads or a cached download, and a clear cost in the checker tiers (T2 over SFTP is slow and costs bandwidth).
6. **Entries are files.** A Home entry is a drive or connection: size and date columns mean nothing; free space, kind and address do. The model needs entry kinds and per-kind columns.
7. **Free space is local.** `disk_usage` has no remote meaning (SFTP `statvfs` exists, FTP and WebDAV mostly not): show nothing rather than a wrong number.

### 3.2 Security and privacy

- **Credentials** only in the system keyring (the rule already written), never in the settings file, history, URLs or logs. "Ask every time" must be an option. A saved connection stores host, port, user and protocol, not the password.
- **SSH host keys:** never accept silently. First connect shows the fingerprint and asks; a changed key blocks with a loud warning (the classic man-in-the-middle sign). Keep a Dossier known-hosts file, optionally read OpenSSH's.
- **TLS:** FTPS and WebDAV over HTTPS verify certificates by default; "accept this certificate" is a per-connection, per-certificate-fingerprint decision, never a global `verify=False`.
- **Plain FTP and HTTP WebDAV** carry passwords in cleartext: show a warning on the connection and offer the encrypted variant first.
- **No automatic probing.** The Home page lists saved servers but never connects on its own: no background reachability pings, no LAN scan on startup. Network discovery (SMB browse, mDNS) is a button the user presses, off by default. This matters on a corporate network, where scans look like an attack, and a dead server must never slow the page.
- **Saved connections are user data**, but they are configuration the user creates on purpose, not logging, so the opt-in-logging rule does not forbid saving them; the Save step is explicit and deletable.
- **Elevated Dossier and mapped drives:** a process running as administrator does not see the user's mapped network drives (separate logon session). Relevant to the terminal and admin questions; see `terminals-plan.md`.

### 3.3 Reliability and fidelity

- Every operation needs a timeout, retry policy, keepalive, and honest cancel; a transfer over a flaky link needs a partial-file strategy (`.dossier-part` on the server, cleaned up on cancel; resume later).
- Rename is not atomic or not overwrite-safe on several servers (FTP RNFR/RNTO, WebDAV MOVE needs an Overwrite header, S3 has no rename). The plan layer must ask the file system what it guarantees (`atomic_rename`, `supports_overwrite`) and degrade gracefully.
- Timestamps, permissions and symlinks survive unevenly: SFTP can set mtime, FTP only through optional extensions, WebDAV has no standard way. Copying to a server may not preserve dates; say so in the plan.
- Names: servers can hold names that Windows cannot (`a:b`, trailing dots, reserved names) and differ on case sensitivity. Copying server to local needs a name-fix step with a conflict report, not a crash halfway.
- FTP listing: demand MLSD, fall back to LIST parsing only with a visible "listing may be wrong" note.
- Encoding: UTF-8 negotiation for FTP; mixed encodings on legacy servers.

### 3.4 Testing

The rule is that user-facing facilities never ship broken. A protocol without an automated test against a real server cannot meet it. Needed: a local SFTP server (e.g. `asyncssh` in the test process), WsgiDAV, `pyftpdlib`, all as test-only dependencies started inside pytest. Samba is not practical in CI; SMB rides on UNC paths on Windows and gets a Linux-only mount test or a small `smbprotocol` loopback if that library is adopted. CI on Windows runners cannot easily host servers other than in-process ones, so in-process servers are required.

### 3.5 Dependencies and size

`paramiko` or `asyncssh` pulls in `cryptography` (about 10 MB in the exe); the exe-size watch (tell at +5 percent) will fire. `fsspec` is small in itself but each backend brings its own dependencies and its listing, error and progress semantics differ. Keep every protocol an **optional extra**, imported on first use, so the base exe stays small and a missing library turns that protocol off with a note, not a crash.

## 4. Build or borrow

| Option | For | Against |
| --- | --- | --- |
| Own implementations (SFTP, WebDAV, FTP on small libraries) | Full control of cancel, progress, timeouts, host-key prompts; fits the plan and undo model | More code; each protocol needs its test server |
| `fsspec` as the layer | Many backends at once | Uniform API hides real differences; weak cancel and progress; still needs our refactor; dependency sprawl |
| `rclone` as an optional bridge | 70 backends including every cloud drive, OAuth and retries already solved | External binary (50 MB, user installs it or we bundle), process and JSON-log parsing, a second source of truth for connections |

**Recommendation:** own implementations for SFTP and WebDAV first (then FTP), behind a strict `FileSystem` contract that includes capabilities; add the `rclone` bridge later as the way to reach clouds without writing OAuth code. Do not adopt `fsspec`.

## 5. Phases

| Phase | What | Size | Needs first |
| --- | --- | --- | --- |
| H0 | Non-blocking navigation (job, loading row, cancel, rollback on failure); `FileSystem` path functions and capability flags; ops layer stops using `os.path` directly; entry kinds | large | nothing |
| H1 | Home page: local drives, places, mapped and UNC network drives, user-pinned folders and typed addresses; same registry feeds the dropdown and strip | medium | H0 entry kinds |
| H2 | Network drives section for SMB and NFS shares, with a Mount... button (runs the OS command on a thread, shows its output, never stores a password); SMB share listing on Windows (enumerate shares of a host, typed UNC addresses, a "browse network" button the user presses); Linux gvfs/cifs shown as mounts | medium | H1 |
| H3 | Connection manager (add, edit, test, keyring) and SFTP and WebDAV file systems, read-only first, then writes with the capability-aware plans | large | H0, H1 |
| H4 | FTP and FTPS, with warnings | medium | H3 |
| H5 | Cross-file-system copy and move plans; permanent-delete confirmation; remote undo rules | large | H3 |
| H6 | Services section: OPDS and Subsonic as read-only virtual folders | medium | H3 |
| H7 | Optional `rclone` bridge for cloud drives | medium | H5 |

H1 is worth doing early: it is the Home page the owner asked for, needs no server code, and exercises the registry that everything later plugs into.

## 6. Decisions needed

| # | Question | Recommendation |
| --- | --- | --- |
| S1 | Is the Home page reached by Backspace from a drive root, and also a button? | Both |
| S2 | Own implementations or `rclone` for clouds | Own for SFTP, WebDAV, FTP; `rclone` bridge later for clouds |
| S3 | Do servers start read-only (spec principle 2, open question 1)? | Yes, writes per connection switch once H5 exists |
| S4 | SMB browsing: button only, never automatic? | Yes |
| S5 | Allow saved passwords in the keyring, or always ask? | Both, per connection, default ask |
| S6 | Which first for real use: SFTP or WebDAV? | SFTP, then WebDAV (Pluteus is WebDAV-capable, so a real test target exists) |

## 7. Tailscale: built in, or just used?

**Embedding it would be overkill; using it costs nothing; a light integration is worth doing.**

- **Plain use, free:** once Tailscale runs on the machine, every device in the tailnet has an IP and a MagicDNS name. A saved SFTP, WebDAV or SMB connection to `homeserver3` just works over it. Nothing in Dossier needs to know.
- **Embedding (`tsnet`, a userspace Tailscale inside the app): overkill.** It is a Go library with no official Python binding, so it would mean bundling a Go helper, handling auth keys and login in our UI, and fighting tailnet policy and device-approval rules. On a managed work laptop it may even be forbidden. It also duplicates a client the user already runs.
- **Light integration (recommended, H2b):** if the `tailscale` command is found, a **Tailnet** section on the Home page lists the devices from `tailscale status --json` (name, address, online or not, system). This is the local daemon's own knowledge, not a network scan, so it has none of the privacy problems of discovery. Each entry offers "Add as SFTP / SMB / WebDAV connection" with the address filled in. If the command is missing the section does not appear.
- **Taildrop (optional extra):** "Send to device" on a selection through `tailscale file cp`, and a "received files" place. Cheap because the command does the work, but it is a convenience, not core.
- **Tailscale SSH:** a server using it can be reached without key setup; whether SFTP works over it depends on the server version and policy, so verify before promising it.
- **Limits:** read-only use of the CLI (never log in, log out or change settings from Dossier: that is a system setting); the CLI path differs per system; all of it is optional.

## 8. Status (2026-10-19)

H0 and H1 are built and tested.

- **H0a:** `FileSystem` has `join`, `basename`, `dirname`, `parent`, `is_root`, `sep` and `case_sensitive`; the planner, undo log, notes finder, selection and the window code use them and no longer call `os.path` on item paths. `MemoryFileSystem` (forward-slash paths, case sensitive) runs the same planner and undo tests as the disk.
- **H0b:** a panel lists a folder on a worker thread. One that answers within 150 ms (every local folder) appears at once; a slow one leaves the window alive, keeps the old folder, says what is being opened, and Esc cancels. A late or failed answer cannot change the wrong folder.
- **H1:** the Home page (`home://`, the root of every panel): local drives with free space filled in the background, the user's places (home, Desktop, Documents, Downloads, Pictures, Music, Videos, OneDrive, Dropbox, Google Drive when they exist), pinned folders (Ctrl+D) and a network section (mapped drives, saved network locations, "Add a network location..."). Reached with the Home button, Alt+Home, Backspace above a drive root, or by typing `home`. Delete removes only a pin or saved location, never a folder; file commands on the page explain that these are shortcuts.
- **Still to do:** H2 (browse the shares of a host, button only), H3 onwards (servers). Saved network locations are stored as typed and opened as folders; a server address is explained, not saved.

## 9. Indicator lights and drive identity (owner, 2026-10-20)

- **Always show** network drives and remote sources, with a light. Never hide an unavailable entry.
- Lights: green connected, grey not checked, red last attempt failed or unavailable, amber (local drives) a different drive than last time. Shapes differ as well as colours (filled dot, hollow dot, cross).
- Network drives: the OS state of mapped SMB/NFS drives is read at once, without touching the network. Remote sources stay grey until opened or until a Check button is pressed; the check runs on a thread with a timeout. No background pinging, no scan.
- Local drives: live, from the Windows device-change message (no polling).
- **Identity of a local drive** = volume GUID + volume serial (+ label, size, file system); the physical disk serial is added when Windows gives it without admin rights. A serial identifies a drive; it is not a checksum (integrity is the Checksums command).
- The identity, not the letter, is the key, so a drive that returns on another letter is recognised as the same drive ("Seen before as E:"). With a changed letter Dossier offers to update pins, favourites and tab history that use the old letter, after asking.
- The "seen before" list is stored data: opt-in, off by default, with a checkbox and a Delete button. Without it, changes are only noticed within one session.

## 10. Nextcloud (owner, 2026-10-20): future feature, under Remote sources

- Nextcloud (and ownCloud) speak WebDAV at `https://host/remote.php/dav/files/<user>/`, so it rides on the WebDAV backend; it is a saved-connection preset, not a new file system.
- What the preset adds: the right URL from just a server address and user name; login with an **app password** (never the main password; created in Nextcloud under Settings > Security), kept in the credential store; two-factor accounts work the same way.
- Later, Nextcloud-only extras: its trash (`/remote.php/dav/trashbin/<user>/trash`) as the recycle bin for deletes there (unlike SMB/NFS, a delete need not be permanent), chunked upload for big files, share links through the OCS API, and file versions.
- Order: after WebDAV works (phase 3). Needs a test server in pytest like the others (WsgiDAV serves the plain WebDAV part; the Nextcloud-only extras need a recorded-response test).

## 11. Status of the lights (2026-10-20, build #06)

Built: lights on local drives, mapped network drives and saved network locations (green filled dot, grey hollow dot, red cross,
amber diamond, drawn over the lower right corner of the icon, with a tooltip); `core/lights.py` (the board of what is known),
`core/drive_identity.py` (volume GUID + serial, Windows; `DriveMemory` with the "same drive on a new letter" case and the
opt-in storage), View > Drive Memory (Remember Drives Between Sessions, off by default; Forget Remembered Drives).
How the lights get their state: a drive answers its free-space probe (green) or does not (red); a panel that opens a path
records it (green) or fails to (red); nothing is pinged. Not built yet: the Mount... button, the Client for NFS check in
Settings, the "update pins to the new letter" offer, the Check button for remote sources (there are none yet).

## 12. Status of SFTP (2026-10-21)

Built (H3, SFTP part): `sftp://user@host:port/path` is a file system behind the common interface, so every command works on it.

- **No SSH library.** The operating system's OpenSSH does the encryption and the login: `ssh -s host sftp`, whose standard streams carry the SFTP protocol, written here in `core/sftp_proto.py` (version 3, pipelined reads and writes, the `posix-rename` extension where the server has it). Nothing is bundled and the exe does not grow; OpenSSH comes with Windows 10/11, macOS and Linux. Without it the connect says so and what to install.
- **Host keys:** fetched with `ssh-keyscan`, shown with their SHA-256 fingerprint, written to Dossier's own known-hosts file only after approval; `ssh` runs with strict checking against that file only. A changed key stops the connection with a warning (replacing it is a separate, explicit button; Cancel is the default).
- **Passwords:** never on a command line, in a file or in a log. They reach the one `ssh` process through its environment and a small helper (`core/askpass.py`) answers its prompt. Keys and the ssh-agent work without one. The login is first tried with what is at hand (a saved password, else keys and the agent); a password is asked for only when the server refuses that. Saved passwords go to the system's store (`keyring`) only when the owner ticks it.
- **Read-only by default** for a new connection (decision S3); the switch is per connection and takes effect at once. Deleting on a server is permanent and the confirmation says so (`is_server_path` makes a server count as "no recycle bin").
- **Nothing is contacted on its own:** the Home page lists saved servers (light grey until connected) and connects only when one is opened.
- **Tested** against OpenSSH's real `sftp-server` over pipes (all of the protocol, copy trees both ways, overwrite, permanent delete, moves across file systems) and against a fake `ssh` that serves it (the command line, the password handling, refused logins). A real `sshd` is not available in the test environment: the whole chain through real ssh has to be tried by hand on a real server.
- Not yet: SCP (shell-based browsing, `scp` for contents), WebDAV, FTP, OPDS and Subsonic, remote undo rules, free space on a server, a progress bar for a listing of a huge remote folder.

## 13. SCP (2026-10-21)

The `scp` kind of connection is a shell session, not the `scp` program: `ssh -T host sh` stays open and `core/shellclient.py` sends POSIX commands with an end marker and the exit status after each. Listing is `ls -la` (parsed, with the server's time zone from `date +%z`), contents are read with `dd` in 64 KB blocks and written as base64, names are quoted with `shlex.quote`. `ShellClient` offers the same calls as `SftpClient`, so `SftpFileSystem("scp")` and the plans above it are unchanged. A server that permits only `scp -t` and no shell cannot be browsed; that case stays out. Tested against a real POSIX shell on pipes and through a fake ssh.

## 14. WebDAV (2026-10-21)

`core/davclient.py` is a WebDAV client on `http.client` and `ssl` (no new dependency) with the same calls as `SftpClient`, so `SftpFileSystem("webdav")` and the plans above it are unchanged. PROPFIND for listing and stat, GET with ranges, PUT when a file is closed, MKCOL, DELETE (a folder only when empty), MOVE with `Overwrite`. Basic and Digest logins (the formula is checked against the example of the RFC), redirects on the same host, one reconnect when a kept connection was dropped. TLS: the system's trust; a server's own certificate is pinned by its SHA-256 fingerprint after the owner agrees, and a changed one is refused. Replies with a DOCTYPE are refused and capped at 64 MB. The base folder of a connection is the `Session.base` prefix. Tested against an in-process WebDAV server (`tests/dav_server.py`, with a self-signed certificate made by openssl). Not yet: LOCK, PROPPATCH for dates, `Expect: 100-continue`, resuming a failed upload.

## 15. FTP and FTPS (2026-10-21)

`core/ftpclient.py` on `ftplib`, same calls as the other clients. Explicit TLS only (`AUTH TLS`, `PBSZ 0`, `PROT P`), the TLS session of the control connection reused for the data connections (`ftplib` does not do that by itself), the certificate pinned by fingerprint like WebDAV. `MLSD` when `FEAT` lists `MLST`, else `LIST` parsed in Unix and DOS styles with a one-time warning. One main connection for commands and one connection per open file, pooled, at most two reading and two writing. `MFMT` for dates when offered. Tested against an in-process FTP server (`tests/ftp_server.py`) that demands session reuse, serves a Unix or DOS listing without MLSD, and reports the most connections open at once. Not yet: implicit FTPS (port 990), `ABOR`, resuming uploads, active mode.

## 16. OPDS and Subsonic (2026-10-21)

Two read-only catalogues, shown as folders through the same `SftpFileSystem(scheme)` and `Session` as the other servers, so the Home page, the saved connections, the login, the certificate question, the panels, copy, the viewer and search need nothing new.

* `core/catalogclient.py` is the shared base. It subclasses `DavClient` for the web side (HTTP and HTTPS, a pinned certificate, Basic and Digest login, redirects to the same host only, a capped reply) and turns a service's lists into `listdir`, `stat`, `open` and `read_blocks`. Everything that writes is refused (`PermissionError`) and the connection is always read-only, whatever the saved file says. Names come from titles (characters a file name cannot hold become `_`; the second of two equal names gets ` (2)`). A listing is kept for two minutes. A file is read with `Range` requests; a server that ignores them has its whole reply kept for the next blocks (up to the reply cap of 64 MB). A size the catalogue did not give is asked for with HEAD.
* **OPDS** (`core/opds.py` parses, `core/opdsclient.py` walks): Atom feeds of OPDS 1.x and JSON feeds of OPDS 2.0. Navigation entries are folders, acquisition entries are files, one for each format (`Title.epub`, `Title.pdf`); buy, borrow, sample and preview links are left out; pages (`rel="next"`) are followed up to 40 pages or 5000 entries; a link to another computer is left out. "Start in" is the catalogue's address on the server (`/opds`, `/opds/v1.2/catalog`...). A reply with a document type declaration is refused. Not built: search (OpenSearch), covers, facets, Kavita-style entries that are both a folder and a book.
* **Subsonic** (`core/subsonicclient.py`): `Artists / artist / album / tracks` and `Playlists / playlist / tracks`. The login is the Subsonic token (`md5(password + salt)`, a new salt for every request): the password is never sent, but over plain HTTP the token can be copied, so the dialog says when the connection is not encrypted. A track is the original file (the `download` call), so a copy is the file the server holds. "Start in" is the folder the server lives in, when it is not at the top (`/navidrome`). Not built: covers, streaming transcoded formats, starred, recent and random lists, scrobbling.
* **"Stream to the player":** Enter on a track or a book downloads it to a temporary folder (with a question above 200 MB) and hands it to the program Windows has for it, the same way a file inside an archive opens. Nothing plays before the download is complete.
* Not reachable from the command line or the assistant, like the other servers: they need an interactive login.
* Tested against in-process servers (`tests/catalog_server.py`: an Atom and a JSON catalogue with paging, Basic login and range support, and a Subsonic API with token login), not against Calibre-Web, Kavita, Komga or Navidrome themselves.
