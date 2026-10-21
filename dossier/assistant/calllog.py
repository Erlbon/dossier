"""The log of what an assistant did (X5): one JSON line per call, with the tool, its arguments (paths, never file contents), whether it worked
and how long it took. It is a file the owner can open and delete; it never grows past a megabyte (the newest half is kept)."""
from __future__ import annotations

import json
import os
import time

from . import paths

MAX_BYTES = 1024 * 1024
ARG_LIMIT = 300


def _short(value):
    if isinstance(value, str):
        return value if len(value) <= ARG_LIMIT else value[:ARG_LIMIT] + "..."
    if isinstance(value, (list, tuple)):
        return [_short(v) for v in value[:20]] + (["..."] if len(value) > 20 else [])
    if isinstance(value, dict):
        return {str(k): _short(v) for k, v in list(value.items())[:20]}
    return value


def record(tool: str, args: dict, ok: bool, millis: int, note: str = "") -> None:
    line = json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool, "args": _short(args), "ok": ok, "ms": millis,
                       "note": note[:200]}, ensure_ascii=False)
    path = paths.log_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
        if os.path.getsize(path) > MAX_BYTES:
            with open(path, "rb") as f:
                data = f.read()
            keep = data[len(data) // 2:]
            keep = keep[keep.find(b"\n") + 1:]
            with open(path, "wb") as f:
                f.write(keep)
    except OSError:
        pass                                              # a log that cannot be written must never stop a call


def clear() -> None:
    try:
        os.remove(paths.log_file())
    except OSError:
        pass
