"""The command line under the panels (spec C4): placeholders and running one command.

Placeholders, quoted for the chosen interpreter:  ``%f`` the item under the cursor (name),
``%p`` its full path, ``%s`` the marked items (else the item under the cursor), ``%d`` this panel's
folder, ``%o`` the other panel's folder, ``%%`` a percent sign. Anything else after a percent sign is
left as typed. A command runs as the normal user, with no console window, its output captured.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .platform import IS_WINDOWS, console_encoding
from .terminals import Launch, Profile, Which, quote_for, run_launch


@dataclass(frozen=True)
class Placeholders:
    current_name: str = ""
    current_path: str = ""
    marked: tuple = ()
    folder: str = ""
    other: str = ""


def expand(template: str, ph: Placeholders, profile: Profile) -> str:
    """Replace the placeholders. Raises ``UnsafeArgument`` for a name the interpreter cannot take
    safely and ``ValueError`` for a placeholder with nothing to put in it."""
    out: list = []
    i = 0
    while i < len(template):
        ch = template[i]
        nxt = template[i + 1] if i + 1 < len(template) else ""
        if ch == "%" and nxt == "%":
            out.append("%")
            i += 2
        elif ch == "%" and nxt in ("f", "p", "s", "d", "o"):
            out.append(_value(nxt, ph, profile))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _value(key: str, ph: Placeholders, profile: Profile) -> str:
    if key == "f":
        parts = [ph.current_name]
    elif key == "p":
        parts = [ph.current_path]
    elif key == "s":
        parts = list(ph.marked) or [ph.current_path]
    elif key == "d":
        parts = [ph.folder]
    else:
        parts = [ph.other]
    if not all(parts):
        raise ValueError(f"%{key} has nothing to use here (no item under the cursor, or no other folder)")
    return " ".join(quote_for(profile, p) for p in parts)


@dataclass
class CommandResult:
    finished: bool
    exit_code: Optional[int]
    output: str
    pid: int
    truncated: bool = False


def run_command(profile: Profile, command: str, cwd: str, *, wait: float = 1.5, max_output: int = 1_000_000,
                which: Which = shutil.which, popen: Callable = subprocess.Popen,
                on_finish: Optional[Callable[["CommandResult"], None]] = None) -> CommandResult:
    """Run ``command`` and wait up to ``wait`` seconds. A command that is still running after that (a
    program that opens its own window, a long job, a slow interpreter start) is left running and reported
    as not finished; when it ends later ``on_finish(result)`` is called from a background thread with its
    exit code and output. Output past ``max_output`` is drained and dropped so a command can never block
    on a full pipe."""
    launch: Launch = run_launch(profile, command, cwd, which)
    argv = launch.argv
    if isinstance(argv, str) and not IS_WINDOWS:
        argv = shlex.split(argv)
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    try:
        proc = popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     creationflags=flags)
    except OSError as e:                 # the interpreter or the program could not be started at all
        return CommandResult(True, 127, f"Cannot start: {e.strerror or e}", 0)
    chunks: list = []
    state = {"size": 0, "cut": False}
    lock = threading.Lock()

    def drain() -> None:
        for block in iter(lambda: proc.stdout.read(4096), b""):
            with lock:
                if state["size"] < max_output:
                    chunks.append(block)
                    state["size"] += len(block)
                else:
                    state["cut"] = True

    reader = threading.Thread(target=drain, daemon=True, name="dossier-command-output")
    reader.start()
    def result(code, finished: bool) -> CommandResult:
        with lock:
            raw = b"".join(chunks)
            cut = state["cut"] or len(raw) > max_output
            raw = raw[:max_output]
        return CommandResult(finished, code, raw.decode(console_encoding(), errors="replace"), proc.pid, cut)

    try:
        code = proc.wait(timeout=wait)
        reader.join(timeout=2)
        return result(code, True)
    except subprocess.TimeoutExpired:
        pass

    if on_finish is not None:
        def watch() -> None:
            code = proc.wait()
            reader.join(timeout=2)
            on_finish(result(code, True))

        threading.Thread(target=watch, daemon=True, name="dossier-command-watch").start()
    return result(None, False)
