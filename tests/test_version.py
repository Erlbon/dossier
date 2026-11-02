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


def test_a_release_is_named_by_its_number_and_tagged_by_its_build():
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", version.RELEASE)
    assert version.release_title() == f"Dossier {version.RELEASE}"
    assert version.release_tag() == version.tag_of(version.APP_VERSION) and version.release_tag("2026-11-02#01") == "v2026-11-02-01"
    assert version.release_notes("0.5") == "docs/releases/v0.5.md"


def test_the_updater_reads_the_release_tag_as_this_build():
    from redactor_common.core import selfupdate
    assert selfupdate.parse_version(version.release_tag()) == selfupdate.parse_version(version.APP_VERSION)
    assert selfupdate.asset_name("dossier", "win32") == "dossier.exe"                # the file the release workflow uploads


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
    assert [a.text() for a in menus["Help"].actions() if not a.isSeparator()] == ["Keyboard Shortcuts...", "Documentation (Online)", "What's New (Online)",
                                                                                   "Check for Updates...", "Check for Updates Once a Day",
                                                                                   "Slowness Log", "About Dossier..."]
    assert menus["Help"].actions()[-1].text() == "About Dossier..."                     # About comes last, as in every other program


def test_the_help_menu_opens_the_project_pages(world, monkeypatch):
    win, *_ = world
    opened = []
    monkeypatch.setattr(win, "open_web_page", opened.append)
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    for action in menus["Help"].actions():
        if action.text() in ("Documentation (Online)", "What's New (Online)"):
            action.trigger()
    assert opened == [version.APP_REPO_URL, version.APP_REPO_URL + "/blob/main/CHANGELOG.md"]


# updates -----------------------------------------------------------------------------------------------------------------------------
def test_the_daily_check_is_off_by_default_and_the_switch_is_kept_beside_the_settings(world):
    win, *_ = world
    assert win.updates.repo == "Erlbon/dossier" and win.updates.slug == "dossier"
    assert os.path.normpath(os.path.dirname(str(win.updates.settings.path))) == os.path.normpath(os.path.dirname(win.settings.fileName()))
    assert not win.act_daily_update.isChecked() and not win.updates.settings.enabled and not win.updates.settings.due()
    win.act_daily_update.setChecked(True)
    assert win.updates.settings.enabled and win.updates.settings.due()
    win.act_daily_update.setChecked(False)
    assert not win.updates.settings.enabled


def test_check_for_updates_asks_github_and_says_when_this_is_the_newest(world, monkeypatch):
    from redactor_common.core import selfupdate
    from redactor_common.gui import update_controller
    win, *_ = world
    asked, told = [], []
    newest = selfupdate.Release(version.release_tag(), selfupdate.parse_version(version.APP_VERSION), "", "")
    monkeypatch.setattr(win.updates, "_latest", lambda: asked.append(1) or newest)
    monkeypatch.setattr(update_controller, "run_busy", lambda parent, label, fn, **kw: fn())
    monkeypatch.setattr(update_controller.QMessageBox, "information", lambda *a: told.append(a[2]))
    menus = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    next(a for a in menus["Help"].actions() if a.text() == "Check for Updates...").trigger()
    assert asked == [1] and "newest version of Dossier" in told[-1]


def test_an_update_left_behind_is_cleaned_up_at_start(tmp_path, monkeypatch):
    from dossier.gui import app as app_module
    exe = tmp_path / "dossier.exe"
    exe.write_bytes(b"new")
    (tmp_path / "dossier.exe.old").write_bytes(b"old")
    monkeypatch.setattr(app_module.sys, "executable", str(exe))
    monkeypatch.setattr(app_module.sys, "frozen", True, raising=False)
    app_module.clean_up_after_update()
    assert exe.exists() and not (tmp_path / "dossier.exe.old").exists()
