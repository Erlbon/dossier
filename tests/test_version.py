"""The build number: same form as the Redactor apps, bumped by one script, shown in the window, in the changelog."""
import datetime
import os
import re

import pytest

import bump_version
from dossier.core import version

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_build_number_has_the_redactor_form():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}#\d{2,}", version.APP_VERSION)
    datetime.date.fromisoformat(version.APP_VERSION.split("#")[0])             # a real date
    assert version.tag_of("2026-10-19#03") == "v2026-10-19-03"


def test_a_release_has_its_own_version_and_tag():
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", version.RELEASE)
    assert version.release_tag() == "v" + version.RELEASE and version.release_tag("0.4") == "v0.4" and version.release_title() == f"Dossier {version.RELEASE}"


def test_the_same_day_counts_up_and_a_new_day_starts_again_at_one():
    day = datetime.date(2026, 10, 19)
    assert bump_version.next_version("2026-10-19", 1, day) == "2026-10-19#02"
    assert bump_version.next_version("2026-10-19", 9, day) == "2026-10-19#10"
    assert bump_version.next_version("2026-10-18", 7, day) == "2026-10-19#01"
    assert bump_version.next_version("2026-10-19", 99, day) == "2026-10-19#100"
    assert bump_version.pep440_from("2026-10-19#03") == "2026.10.19.3"


def make_files(tmp_path, stored="2026-10-19#05", project_version="2026.10.19.5"):
    v = tmp_path / "version.py"
    v.write_text(f'APP_NAME = "X"\nAPP_VERSION = "{stored}"\nAPP_REPO_URL = "u"\n', encoding="utf-8")
    p = tmp_path / "pyproject.toml"
    p.write_text(f'[project]\nname = "x"\nversion = "{project_version}"\ndescription = "d"\n', encoding="utf-8")
    return v, p


def test_the_script_rewrites_only_the_build_line_and_keeps_pyproject_in_step(tmp_path):
    v, p = make_files(tmp_path)
    old, new = bump_version.bump(v, p, today=datetime.date(2026, 10, 19))
    assert (old, new) == ("2026-10-19#05", "2026-10-19#06")
    assert 'APP_VERSION = "2026-10-19#06"' in v.read_text(encoding="utf-8") and 'APP_NAME = "X"' in v.read_text(encoding="utf-8")
    assert 'version = "2026.10.19.6"' in p.read_text(encoding="utf-8") and 'name = "x"' in p.read_text(encoding="utf-8")
    old, new = bump_version.bump(v, p, today=datetime.date(2026, 10, 20))
    assert new == "2026-10-20#01" and 'version = "2026.10.20.1"' in p.read_text(encoding="utf-8")


def test_a_file_without_a_build_line_is_refused_with_a_clear_message(tmp_path):
    v = tmp_path / "version.py"
    v.write_text("APP_NAME = 'x'\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="APP_VERSION"):
        bump_version.bump(v, None)


def test_the_repository_files_agree_with_each_other():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        project = re.search(r'(?m)^version = "(.*)"$', f.read()).group(1)
    assert project == bump_version.pep440_from(version.APP_VERSION)


def test_the_changelog_has_a_section_for_the_current_build():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    assert re.search(rf"(?m)^## {re.escape(version.APP_VERSION)} -- \S", text), "add a CHANGELOG section for this build"
    top = re.search(r"(?m)^## (\d{4}-\d{2}-\d{2}#\d+)", text).group(1)
    assert top == version.APP_VERSION                                         # the newest section is the current build


# in the window ------------------------------------------------------------------------------------------
pytest.importorskip("PyQt6")
from tests.test_gui_commander import app, world  # noqa: E402,F401


def test_the_build_number_is_in_the_status_line_and_in_the_about_box(world):
    win, dialogs, *_ = world
    assert version.APP_VERSION in win.build_label.text()
    win.about()
    title, text = dialogs.infos[-1]
    assert "Dossier" in title and f"Build {version.APP_VERSION}" in text and version.APP_REPO_URL in text


def test_the_help_menu_has_about(world):
    win, *_ = world
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    assert [a.text() for a in menus["Help"].actions() if not a.isSeparator()] == ["Slowness Log", "Keyboard Shortcuts...", "About Dossier..."]
