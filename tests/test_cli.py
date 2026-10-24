"""Dossier's command line: every command on real files, the rules they all follow (dry run, nothing overwritten, the bin, JSON, exit codes),
the entry point, and that the documentation names everything."""
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

from dossier import cli
from dossier.cli import commands
from dossier.core import askpass
from dossier.core.version import RELEASE

T0 = 1_700_000_000


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    """The recycle bin of the tests: a folder, never the real one."""
    folder = tmp_path / "_bin"
    folder.mkdir()

    def trash(path):
        shutil.move(path, str(folder / (str(len(os.listdir(folder))) + "-" + os.path.basename(path))))
    monkeypatch.setattr(commands, "default_trash", trash)
    return folder


def run(capsys, *argv):
    from redactor_common.cli import run as run_cli                      # what the program does: a mistake becomes a message and exit code 2
    code = run_cli(cli.main, list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    return code, json.loads(out), err


def put(path, data=b"x", mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return str(path)


# the entry point ----------------------------------------------------------------------------------------------------------------------
def test_only_a_command_name_means_the_command_line():
    assert cli.cli_requested(["dossier", "ls"]) and cli.cli_requested(["dossier", "dups", "x"]) and cli.cli_requested(["dossier", "--help"])
    assert cli.cli_requested(["dossier", "help"]) and cli.cli_requested(["dossier", "--version"])
    assert not cli.cli_requested(["dossier"]) and not cli.cli_requested(["dossier", "C:/Users/me"]) and not cli.cli_requested(["dossier", "--check"])
    assert not cli.cli_requested([])


def test_the_program_runs_a_command_without_starting_the_window(tmp_path):
    put(tmp_path / "a.txt")
    done = subprocess.run([sys.executable, "-m", "dossier", "ls", str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "a.txt" and done.stderr == ""
    bad = subprocess.run([sys.executable, "-m", "dossier", "ls", str(tmp_path / "nope")], capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2 and "does not exist" in bad.stderr
    version = subprocess.run([sys.executable, "-m", "dossier", "--version"], capture_output=True, text=True, timeout=60)
    assert version.returncode == 0 and f"Dossier {RELEASE} (build 20" in version.stdout


def test_ssh_can_ask_the_program_for_a_password_through_the_same_entry(tmp_path):
    env = dict(os.environ, **{askpass.VARIABLE: "s3cret"})
    done = subprocess.run([sys.executable, "-m", "dossier", "--askpass", "me@host's password: "], capture_output=True, env=env, timeout=60)
    assert done.returncode == 0 and done.stdout.decode().strip() == "s3cret"


def test_help_lists_every_command_and_a_mistake_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    text = capsys.readouterr().out
    assert all(name in text for name in cli.COMMANDS)
    with pytest.raises(SystemExit) as e:
        cli.main(["copy"])
    assert e.value.code == 2


# ls, info, find ------------------------------------------------------------------------------------------------------------------------
def test_ls_lists_folders_first_in_natural_order_and_long_and_json(tmp_path, capsys):
    (tmp_path / "dir").mkdir()
    for n in ("img10.jpg", "img2.jpg", "A.txt"):
        put(tmp_path / n, b"12345")
    code, out, _e = run(capsys, "ls", str(tmp_path))
    assert code == 0 and out.split() == ["dir/", "A.txt", "img2.jpg", "img10.jpg"]
    code, out, _e = run(capsys, "ls", str(tmp_path), "-l")
    assert "5.0 B" in out or "5 B" in out
    code, doc, _e = run_json(capsys, "ls", str(tmp_path))
    assert [r["name"] for r in doc["results"]] == ["dir", "A.txt", "img2.jpg", "img10.jpg"] and doc["count"] == 4 and doc["results"][0]["is_dir"]


def test_an_archive_file_is_listed_like_a_folder(tmp_path, capsys):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("in/one.txt", "1")
    code, out, _e = run(capsys, "ls", str(z))
    assert code == 0 and "in/" in out


def test_info_shows_size_times_and_what_is_inside_a_comic(tmp_path, capsys):
    cbz = tmp_path / "Saga 012.cbz"
    with zipfile.ZipFile(cbz, "w") as z:
        z.writestr("ComicInfo.xml", "<ComicInfo><Series>Saga</Series><Number>12</Number></ComicInfo>")
        z.writestr("p1.jpg", b"x")
    code, doc, _e = run_json(capsys, "info", str(cbz), "--bytes")
    row = doc["results"][0]
    assert code == 0 and row["type"] == "file" and row["size"] > 0 and any(f["key"] == "series" and f["value"] == "Saga" for f in row["metadata"])
    code, out, _e = run(capsys, "info", str(cbz))
    assert "Series: Saga" in out and "Size:" in out
    code, _o, err = run(capsys, "info", str(tmp_path / "missing"))
    assert code == 2 and "not found" in err


def test_find_filters_by_name_size_date_and_text(tmp_path, capsys):
    put(tmp_path / "a" / "report.txt", b"alpha needle beta", T0)
    put(tmp_path / "a" / "other.txt", b"nothing", T0 + 86400 * 400)
    put(tmp_path / "b" / "big.bin", b"B" * 5000, T0)
    root = str(tmp_path)
    code, out, _e = run(capsys, "find", root, "--name", "*.txt")
    assert sorted(os.path.basename(p) for p in out.split("\n") if p) == ["other.txt", "report.txt"]
    assert run(capsys, "find", root, "--text", "needle")[1].strip().endswith("report.txt")
    assert run(capsys, "find", root, "--min-size", "1K")[1].strip().endswith("big.bin")
    assert run(capsys, "find", root, "--newer", "2024-06-01", "--name", "*.txt")[1].strip().endswith("other.txt")
    code, doc, _e = run_json(capsys, "find", root, "--kind", "folders")
    assert sorted(os.path.basename(r["path"]) for r in doc["results"]) == ["a", "b"] and doc["count"] == 2
    code, _o, err = run(capsys, "find", root, "--min-size", "ten")
    assert code == 2 and "not a size" in err
    code, _o, err = run(capsys, "find", root, "--min-size", "10K", "--max-size", "1K")
    assert code == 2


# checksum ---------------------------------------------------------------------------------------------------------------------------------
def test_checksums_print_in_the_sha256sum_format_and_can_be_checked(tmp_path, capsys):
    put(tmp_path / "a.txt", b"hello")
    put(tmp_path / "b.txt", b"world")
    code, out, _e = run(capsys, "checksum", str(tmp_path / "a.txt"), str(tmp_path / "b.txt"))
    lines = out.strip().splitlines()
    assert code == 0 and lines[0].startswith("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824 *")
    (tmp_path / "sums.txt").write_text("\n".join(f"{ln.split(' *')[0]} *{os.path.basename(ln.split(' *')[1])}" for ln in lines) + "\n")
    code, out, _e = run(capsys, "checksum", "--check", str(tmp_path / "sums.txt"))
    assert code == 0 and out.count(": ok") == 2
    (tmp_path / "b.txt").write_bytes(b"changed")
    os.remove(tmp_path / "a.txt")
    code, out, _e = run(capsys, "checksum", "--check", str(tmp_path / "sums.txt"))
    assert code == 1 and "a.txt: missing" in out and "b.txt: FAILED" in out
    code, doc, _e = run_json(capsys, "checksum", str(tmp_path / "b.txt"), "-a", "md5")
    assert doc["results"][0]["algorithm"] == "md5" and len(doc["results"][0]["digest"]) == 32


# copy, move, delete --------------------------------------------------------------------------------------------------------------------------
def test_copy_never_overwrites_by_default_and_a_dry_run_changes_nothing(tmp_path, capsys, bin_dir):
    put(tmp_path / "src" / "a.txt", b"new")
    put(tmp_path / "src" / "dir" / "b.txt", b"b")
    put(tmp_path / "dest" / "a.txt", b"old")
    dest = str(tmp_path / "dest")
    code, out, _e = run(capsys, "copy", str(tmp_path / "src" / "a.txt"), str(tmp_path / "src" / "dir"), dest, "--dry-run")
    assert code == 0 and "nothing was done" in out and not (tmp_path / "dest" / "dir").exists()
    code, out, _e = run(capsys, "copy", str(tmp_path / "src" / "a.txt"), str(tmp_path / "src" / "dir"), dest)
    assert code == 0 and (tmp_path / "dest" / "a.txt").read_bytes() == b"old" and (tmp_path / "dest" / "dir" / "b.txt").read_bytes() == b"b"
    code, doc, _e = run_json(capsys, "copy", str(tmp_path / "src" / "a.txt"), dest, "--on-conflict", "overwrite")
    assert code == 0 and (tmp_path / "dest" / "a.txt").read_bytes() == b"new" and doc["done"] >= 1
    assert any(p.name.endswith("a.txt.dossier-old") or p.name.endswith("a.txt") for p in bin_dir.iterdir())          # the old file went to the bin


def test_copy_keep_both_and_newer(tmp_path, capsys, bin_dir):
    put(tmp_path / "src" / "f.txt", b"source", T0 + 1000)
    put(tmp_path / "dest" / "f.txt", b"dest", T0)
    run(capsys, "copy", str(tmp_path / "src" / "f.txt"), str(tmp_path / "dest"), "--on-conflict", "keep-both")
    assert sorted(os.listdir(tmp_path / "dest")) != ["f.txt"] and (tmp_path / "dest" / "f.txt").read_bytes() == b"dest"
    put(tmp_path / "dest2" / "f.txt", b"dest", T0 + 5000)
    run(capsys, "copy", str(tmp_path / "src" / "f.txt"), str(tmp_path / "dest2"), "--on-conflict", "newer")
    assert (tmp_path / "dest2" / "f.txt").read_bytes() == b"dest"                       # the destination is newer: it stays
    put(tmp_path / "dest3" / "f.txt", b"dest", T0)
    run(capsys, "copy", str(tmp_path / "src" / "f.txt"), str(tmp_path / "dest3"), "--on-conflict", "newer")
    assert (tmp_path / "dest3" / "f.txt").read_bytes() == b"source"


def test_the_destination_must_exist_unless_create_is_given_and_missing_sources_are_a_usage_error(tmp_path, capsys, bin_dir):
    put(tmp_path / "a.txt")
    code, _o, err = run(capsys, "copy", str(tmp_path / "a.txt"), str(tmp_path / "newfolder"))
    assert code == 2 and "does not exist" in err and not (tmp_path / "newfolder").exists()
    code, _o, _e = run(capsys, "copy", str(tmp_path / "a.txt"), str(tmp_path / "newfolder"), "--create")
    assert code == 0 and (tmp_path / "newfolder" / "a.txt").exists()
    code, _o, err = run(capsys, "copy", str(tmp_path / "nope.txt"), str(tmp_path))
    assert code == 2 and "not found" in err
    code, _o, err = run(capsys, "copy", str(tmp_path / "a.txt"))
    assert code == 2


def test_wildcards_are_expanded_and_move_moves(tmp_path, capsys, bin_dir):
    for n in ("one.txt", "two.txt", "keep.dat"):
        put(tmp_path / "src" / n)
    (tmp_path / "dest").mkdir()
    code, _o, _e = run(capsys, "move", str(tmp_path / "src" / "*.txt"), str(tmp_path / "dest"))
    assert code == 0 and sorted(os.listdir(tmp_path / "dest")) == ["one.txt", "two.txt"] and os.listdir(tmp_path / "src") == ["keep.dat"]
    code, _o, err = run(capsys, "move", str(tmp_path / "src" / "*.nothing"), str(tmp_path / "dest"))
    assert code == 2 and "not found" in err


def test_delete_goes_to_the_bin_a_dry_run_does_nothing_and_permanent_is_the_only_way_for_good(tmp_path, capsys, bin_dir):
    put(tmp_path / "a.txt")
    put(tmp_path / "b.txt")
    put(tmp_path / "c.txt")
    code, out, _e = run(capsys, "delete", str(tmp_path / "a.txt"), "--dry-run")
    assert code == 0 and (tmp_path / "a.txt").exists() and not os.listdir(bin_dir)
    code, _o, _e = run(capsys, "delete", str(tmp_path / "a.txt"))
    assert code == 0 and not (tmp_path / "a.txt").exists() and len(os.listdir(bin_dir)) == 1
    code, out, err = run(capsys, "delete", str(tmp_path / "b.txt"), "--permanent")
    assert code == 0 and not (tmp_path / "b.txt").exists() and len(os.listdir(bin_dir)) == 1 and "permanently" in err
    code, doc, _e = run_json(capsys, "delete", str(tmp_path / "c.txt"), "--dry-run")
    assert doc["dry_run"] is True and doc["steps"] == 1 and doc["results"][0]["op"] == "delete"


# dups, compare ----------------------------------------------------------------------------------------------------------------------------------
def test_dups_reports_groups_and_deletes_only_the_extras_leaving_one_copy(tmp_path, capsys, bin_dir):
    put(tmp_path / "a" / "x.dat", b"S" * 3000, T0)
    put(tmp_path / "b" / "x-copy.dat", b"S" * 3000, T0 + 500)
    put(tmp_path / "c" / "x3.dat", b"S" * 3000, T0 + 900)
    put(tmp_path / "c" / "alone.dat", b"unique")
    root = str(tmp_path)
    code, out, _e = run(capsys, "dups", root, "--min-size", "10")
    kept = [ln for ln in out.splitlines() if ln.startswith("  keep ")]
    extra = [ln for ln in out.splitlines() if ln.startswith("  extra ")]
    assert code == 0 and "Group 1: 3 copies" in out and len(kept) == 1 and len(extra) == 2
    code, doc, _e = run_json(capsys, "dups", root)
    group = doc["results"][0]
    assert doc["groups"] == 1 and doc["wasted"] == 6000 and [f["keep"] for f in group["files"]] == [True, False, False]
    code, out, _e = run(capsys, "dups", root, "--delete", "--dry-run")
    assert code == 0 and (tmp_path / "b" / "x-copy.dat").exists() and (tmp_path / "c" / "x3.dat").exists()
    code, _o, _e = run(capsys, "dups", root, "--delete", "--keep", "newest")
    assert code == 0 and (tmp_path / "c" / "x3.dat").exists() and not (tmp_path / "a" / "x.dat").exists() and not (tmp_path / "b" / "x-copy.dat").exists()
    assert (tmp_path / "c" / "alone.dat").exists() and len(os.listdir(bin_dir)) == 2


def test_compare_lists_the_differences_and_sync_dry_run_then_real(tmp_path, capsys, bin_dir):
    put(tmp_path / "L" / "same.txt", b"s")
    put(tmp_path / "R" / "same.txt", b"s")
    put(tmp_path / "L" / "only_l.txt", b"L")
    put(tmp_path / "R" / "only_r.txt", b"R")
    put(tmp_path / "L" / "n.txt", b"new on the left", T0 + 900)
    put(tmp_path / "R" / "n.txt", b"old", T0)
    left, right = str(tmp_path / "L"), str(tmp_path / "R")
    code, out, _e = run(capsys, "compare", left, right)
    assert code == 0 and "only-left" in out and "only-right" in out and "left-newer" in out and "3 differences" in out
    code, doc, _e = run_json(capsys, "compare", left, right)
    assert {r["path"]: r["status"] for r in doc["results"]} == {"n.txt": "left-newer", "only_l.txt": "only-left", "only_r.txt": "only-right"}
    code, out, _e = run(capsys, "compare", left, right, "--sync", "update_right", "--dry-run")
    assert code == 0 and "nothing was done" in out and not (tmp_path / "R" / "only_l.txt").exists()
    code, doc, _e = run_json(capsys, "compare", left, right, "--sync", "update_right")
    assert code == 0 and doc["done"] == 2 and (tmp_path / "R" / "only_l.txt").exists() and (tmp_path / "R" / "n.txt").read_bytes() == b"new on the left"
    assert (tmp_path / "R" / "only_r.txt").exists()                                      # update never deletes
    code, _o, _e = run(capsys, "compare", left, right, "--sync", "mirror_right")
    assert code == 0 and not (tmp_path / "R" / "only_r.txt").exists() and len(os.listdir(bin_dir)) >= 1
    assert run(capsys, "compare", left, right)[1].count("only-") == 0


def test_json_and_output_file_hold_one_complete_document(tmp_path, capsys):
    put(tmp_path / "a.txt")
    target = tmp_path / "result.json"
    code, out, _e = run(capsys, "ls", str(tmp_path), "--json", "-o", str(target))
    assert code == 0 and out == ""                                                      # nothing on stdout: it all went to the file
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert [r["name"] for r in doc["results"] if r["name"] == "a.txt"] == ["a.txt"] and doc["command"] == "ls"


# the documentation names everything ----------------------------------------------------------------------------------------------------------
def test_the_documentation_names_every_command_and_every_option():
    doc = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "cli.md"), encoding="utf-8").read()
    parser = commands.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    missing = []
    for name, p in sub.choices.items():
        if f"### {name}" not in doc and f"### copy, move" not in doc:
            missing.append(name)
        for action in p._actions:
            for option in action.option_strings:
                if option.startswith("--") and option not in ("--help", "--json", "--quiet", "--output") and option not in doc:
                    missing.append(f"{name} {option}")
    assert not missing, missing


def test_check_reports_and_fixes(tmp_path, capsys, bin_dir):
    data = tmp_path / "data"
    put(data / "Thumbs.db", b"j")
    put(data / "Beach.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)
    code, doc, _err = run_json(capsys, "check", str(data))
    assert code == 0 and doc["findings"] == 2 and doc["warning"] == 0
    assert {r["rule"] for r in doc["results"]} == {"junk-file", "upper-case-extension"}
    code, doc, _err = run_json(capsys, "check", str(data), "--fix", "--dry-run")
    assert code == 0 and doc["dry_run"] and (data / "Beach.JPG").exists()
    code, doc, _err = run_json(capsys, "check", str(data), "--fix")
    assert "Beach.jpg" in os.listdir(data)
    code, doc, _err = run_json(capsys, "check", str(data), "--fix", "--delete-junk")
    assert not (data / "Thumbs.db").exists() and data.is_dir()


def test_check_lists_its_checkers_and_refuses_an_unknown_one(tmp_path, capsys):
    code, doc, _err = run_json(capsys, "check", str(tmp_path), "--list")
    assert code == 0 and doc["checkers"] >= 10
    code, _out, err = run(capsys, "check", str(tmp_path), "--only", "nonsense")
    assert code == 2


def test_link_makes_a_hard_link_and_info_shows_it(tmp_path, capsys):
    src = put(tmp_path / "a.txt", b"hello")
    code, doc, _err = run_json(capsys, "link", src, str(tmp_path / "b.txt"), "--kind", "hardlink")
    assert code == 0 and open(tmp_path / "b.txt").read() == "hello"
    code, doc, _err = run_json(capsys, "info", src)
    assert "2 names" in doc["results"][0]["link_info"]
    code, _out, err = run(capsys, "link", src, str(tmp_path / "b.txt"), "--kind", "hardlink")
    assert code == 2 and "already there" in err
    code, doc, _err = run_json(capsys, "link", src, str(tmp_path), "--kind", "hardlink")                  # into an existing folder
    assert code == 0 and (tmp_path / "a - link.txt").exists()


def test_touch_previews_then_changes_dates(tmp_path, capsys):
    a = put(tmp_path / "a.txt", mtime=T0)
    code, doc, _err = run_json(capsys, "touch", a, "--set", "2024-05-17 10:30", "--dry-run")
    assert code == 0 and doc["dry_run"] and doc["items"] == 1 and os.stat(a).st_mtime == T0
    code, doc, _err = run_json(capsys, "touch", a, "--shift", "+1d2h")
    assert code == 0 and os.stat(a).st_mtime == T0 + 86400 + 7200
    code, doc, _err = run_json(capsys, "touch", a, "--readonly", "on")
    assert code == 0 and not os.access(a, os.W_OK)
    code, doc, _err = run_json(capsys, "touch", a, "--readonly", "off", "--set", "2020-01-01")
    assert code == 0 and os.access(a, os.W_OK)


def test_touch_goes_into_folders_and_refuses_nonsense(tmp_path, capsys):
    put(tmp_path / "d" / "x.txt", mtime=T0)
    code, doc, _err = run_json(capsys, "touch", str(tmp_path / "d"), "-r", "--no-folders", "--set", "2024-01-01")
    assert code == 0 and doc["done"] == 1
    assert os.stat(tmp_path / "d").st_mtime != os.stat(tmp_path / "d" / "x.txt").st_mtime
    code, _out, err = run(capsys, "touch", str(tmp_path / "d"))
    assert code == 2 and "nothing to change" in err
    code, _out, err = run(capsys, "touch", str(tmp_path / "d"), "--shift", "soon")
    assert code == 2 and "not a time difference" in err


def test_check_can_quarantine_instead_of_renaming(tmp_path, capsys):
    data = tmp_path / "data"
    put(data / "empty.dat", b"")
    safe = tmp_path / "safe"
    code, doc, _err = run_json(capsys, "check", str(data), "--fix", "--quarantine", "--quarantine-folder", str(safe), "--dry-run")
    assert doc["dry_run"] and (data / "empty.dat").exists() and not safe.exists()          # planning made nothing
    code, doc, _err = run_json(capsys, "check", str(data), "--fix", "--quarantine", "--quarantine-folder", str(safe))
    assert not (data / "empty.dat").exists()
    assert [p for p in safe.rglob("empty.dat")]                                    # it is in the quarantine, in its own place
    code, _out, err = run(capsys, "check", str(data), "--fix", "--quarantine", "--delete-junk")
    assert code == 2 and "two different fixes" in err
