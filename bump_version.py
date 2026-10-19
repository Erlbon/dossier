"""bump_version.py: run once per check-in that changes real code, instead of editing version.py by hand.

The date comes from the system clock, never from anyone's memory of what day it is. If the stored build number has
today's date the counter goes up by one; on a new day it starts again at 01. It also keeps the version in
pyproject.toml in step (``2026-10-19#03`` becomes ``2026.10.19.3``).

This is the same rule as ``redactor_common.core.version_bump`` in the Redactor apps; Dossier carries its own copy
because it does not depend on that package.

Usage:
    python bump_version.py
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent
VERSION_FILE = ROOT / "dossier" / "core" / "version.py"
PYPROJECT = ROOT / "pyproject.toml"
PATTERN = re.compile(r'APP_VERSION = "(\d{4}-\d{2}-\d{2})#(\d+)"')


def next_version(stored_date: str, stored_counter: int, today: Optional[datetime.date] = None) -> str:
    today_str = (today or datetime.date.today()).isoformat()
    counter = stored_counter + 1 if stored_date == today_str else 1
    return f"{today_str}#{counter:02d}"


def pep440_from(version: str) -> str:
    """'2026-09-04#10' -> '2026.9.4.10' (the form pyproject.toml wants)."""
    date_part, counter = version.split("#")
    year, month, day = (int(x) for x in date_part.split("-"))
    return f"{year}.{month}.{day}.{int(counter)}"


def bump(version_file: Path = VERSION_FILE, pyproject: Optional[Path] = PYPROJECT,
         today: Optional[datetime.date] = None) -> tuple:
    """Rewrite the build number. Returns (old, new). Raises SystemExit when the file has no such line."""
    text = version_file.read_text(encoding="utf-8")
    match = PATTERN.search(text)
    if not match:
        raise SystemExit(f'ERROR: no APP_VERSION = "YYYY-MM-DD#NN" line found in {version_file}')
    stored_date, stored_counter = match.group(1), int(match.group(2))
    old = f"{stored_date}#{stored_counter:02d}"
    new = next_version(stored_date, stored_counter, today)
    version_file.write_text(PATTERN.sub(f'APP_VERSION = "{new}"', text, count=1), encoding="utf-8", newline="\n")
    if pyproject is not None and pyproject.exists():
        project = pyproject.read_text(encoding="utf-8")
        project = re.sub(r'(?m)^version = ".*"$', f'version = "{pep440_from(new)}"', project, count=1)
        pyproject.write_text(project, encoding="utf-8", newline="\n")
    return old, new


if __name__ == "__main__":
    old, new = bump()
    print(f"APP_VERSION bumped: {old} -> {new}")
