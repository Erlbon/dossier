"""Starting Dossier: a missing package gets a plain message, and every way of starting it from a checkout works."""
import os
import subprocess
import sys

import pytest

from dossier.gui import check_install
from dossier.gui.check_install import check_or_explain, message, missing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def finder(absent):
    return lambda module: None if module.split(".")[0] in absent else object()


def test_everything_present_gives_nothing_missing():
    assert missing(finder(set())) == [] and check_or_explain(finder(set())) is True


def test_each_missing_package_is_named_with_what_it_is_for():
    problems = missing(finder({"redactor_common", "PyQt6"}))
    assert [p for p, _w in problems] == ["PyQt6", "redactor_common"]
    text = message(problems)
    assert "redactor_common" in text and "2026-10-20-02" in text and check_install.INSTALL in text and "Traceback" not in text


def test_an_old_redactor_common_without_the_needed_module_counts_as_missing():
    def find(module):
        return None if module == "redactor_common.core.meta_fields" else object()
    assert [p for p, _w in missing(find)] == ["redactor_common"]


def test_the_explanation_is_printed_and_shown(capsys):
    shown = []
    assert check_or_explain(finder({"send2trash"}), show=shown.append) is False
    assert "send2trash" in capsys.readouterr().err and shown and "send2trash" in shown[0]


def test_a_failing_finder_is_treated_as_missing_not_as_a_crash():
    def broken(module):
        raise ValueError("bad")
    assert len(missing(broken)) == len(check_install.REQUIRED)


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))


def test_python_m_dossier_check_works_from_the_checkout():
    r = run("-m", "dossier", "--check")
    assert r.returncode == 0 and "Everything Dossier needs is installed" in r.stdout


def test_the_file_can_be_started_directly_and_from_another_folder(tmp_path):
    r = run(os.path.join(ROOT, "dossier", "__main__.py"), "--check", cwd=str(tmp_path))
    assert r.returncode == 0 and "installed" in r.stdout, r.stderr
    r = run(os.path.join(ROOT, "dossier"), "--check", cwd=str(tmp_path))           # python path/to/dossier
    assert r.returncode == 0 and "installed" in r.stdout, r.stderr


def test_main_stops_with_the_message_when_something_is_missing(monkeypatch):
    from dossier.gui import app
    monkeypatch.setattr(check_install, "check_or_explain", lambda *a, **k: False)
    assert app.main(["dossier"]) == 1


def test_the_package_metadata_lists_everything_the_program_imports():
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    for name in ("send2trash", "PyQt6", "PyQt6-QScintilla", "redactor_common"):
        assert name in text.split("[project.optional-dependencies]")[0], name
