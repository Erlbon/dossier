"""Git awareness in the window (plan 2026-11-07, cards 2-4): the branch and what changed in the panel's bar, a Git column, and network
drives only when switched on. Read-only: the repository is never changed by looking."""
import os
import shutil
import subprocess

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dossier.core import gitinfo  # noqa: E402
from dossier.gui.models import GIT_COL  # noqa: E402
from tests.test_gui_commander import app, pump, world  # noqa: E402,F401

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args], check=True,
                   capture_output=True)


def make_repo(folder):
    git(folder, "init", "-q", "-b", "main")
    (folder / "src").mkdir(exist_ok=True)
    (folder / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (folder / "kept.txt").write_text("kept\n", encoding="utf-8")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    (folder / "src" / "app.py").write_text("print(2)\n", encoding="utf-8")
    (folder / "new.txt").write_text("new\n", encoding="utf-8")


def cell(win, name):
    model = win.left.model
    row = model.row_of(name)
    return model.data(model.index(row, GIT_COL))


@pytest.fixture
def repo_world(world):
    win, dialogs, left, right, tmp = world
    gitinfo.SHARED_CACHE.forget()
    make_repo(left)
    win.left.refresh()
    pump(win, lambda: win.left.git_label.isVisibleTo(win.left))
    return win, left, right


def test_the_bar_shows_the_branch_and_what_changed(repo_world):
    win, left, right = repo_world
    assert "main · 1 changed, 1 new" in win.left.git_label.text()
    assert str(left) in win.left.git_label.toolTip() and "never changes" in win.left.git_label.toolTip()


def test_the_git_column_shows_each_item_and_a_folder_the_strongest_below_it(repo_world):
    win, left, right = repo_world
    assert cell(win, "new.txt") == "New" and cell(win, "kept.txt") == "" and cell(win, "src") == "Changed"
    win.left.model.sort(GIT_COL)
    names = [win.left.model.entry_at(r).name for r in range(win.left.model.entry_count())]
    assert names.index("new.txt") < names.index("kept.txt")                 # what changed comes first among the files


def test_a_folder_in_no_repository_shows_nothing(repo_world):
    win, left, right = repo_world
    win.left.set_folder(str(right))
    pump(win, lambda: not win.left.git_label.isVisibleTo(win.left))
    assert win.left.model.git_state(win.left.model.entry_at(win.left.model.entry_count() - 1)) == ""


def test_looking_never_changes_the_repository(repo_world):
    win, left, right = repo_world
    index = left / ".git" / "index"
    before = (index.stat().st_mtime_ns, index.read_bytes())
    for _ in range(3):
        win.left.refresh()
        pump(win, lambda: win.left.git_label.isVisibleTo(win.left))
    assert (index.stat().st_mtime_ns, index.read_bytes()) == before and not (left / ".git" / "index.lock").exists()


def test_a_refresh_asks_git_again(repo_world):
    win, left, right = repo_world
    (left / "kept.txt").write_text("changed now\n", encoding="utf-8")
    win.left.refresh()
    pump(win, lambda: "2 changed" in win.left.git_label.text())
    assert cell(win, "kept.txt") == "Changed"


def test_network_drives_only_when_switched_on(world):
    win, *_ = world
    share = chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "project"
    win.settings.setValue("git/network", "false")
    assert not win.left.git_allowed(share) and win.left.git_allowed(os.path.expanduser("~"))
    assert not win.act_git_network.isChecked()
    win.act_git_network.setChecked(True)
    assert win.left.git_allowed(share) and win.right.git_allowed(share) and win.git_on_network()
    win.act_git_network.setChecked(False)
    assert not win.left.git_allowed(share)


def test_servers_and_archives_are_never_asked(world, monkeypatch):
    win, *_ = world
    asked = []
    monkeypatch.setattr(gitinfo, "find_root", lambda path, *a: asked.append(path))
    for path in ("sftp://me@host:22/repo", "zip://C:/a.zip!/x"):
        monkeypatch.setattr(type(win.left), "path", property(lambda self, p=path: p), raising=False)
        win.left.refresh_git()
    assert asked == [] and not win.left.git_label.isVisibleTo(win.left)
