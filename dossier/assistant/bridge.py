"""The files the Dossier window and the assistant's server share. They are separate programs with no shared memory and no network between
them, so they talk through small JSON files in one folder (``paths.data_dir``), each written whole and renamed into place, so a reader never
sees half a file.

* ``state.json``: written by the window while the assistant feature is on: what each panel shows and the shared selection. It carries the
  time it was written, so a reader can tell a window that is running from one that was closed.
* ``requests/<id>.json``: written by the server: a change to the selection, or a change to files to be confirmed by the owner.
* ``responses/<id>.json``: written by the window when it has dealt with a request (done, rejected, failed).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

from . import paths

FRESH = 15.0               # a state older than this (seconds) is from a window that is not running
EXPIRES = 600.0            # a request nobody answered for this long is dropped
POLL = 0.25


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False)
    for attempt in range(25):                         # on Windows a file somebody is reading cannot be replaced for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.02)


def read_json(path: str) -> Optional[dict]:
    for attempt in range(5):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):         # being replaced at this moment: look again
            time.sleep(0.02)
        except OSError:
            return None
    return None


# the window's state ----------------------------------------------------------------------------------------------------------------------
def publish_state(state: dict) -> None:
    write_json(paths.state_file(), {**state, "updated": time.time()})


def read_state() -> dict:
    """What the window last published, with ``window_running`` (it published recently) and ``age`` in seconds."""
    data = read_json(paths.state_file())
    if data is None:
        return {"window_running": False, "panels": [], "selection": [], "age": None}
    age = max(0.0, time.time() - float(data.get("updated", 0) or 0))
    return {**data, "window_running": age < FRESH, "age": round(age, 1)}


def clear_state() -> None:
    try:
        os.remove(paths.state_file())
    except OSError:
        pass


# requests and responses -------------------------------------------------------------------------------------------------------------------
def post_request(kind: str, payload: dict) -> str:
    """Leave a request for the window; returns its id."""
    rid = uuid.uuid4().hex[:12]
    write_json(os.path.join(paths.requests_dir(), rid + ".json"), {"id": rid, "time": time.time(), "kind": kind, "payload": payload})
    return rid


def wait_response(rid: str, timeout: float) -> Optional[dict]:
    """The window's answer to request ``rid``, or None when none came in ``timeout`` seconds."""
    end = time.monotonic() + timeout
    target = os.path.join(paths.responses_dir(), rid + ".json")
    while True:
        data = read_json(target)
        if data is not None:
            try:
                os.remove(target)
            except OSError:
                pass
            return data
        if time.monotonic() >= end:
            return None
        time.sleep(POLL)


def withdraw_request(rid: str) -> None:
    try:
        os.remove(os.path.join(paths.requests_dir(), rid + ".json"))
    except OSError:
        pass


def pending_requests() -> list:
    """The requests waiting for the window, oldest first (the window calls this). Expired and unreadable ones are removed."""
    folder = paths.requests_dir()
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return []
    out = []
    for name in names:
        full = os.path.join(folder, name)
        data = read_json(full)
        if data is None or time.time() - float(data.get("time", 0) or 0) > EXPIRES:
            try:
                os.remove(full)
            except OSError:
                pass
            continue
        out.append(data)
    return sorted(out, key=lambda d: d.get("time", 0))


def answer(rid: str, status: str, message: str = "", **details) -> None:
    """The window's answer to a request (and the request is taken off the queue)."""
    write_json(os.path.join(paths.responses_dir(), rid + ".json"), {"id": rid, "status": status, "message": message, **details})
    withdraw_request(rid)
