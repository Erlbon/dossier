"""The single source of truth for the program's name and build number.

The build number has the same form as in the Redactor apps: ``YYYY-MM-DD#NN``, the date of the check-in and a
counter that restarts at 01 each day. It is changed only by ``python bump_version.py`` (never by hand), in the same
check-in as the code change and a matching CHANGELOG.md entry. Release tags are ``v`` + the number with ``#`` turned
into ``-``, for example ``v2026-10-19-01``.
"""
from __future__ import annotations

APP_NAME = "Dossier"
APP_VERSION = "2026-10-21#14"
APP_REPO_URL = "https://github.com/Erlbon/dossier"


def tag_of(version: str = APP_VERSION) -> str:
    return "v" + version.replace("#", "-")
