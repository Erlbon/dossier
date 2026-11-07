"""Git awareness (plan 2026-11-07, cards 1-4): what git knows about a repository, read with commands that never change it."""
import os
import shutil
import subprocess

import pytest

from dossier.core import gitinfo as G

GIT = shutil.which("git")
NUL = chr(0)


def porcelain(*records):
    return NUL.join(records) + NUL


def test_the_status_answer_gives_the_branch_and_each_item_with_spaces_renames_and_whole_folders():
    raw = porcelain("# branch.oid 0123abc", "# branch.head main", "# branch.upstream origin/main", "# branch.ab +2 -1",
                    "1 .M N... 100644 100644 100644 aaa bbb docs/my notes.md",
                    "1 M. N... 100644 100644 100644 aaa bbb staged.txt",
                    "2 R. N... 100644 100644 100644 aaa bbb R100 new name.txt", "old name.txt",
                    "u UU N... 100644 100644 100644 100644 aaa bbb ccc clash.py",
                    "? scratch/", "? todo.txt", "! build/")
    st = G.parse_status(raw, "C:" + os.sep + "repo")
    assert (st.branch, st.upstream, st.ahead, st.behind) == ("main", "origin/main", 2, 1)
    assert st.states == {"docs/my notes.md": "changed", "staged.txt": "staged", "new name.txt": "staged", "clash.py": "conflict",
                         "scratch/": "new", "todo.txt": "new", "build/": "ignored"}
    assert "old name.txt" not in st.states                               # the old name of a rename is not an item
    assert G.summary(st) == "main · 1 in conflict, 1 changed, 2 staged, 2 new · 2 ahead, 1 behind"


def test_each_item_and_each_folder_shows_its_state_and_a_folder_the_strongest_below_it(tmp_path):
    root = str(tmp_path)
    st = G.parse_status(porcelain("# branch.head main", "1 .M N... 1 1 1 a b src/deep/a.py", "1 M. N... 1 1 1 a b src/b.py",
                                  "? src/new/", "! build/", "! notes.log"), root)
    p = lambda *parts: os.path.join(root, *parts)                         # noqa: E731
    assert G.state_of(st, p("src", "deep", "a.py"), False) == "changed"
    assert G.state_of(st, p("src", "b.py"), False) == "staged"
    assert G.state_of(st, p("src", "c.py"), False) == ""                 # unchanged: nothing shown, as in VS Code
    assert G.state_of(st, p("src"), True) == "changed"                   # changed beats staged
    assert G.state_of(st, p("src", "deep"), True) == "changed"
    assert G.state_of(st, p("src", "new"), True) == "new"
    assert G.state_of(st, p("src", "new", "x.txt"), False) == "new"      # inside a whole new folder
    assert G.state_of(st, p("build"), True) == "ignored" and G.state_of(st, p("build", "out.o"), False) == "ignored"
    assert G.state_of(st, p("notes.log"), False) == "ignored"
    assert G.state_of(st, p("docs"), True) == ""
    assert G.state_of(st, p(".git"), True) == ""
    assert G.state_of(st, str(tmp_path.parent / "elsewhere.txt"), False) == ""
    clean = G.parse_status(porcelain("# branch.head (detached)"), root)
    assert G.summary(clean) == "detached · clean"


def test_the_repository_is_found_from_any_folder_inside_it_and_a_worktree_counts(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "a" / "b").mkdir(parents=True)
    assert G.find_root(str(tmp_path / "repo" / "a" / "b")) == str(tmp_path / "repo")
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: elsewhere", encoding="utf-8")    # a worktree or a submodule: .git is a file
    assert G.find_root(str(tmp_path / "wt")) == str(tmp_path / "wt")
    assert G.find_root("zip://C:/a.zip!/x") is None and G.find_root("sftp://me@host:22/") is None


def test_a_refusal_is_said_in_plain_words_and_no_git_is_no_error(tmp_path):
    class Done:
        returncode, stdout = 128, b""
        stderr = b"fatal: detected dubious ownership in repository at 'X'\nTo add an exception for this directory, call:\n"
    with pytest.raises(G.GitError, match="does not trust this folder"):
        G.read_status(str(tmp_path), git="git", runner=lambda argv: Done)
    with pytest.raises(G.GitError, match="not installed"):
        G.read_status(str(tmp_path), git="")


def test_the_command_only_reads_and_takes_no_lock():
    argv = G.status_command("git", "C:" + os.sep + "repo")
    assert argv[:4] == ["git", "-C", "C:" + os.sep + "repo", "--no-optional-locks"] and "status" in argv
    for writing in ("add", "commit", "checkout", "reset", "restore", "stash", "push", "pull", "fetch", "init"):
        assert writing not in argv


def test_answers_are_kept_a_few_seconds_per_repository():
    now = [100.0]
    cache = G.StatusCache(seconds=3, clock=lambda: now[0])
    asked = []
    read = lambda root: asked.append(root) or G.GitStatus(root=root)        # noqa: E731
    cache.get("C:/r", read)
    cache.get("C:/r", read)
    now[0] += 4
    cache.get("C:/r", read)
    cache.forget("C:/r")
    cache.get("C:/r", read)
    assert asked == ["C:/r", "C:/r", "C:/r"]


# a real repository ----------------------------------------------------------------------------------------------------------------
def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args], check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    if GIT is None:
        pytest.skip("git is not installed")
    r = tmp_path / "project"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (r / "README.md").write_text("# p\n", encoding="utf-8")
    (r / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "first")
    return r


def test_a_real_repository_is_read_and_looking_never_changes_it(repo):
    (repo / "src" / "app.py").write_text("print(2)\n", encoding="utf-8")
    (repo / "notes with space.txt").write_text("x", encoding="utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_bytes(b"x")
    index = repo / ".git" / "index"
    before = (index.stat().st_mtime_ns, index.read_bytes())
    st = G.read_status(str(repo))
    assert st.branch == "main"
    assert G.state_of(st, str(repo / "src" / "app.py"), False) == "changed"
    assert G.state_of(st, str(repo / "src"), True) == "changed"
    assert G.state_of(st, str(repo / "notes with space.txt"), False) == "new"
    assert G.state_of(st, str(repo / "build"), True) == "ignored"
    assert G.state_of(st, str(repo / "README.md"), False) == ""
    assert G.summary(st) == "main · 1 changed, 1 new"
    assert (index.stat().st_mtime_ns, index.read_bytes()) == before and not (repo / ".git" / "index.lock").exists()
    assert G.find_root(str(repo / "src")) == str(repo)
