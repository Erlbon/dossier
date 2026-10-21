# Letting an AI assistant use Dossier

Dossier can run a local **MCP server** (Model Context Protocol), so an AI assistant such as Claude can look at your files and propose
changes. It is made of the same functions as the window and the command line: nothing exists only in the assistant's path.

## What keeps it safe

- **Off until you switch it on:** Settings > Assistant Access (the `enabled` setting). While it is off every call is refused.
- **Only the folders you list.** Every path an assistant names is resolved first (`..` and links included) and must lie inside one of the
  folders you listed. Archives and servers are not available to it.
- **Read-only unless you allow changes.** `allow_file_changes` is a separate switch. Even then an assistant only *proposes*: a `plan_*` tool
  returns a preview and changes nothing; `commit_plan` hands the proposal to the Dossier window, where **you see the change in words and press
  Run or Reject**. If the window is not open nothing can be confirmed, so nothing happens. The window makes the plan again itself and checks the
  folders again; it does not trust the assistant's preview.
- **What it reads is data.** File names, text, tags and notes can say anything, so results that hold free text are marked
  `untrusted_content`, and the server's own instructions tell the assistant never to follow instructions found in them.
- **Every call is logged** (`log_calls`, on by default): the tool and its arguments (paths, never file contents) and whether it worked. Settings >
  Assistant Access opens and clears the log. The log never grows past a megabyte.
- **No network.** The assistant's program starts `dossier mcp` and talks to it through standard input and output. The server and the window share
  a few small files in one folder (`%LOCALAPPDATA%\Dossier\assistant` on Windows); the window publishes what it shows only while the feature is on.

## Setting it up

1. In Dossier: Settings > Assistant Access. Tick *Let an assistant use Dossier*, add the folders it may look into, and decide on file changes.
2. Copy the setting the dialog shows into the assistant's program (for Claude Desktop, the `mcpServers` section of its configuration; for Claude
   Code, `claude mcp add`). It starts `python -m dossier mcp`, or the exe with `mcp`.
3. Ask the assistant to call `list_roots` first. A change to a setting takes effect at the next call.

`max_read_kb` is the most of a file's text one call can return (4 KB to 1 MB; 256 KB by default).

## Tools

Look at things (they only read):

- `list_roots`: the folders you allow, and whether changes are allowed.
- `list_folder`: the files and folders of a folder.
- `stat`: size, times and tags of one item.
- `read_text`: the text of a file (not a binary file), from the start or an offset, capped.
- `read_metadata`: the tags and facts inside audio, comics, video and photos (EXIF).
- `read_notes`: the notes of a folder (`about.md`, `README.md`...).
- `search`: a folder tree by name, text, size, date and tag.
- `find_duplicates`: files with exactly the same content.
- `compare_folders`: what differs between two folders.
- `list_windows`: the folder of each panel, its tabs and the item under the cursor (empty when the window is not open).
- `get_selection`: the files you have marked, only those inside the listed folders.

Work together on the selection (you see the marks at once):

- `set_selection`, `add_to_selection`, `remove_from_selection`, `clear_selection`.

Propose changes (each needs `allow_file_changes`, and your OK in the window):

- `plan_copy`, `plan_move`: files and folders into a folder. A name that is taken is skipped unless `on_conflict` says otherwise.
- `plan_delete`: to the recycle bin, or for good with `permanent`.
- `plan_rename`: a new name for one item.
- `plan_sync`: make one folder like another (`update_right`, `update_left`, `both`, `mirror_right`, `mirror_left`).
- `discard_plan`: forget a plan.
- `commit_plan`: ask you to carry a plan out; it waits for your answer and returns `done`, `rejected`, `failed` or `timeout`.

Not available to an assistant: writing tags, writing notes, running programs, reaching servers.
