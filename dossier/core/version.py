"""The single source of truth for the program's name and build number.

The build number has the same form as in the Redactor apps: ``YYYY-MM-DD#NN``, the date of the check-in and a
counter that restarts at 01 each day. It is changed only by ``python bump_version.py`` (never by hand), in the same
check-in as the code change and a matching CHANGELOG.md entry.

A **release** has a name of its own, ``RELEASE`` (``0.5``): the owner decides the main numbers. The release *tag* is the build's tag
(``v2026-11-02-01``), as in the Redactor apps, because Help > Check for Updates (``redactor_common`` ``selfupdate``) compares that tag
with ``APP_VERSION``. The release workflow refuses a tag that is not this build's, and the notes are ``docs/releases/v<RELEASE>.md``.
"""
from __future__ import annotations

APP_NAME = "Dossier"
APP_VERSION = "2026-11-04#06"
RELEASE = "0.5"
APP_REPO_URL = "https://github.com/Erlbon/dossier"


def tag_of(version: str = APP_VERSION) -> str:
    """The tag of a build (``v2026-10-19-03``): for telling builds apart, not a release."""
    return "v" + version.replace("#", "-")


def release_tag(version: str = APP_VERSION) -> str:
    """The tag of a release: the build's tag (``v2026-11-02-01``), which the updater reads as a version."""
    return tag_of(version)


def release_notes(release: str = RELEASE) -> str:
    """The notes of a release, by its name: ``docs/releases/v0.5.md``."""
    return f"docs/releases/v{release}.md"


def release_title() -> str:
    return f"{APP_NAME} {RELEASE}"
