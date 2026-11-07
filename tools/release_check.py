"""The checks build_release.bat runs around a release build (python -m redactor_common.release publish calls that script).

    python tools/release_check.py before    the RELEASE number is not released yet under another build, and its notes exist
    python tools/release_check.py after     the built programs start: the one-file exe and the installer's one-folder build report
                                            their version, list a folder and find every package; each declares its update channel

These were steps of the old GitHub release workflow; the release tool builds and publishes on this PC now, and its gate tries the
published release for real (redactor_common docs/update-framework.md).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dossier.core.version import APP_NAME, APP_VERSION, RELEASE, release_notes, release_tag  # noqa: E402


def before() -> str:
    """"" when the release may be made; else what stops it."""
    notes = release_notes()
    if not os.path.isfile(os.path.join(ROOT, notes)):
        return f"There are no release notes: write {notes} first"
    listed = subprocess.run(["gh", "release", "list", "--limit", "200", "--json", "name,tagName"], capture_output=True, text=True,
                            cwd=ROOT)
    if listed.returncode != 0:
        return f"gh could not list the releases: {listed.stderr.strip()}"
    return taken(json.loads(listed.stdout or "[]"))


def taken(releases: list, tag: str = "", release: str = RELEASE) -> str:
    """What stops RELEASE: another build already released under the same number ("" when nothing does)."""
    tag = tag or release_tag()
    for other in releases:
        if other["name"].startswith(f"{APP_NAME} {release} (") and other["tagName"] != tag:
            return f"{APP_NAME} {release} is already released as {other['tagName']}: raise RELEASE in dossier/core/version.py first"
    return ""


def try_program(exe: str, channel: str, listing: bool) -> str:
    """"" when the built program works; else what is wrong."""
    def run(*args):
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=120, cwd=ROOT)

    if not os.path.isfile(exe):
        return f"{exe} was not built"
    version = run("--version")
    if version.returncode != 0 or APP_VERSION not in version.stdout:
        return f"{exe} --version said {version.stdout.strip()!r} {version.stderr.strip()!r}"
    if listing:
        listed = run("ls", "dist")
        if listed.returncode != 0 or "dossier.exe" not in listed.stdout:
            return f"{exe} cannot list a folder: {listed.stdout.strip()!r} {listed.stderr.strip()!r}"
    check = run("--check")
    if check.returncode != 0:
        return f"{exe} is missing a package: {check.stdout.strip()} {check.stderr.strip()}"
    answer = os.path.join(ROOT, "build", "release-check.json")
    asked = run("--check-update", "--release-tag", release_tag(), "--result-file", answer)
    try:
        with open(answer, encoding="utf-8") as f:
            said = json.load(f)
    except (OSError, ValueError):
        return f"{exe} --check-update gave no answer (exit {asked.returncode})"
    if said.get("channel") != channel:
        return f"{exe} declares update channel {said.get('channel')!r}, expected {channel!r}"
    return ""


def after() -> str:
    dist = os.path.join(ROOT, "dist")
    return (try_program(os.path.join(dist, "dossier.exe"), "windows-exe", listing=True)
            or try_program(os.path.join(dist, "dossier", "dossier.exe"), "windows-zip", listing=False))


def main(argv: list) -> int:
    step = {"before": before, "after": after}.get(argv[1] if len(argv) > 1 else "")
    if step is None:
        print(__doc__)
        return 2
    problem = step()
    if problem:
        print(f"release_check {argv[1]}: {problem}", file=sys.stderr)
        return 1
    print(f"release_check {argv[1]}: fine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
