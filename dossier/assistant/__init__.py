"""Letting an AI assistant work with Dossier (spec section 12): a local MCP server, started by the assistant's program as ``dossier mcp``.

It talks over standard input and output only (no network listener), and it is made of the same core functions as the window and the
command line, so nothing exists only in the assistant's path. What keeps it safe:

* **Off until the owner switches it on** (Settings > Assistant Access), and **limited to the folders the owner lists**: every path an
  assistant names is resolved (links and ``..`` included) and must lie inside one of them.
* **Read-only by default.** The tools that read are the default; the tools that change files only *propose*: the assistant gets a preview,
  asks to commit it, and the request waits for the owner's confirmation in the Dossier window. Without that window, or without the
  owner's agreement, nothing changes. Each kind of change has its own switch.
* **Everything it reads is data.** File names, text, tags and notes can say anything; they are handed over as data and the server's own
  instructions say so. Nothing a file contains can start a change.
* **Every call is logged** in a file the owner can open and delete.

The server process and the window do not share memory, so they share a small folder of files (``bridge.py``): the window publishes what
it shows and the shared selection, the server writes requests, and the window answers them.
"""
