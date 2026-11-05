"""How long Dossier takes to start: from the start of the process to a window you can type in (comparison review 2026-11-05, card 2).

    python tools/time_startup.py                              # from the source, and dist\\dossier.exe when it is there
    python tools/time_startup.py --exe "C:\\path\\to\\dossier.exe" --runs 5

Each run starts the program with DOSSIER_STARTUP_PROBE set: the window prints ``dossier-ready`` once it is shown and its event loop has
run once, then closes itself. The first run of an exe is kept apart (a cold start, files not yet in the disk cache). The window opens on
no screen (Qt's offscreen platform), with its own settings file in a temporary folder, so nothing of yours is changed and nothing takes the
focus.
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def one_start(command: list, env: dict, timeout: float = 60.0) -> float:
    start = time.perf_counter()
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=ROOT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for line in iter(p.stdout.readline, b""):
            if b"dossier-ready" in line:
                seconds = time.perf_counter() - start
                p.wait(timeout=timeout)
                return seconds
            if time.perf_counter() - start > timeout:
                break
    finally:
        if p.poll() is None:
            p.kill()
    raise RuntimeError(f"{command[0]} did not report a window within {timeout:.0f} s")


def measure(label: str, command: list, runs: int, env: dict) -> None:
    first = one_start(command, env)
    rest = [one_start(command, env) for _ in range(runs)]
    print(f"{label:<28} first {first:5.2f} s   then median {statistics.median(rest):5.2f} s  (min {min(rest):.2f}, max {max(rest):.2f})",
          flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--exe", action="append", default=[], help="an exe to time (may be given more than once)")
    parser.add_argument("--runs", type=int, default=5, help="warm runs after the first (default 5)")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="dossier-startup-") as home:
        # its own settings file (never yours), and the offscreen platform: no window appears on the screen or takes the focus
        env = {**os.environ, "DOSSIER_STARTUP_PROBE": home, "LOCALAPPDATA": home, "XDG_CONFIG_HOME": home, "QT_QPA_PLATFORM": "offscreen"}
        measure("from the source", [sys.executable, "-m", "dossier"], args.runs, env)
        exes = args.exe or [p for p in (os.path.join(ROOT, "dist", "dossier.exe"),) if os.path.isfile(p)]
        for exe in exes:
            measure(os.path.basename(os.path.dirname(exe)) + os.sep + os.path.basename(exe), [exe], args.runs, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
