"""Time Dossier on big folders: listing, sorting, marking and copying 10,000 and 100,000 files (comparison review 2026-11-05, card 4).

    python tools/time_big_folders.py                      # local, in C:\\Temp\\Claude\\dossier-timing (made, and removed at the end)
    python tools/time_big_folders.py --where \\\\nas\\share\\dossier-timing --sizes 10000
    python tools/time_big_folders.py --keep               # leave the test folders for Explorer, Total Commander, Double Commander

It uses the same code as the window (the file system, the list model with its sort, the selection, plan_copy and execute), on a hidden
offscreen window, so the numbers are Dossier's own and not a test double's. Explorer, TC and DC cannot be timed from here: with --keep,
open the folders in them and time them by hand as yardsticks for speed only. The test folders are written once per size and reused.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEFAULT_WHERE = os.path.join("C:" + os.sep, "Temp", "Claude", "dossier-timing") if os.name == "nt" else "/tmp/dossier-timing"
FILE_BYTES = 2048


def make_folder(path: str, count: int) -> None:
    """``count`` small files with varied names, sizes and times (sorting has work to do), unless it is there already."""
    marker = os.path.join(path, ".complete")
    if os.path.exists(marker):
        return
    os.makedirs(path, exist_ok=True)
    data = os.urandom(FILE_BYTES)
    now = time.time()
    for i in range(count):
        name = os.path.join(path, f"file {i * 7919 % count:06d} {'abcdefgh'[i % 8]}.{('txt', 'jpg', 'pdf', 'mp3')[i % 4]}")
        with open(name, "wb") as f:
            f.write(data[: (i * 37) % FILE_BYTES + 1])
        os.utime(name, (now - i * 60, now - i * 60))
    open(marker, "w").close()


def timed(label: str, work, results: list):
    start = time.perf_counter()
    out = work()
    seconds = time.perf_counter() - start
    results.append((label, seconds))
    print(f"  {label:<34} {seconds:8.2f} s", flush=True)
    return out


def run(where: str, count: int) -> list:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from dossier.core.ops import execute, plan_copy
    from dossier.core.selection import SelectionStore
    from dossier.core.vfs import LocalFileSystem, sort_entries
    from dossier.gui.models import FolderModel

    QApplication.instance() or QApplication([])
    fs = LocalFileSystem()
    folder = os.path.join(where, f"files-{count}")
    print(f"{count:,} files in {folder}")
    results: list = []
    timed("make the test folder (once)", lambda: make_folder(folder, count), results)
    entries = timed("list the folder", lambda: fs.list(folder), results)
    timed("sort by name (folders first)", lambda: sort_entries(entries), results)
    selection = SelectionStore()
    model = FolderModel(fs, selection)
    timed("show it in the list model", lambda: model.set_entries(folder, entries), results)
    for column, label in ((2, "size"), (3, "date")):
        timed(f"sort the list by {label}", lambda c=column: model.sort(c, Qt.SortOrder.DescendingOrder), results)
    paths = [e.path for e in entries if not e.is_dir]
    timed("mark every file", lambda: selection.add(paths), results)
    timed("invert the marks", lambda: selection.invert(paths), results)
    target = os.path.join(where, f"copy-{count}")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    plan = timed("plan the copy of the folder", lambda: plan_copy(fs, [folder], target), results)
    timed("copy it", lambda: execute(plan, fs), results)
    shutil.rmtree(target, ignore_errors=True)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--where", default=DEFAULT_WHERE, help="the folder the test folders go in (local, or a share on the NAS)")
    parser.add_argument("--sizes", default="10000,100000", help="numbers of files, separated by commas")
    parser.add_argument("--keep", action="store_true", help="leave the test folders (for timing Explorer, TC and DC by hand)")
    args = parser.parse_args(argv)
    os.makedirs(args.where, exist_ok=True)
    table = []
    try:
        for count in (int(s) for s in args.sizes.split(",") if s.strip()):
            table.append((count, run(args.where, count)))
    finally:
        if not args.keep:
            shutil.rmtree(args.where, ignore_errors=True)
    print()
    print("| Step | " + " | ".join(f"{c:,} files" for c, _r in table) + " |")
    print("|---|" + "---:|" * len(table))
    for i, (label, _s) in enumerate(table[0][1] if table else []):
        print(f"| {label} | " + " | ".join(f"{r[i][1]:.2f} s" for _c, r in table) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
