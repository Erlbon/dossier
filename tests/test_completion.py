"""Completing the command line: the word at the cursor, names in the folder, programs on PATH, quotes."""
import os

from dossier.core import completion as cp
from dossier.core.platform import IS_WINDOWS


def touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        if n.endswith("/"):
            (folder / n).mkdir(parents=True, exist_ok=True)
        else:
            (folder / n).write_text("x")


def test_the_word_at_the_cursor():
    assert cp.word_at("copy a.txt b", 12) == (11, "b", "", False)
    assert cp.word_at("copy a.txt b", 6) == (5, "a", "", False)
    assert cp.word_at("ls", 2) == (0, "ls", "", True)
    assert cp.word_at('type "My do', 11) == (5, "My do", '"', False)
    assert cp.word_at("", 0) == (0, "", "", True)
    assert cp.word_at('echo "a b" c', 12) == (11, "c", "", False)


def test_files_and_folders_of_the_folder_folders_first(tmp_path):
    touch(tmp_path, "report.txt", "reports/", "readme.md", "other.txt")
    got = cp.complete("open re", 7, str(tmp_path))
    assert got.items == ["reports" + os.sep, "readme.md", "report.txt"] and (got.start, got.end) == (5, 7)
    assert got.common() == "re"


def test_a_unique_match_and_the_common_start(tmp_path):
    touch(tmp_path, "alpha-one.txt", "alpha-two.txt", "beta.txt")
    got = cp.complete("cat a", 5, str(tmp_path))
    assert got.items == ["alpha-one.txt", "alpha-two.txt"] and got.common() == "alpha-"
    one = cp.complete("cat b", 5, str(tmp_path))
    assert one.items == ["beta.txt"] and one.render(one.items[0], closing=True) == "beta.txt"


def test_names_with_spaces_are_quoted(tmp_path):
    touch(tmp_path, "My Document.txt", "My Pictures/")
    got = cp.complete("open My", 7, str(tmp_path))
    assert set(got.items) == {"My Document.txt", "My Pictures" + os.sep}
    assert got.render("My Document.txt", closing=True) == '"My Document.txt"'
    assert got.render("My Pictures" + os.sep) == '"My Pictures' + os.sep           # a folder: the quote stays open for the next press
    started = cp.complete('open "My ', 9, str(tmp_path))
    assert started.quote == '"' and len(started.items) == 2 and (started.start, started.end) == (5, 9)
    assert started.render("My Document.txt", closing=True) == '"My Document.txt"'


def test_a_path_with_a_folder_part(tmp_path):
    touch(tmp_path / "sub", "inner.txt", "inside/")
    got = cp.complete("copy sub" + os.sep + "in", 11, str(tmp_path))
    assert got.items == ["sub" + os.sep + "inside" + os.sep, "sub" + os.sep + "inner.txt"]
    forward = cp.complete("copy sub/in", 11, str(tmp_path))
    assert len(forward.items) == 2


def test_an_absolute_path_and_a_missing_folder(tmp_path):
    touch(tmp_path / "abs", "one.txt")
    got = cp.complete("type " + str(tmp_path / "abs") + os.sep + "o", 0 + len("type " + str(tmp_path / "abs") + os.sep + "o"), "elsewhere")
    assert [os.path.basename(i) for i in got.items] == ["one.txt"]
    assert cp.complete("type nowhere" + os.sep + "x", 100, str(tmp_path)).items == []


def test_hidden_names_only_when_asked_for(tmp_path):
    touch(tmp_path, ".secret", "shown.txt")
    assert ".secret" not in cp.complete("ls ", 3, str(tmp_path)).items
    assert ".secret" in cp.complete("ls .", 4, str(tmp_path)).items


def test_the_first_word_completes_programs_and_the_history(tmp_path):
    bin_dir = tmp_path / "bin"
    suffix = ".exe" if IS_WINDOWS else ""
    touch(bin_dir, "gitk" + suffix, "git" + suffix, "other.txt")
    if not IS_WINDOWS:
        for n in ("gitk", "git"):
            os.chmod(bin_dir / n, 0o755)
    got = cp.complete("gi", 2, str(tmp_path), path_dirs=[str(bin_dir)], history=["gitlab-runner --version", "ls"])
    assert got.items == ["git", "gitk", "gitlab-runner"]
    assert "other" not in cp.complete("o", 1, str(tmp_path), path_dirs=[str(bin_dir)]).items
    cached = cp.complete("gi", 2, str(tmp_path), cached_programs=["gizmo"])
    assert cached.items == ["gizmo"]


def test_programs_lists_each_once(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    suffix = ".exe" if IS_WINDOWS else ""
    for d in (a, b):
        touch(d, "tool" + suffix)
        if not IS_WINDOWS:
            os.chmod(d / "tool", 0o755)
    assert cp.programs([str(a), str(b), str(tmp_path / "missing")]) == ["tool"]


def test_nothing_matches_and_an_empty_line(tmp_path):
    touch(tmp_path, "a.txt")
    assert cp.complete("cat zzz", 7, str(tmp_path)).items == []
    assert cp.complete("cat ", 4, str(tmp_path)).items == ["a.txt"]
