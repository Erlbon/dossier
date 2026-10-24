"""The single source of truth for the program's name and build number.

The build number has the same form as in the Redactor apps: ``YYYY-MM-DD#NN``, the date of the check-in and a
counter that restarts at 01 each day. It is changed only by ``python bump_version.py`` (never by hand), in the same
check-in as the code change and a matching CHANGELOG.md entry.

A **release** has a version of its own, ``RELEASE`` (``0.4``): the owner decides the main numbers, and the release tag is ``v`` +
that (``v0.4``). The release workflow refuses a tag that is not ``v`` + ``RELEASE``, so the number is changed here, in the check-in that
is released, and nowhere else. The build number still says exactly which check-in a program was made from.
"""
from __future__ import annotations

APP_NAME = "Dossier"
APP_VERSION = "2026-10-24#08"
RELEASE = "0.4"
APP_REPO_URL = "https://github.com/Erlbon/dossier"


def tag_of(version: str = APP_VERSION) -> str:
    """The tag of a build (``v2026-10-19-03``): for telling builds apart, not a release."""
    return "v" + version.replace("#", "-")


def release_tag(release: str = RELEASE) -> str:
    """The tag of a release: ``v0.4``."""
    return "v" + release


def release_title() -> str:
    return f"{APP_NAME} {RELEASE}"
