"""Taildrop: sending files to another device of the Tailscale network, and fetching the files others sent here. Qt-free.

It only runs the local ``tailscale`` program, as ``core/tailnet.py`` does: ``tailscale file cp <file> <device>:`` sends one file and
``tailscale file get <folder>`` takes the files waiting for this device into a folder. Both take as long as the files need, so call them
on a thread. Every run goes through a ``runner(command, cancel)`` that returns ``(exit code, the program's own words)``, so tests need no
Tailscale. A Cancel stops the program that is running.

Not used, because it could not be checked here: ``file get``'s ``--conflict`` and ``--wait`` options. The caller receives into an empty
folder and places the files itself, so a clash is never settled by Tailscale.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

from .platform import no_window_flags

POLL = 0.2                     # seconds between two looks at the Cancel while the program runs


@dataclass(frozen=True)
class SendResult:
    path: str
    ok: bool
    message: str = ""          # the program's own words when it failed, or why the file was not sent


@dataclass
class ReceiveResult:
    ok: bool
    message: str = ""          # the program's own words when it failed
    files: list = field(default_factory=list)       # the names now in the folder


def send_command(exe: str, path: str, host: str) -> list:
    """The command that sends one file. ``host`` is the device's address or name; the colon after it is how the program tells a device
    from a file. One file a time: a Cancel then stops between files, and an error names its file."""
    return [exe, "file", "cp", path, f"{host}:"]


def receive_command(exe: str, folder: str) -> list:
    return [exe, "file", "get", folder]


def run_command(command: list, cancel=None, popen: Callable = subprocess.Popen) -> tuple:
    """Run a command to its end; ``(exit code, output)``. When ``cancel`` (a ``CancelToken``) is set the program is stopped and the
    code is None. A program that cannot start is code -1 with the system's own words."""
    try:
        proc = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL, creationflags=no_window_flags())
    except OSError as e:
        return -1, str(e)
    while True:
        try:
            out, _ = proc.communicate(timeout=POLL)
            return proc.returncode, (out or "").strip()
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.cancelled:
                proc.kill()
                proc.communicate()
                return None, "Cancelled"


def _words(code, text: str) -> str:
    return text.strip() or f"tailscale stopped with code {code}"


def send_files(exe: str, paths: list, host: str, *, runner: Callable = run_command, cancel=None, progress: Optional[Callable] = None,
               on_file: Optional[Callable] = None) -> list:
    """Send the files one after the other: a ``SendResult`` for each that was tried (a cancel ends the list there). Folders and missing
    files are not sent, with the reason. ``progress(done, total)`` counts files; ``on_file(name)`` is told which one starts."""
    results = []
    total = len(paths)
    for number, path in enumerate(paths):
        if cancel is not None and cancel.cancelled:
            break
        if progress:
            progress(number, total)
        if on_file:
            on_file(os.path.basename(path))
        if os.path.isdir(path):
            results.append(SendResult(path, False, "Taildrop sends files, not folders. Pack the folder to a zip file first."))
            continue
        if not os.path.isfile(path):
            results.append(SendResult(path, False, "The file is not there."))
            continue
        code, text = runner(send_command(exe, path, host), cancel)
        if code is None:
            break
        results.append(SendResult(path, code == 0, "" if code == 0 else _words(code, text)))
    if progress and not (cancel is not None and cancel.cancelled):
        progress(total, total)
    return results


def sent_summary(results: list, device: str) -> str:
    """One line for the status bar: what was sent where, and what failed."""
    good = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    text = f"Sent {len(good)} file{'s' if len(good) != 1 else ''} to {device}" if good else ""
    if bad:
        text += (". " if text else "") + f"{len(bad)} not sent"
    return text or "Nothing was sent"


def failure_text(results: list) -> str:
    """The failed files with the program's own words, one line each; empty when all went well."""
    return chr(10).join(f"{os.path.basename(r.path)}: {r.message}" for r in results if not r.ok)


def receive_files(exe: str, folder: str, *, runner: Callable = run_command, cancel=None) -> ReceiveResult:
    """Take the files waiting for this device into ``folder`` (which should be empty and new: the caller places them from there)."""
    code, text = runner(receive_command(exe, folder), cancel)
    if code is None:
        return ReceiveResult(False, "Cancelled")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    if code != 0:
        return ReceiveResult(False, _words(code, text), names)
    return ReceiveResult(True, text, names)
