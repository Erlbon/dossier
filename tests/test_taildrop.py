"""Taildrop core: the commands, one file at a time, the program's own words on failure, Cancel, receiving into a folder. No real Tailscale."""
import subprocess

from dossier.core import taildrop
from dossier.core.progress import CancelToken


def fake_runner(codes=None, texts=None, log=None):
    log = log if log is not None else []

    def run(command, cancel=None):
        log.append(command)
        n = len(log) - 1
        return (codes or {}).get(n, 0), (texts or {}).get(n, "")
    run.log = log
    return run


def test_the_commands_are_one_file_to_a_device_and_a_folder_to_get_into():
    assert taildrop.send_command("ts", "/a/b.txt", "100.64.0.2") == ["ts", "file", "cp", "/a/b.txt", "100.64.0.2:"]
    assert taildrop.receive_command("ts", "/in") == ["ts", "file", "get", "/in"]


def test_files_are_sent_one_by_one_with_progress_and_failures_in_the_programs_words(tmp_path):
    files = []
    for name in ("a.txt", "b.txt", "c.txt"):
        p = tmp_path / name
        p.write_text(name)
        files.append(str(p))
    run = fake_runner(codes={1: 1}, texts={1: "  can't send: device is offline  "})
    seen = []
    results = taildrop.send_files("ts", files, "100.64.0.2", runner=run, progress=lambda d, t: seen.append((d, t)))
    assert [c[3] for c in run.log] == files and all(c[4] == "100.64.0.2:" for c in run.log)
    assert [r.ok for r in results] == [True, False, True] and results[1].message == "can't send: device is offline"
    assert seen[0] == (0, 3) and seen[-1] == (3, 3)
    assert taildrop.sent_summary(results, "phone") == "Sent 2 files to phone. 1 not sent"
    assert taildrop.failure_text(results) == "b.txt: can't send: device is offline"


def test_a_failure_without_words_still_says_something_and_folders_and_missing_files_are_not_sent(tmp_path):
    (tmp_path / "d").mkdir()
    one = tmp_path / "x.txt"
    one.write_text("x")
    run = fake_runner(codes={0: 2})
    results = taildrop.send_files("ts", [str(tmp_path / "d"), str(tmp_path / "gone.txt"), str(one)], "h", runner=run)
    assert "not folders" in results[0].message and results[1].message == "The file is not there."
    assert results[2].message == "tailscale stopped with code 2" and len(run.log) == 1


def test_cancel_stops_between_files_and_during_one(tmp_path):
    files = []
    for name in ("a", "b", "c"):
        (tmp_path / name).write_text(name)
        files.append(str(tmp_path / name))
    token = CancelToken()

    def run(command, cancel=None):
        token.cancel()
        return 0, ""
    results = taildrop.send_files("ts", files, "h", runner=run, cancel=token)
    assert len(results) == 1                                     # the second file never started
    token2 = CancelToken()
    results = taildrop.send_files("ts", files, "h", runner=lambda c, cancel=None: (None, "Cancelled"), cancel=token2)
    assert results == []


def test_run_command_returns_the_output_and_stops_a_program_when_cancelled():
    class Proc:
        returncode = 3

        def communicate(self, timeout=None):
            return " nope \n", None
    code, text = taildrop.run_command(["x"], popen=lambda *a, **k: Proc())
    assert (code, text) == (3, "nope")

    class Slow:
        killed = False
        returncode = None

        def communicate(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("x", timeout)
            return "", None

        def kill(self):
            self.killed = True
    token = CancelToken()
    token.cancel()
    proc = Slow()
    assert taildrop.run_command(["x"], token, popen=lambda *a, **k: proc) == (None, "Cancelled") and proc.killed

    def broken(*a, **k):
        raise FileNotFoundError("no tailscale")
    assert taildrop.run_command(["x"], popen=broken) == (-1, "no tailscale")


def test_receiving_lists_what_arrived_and_reports_the_programs_words(tmp_path):
    def run(command, cancel=None):
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "a.txt").write_text("a")
        return 0, ""
    got = taildrop.receive_files("ts", str(tmp_path), runner=run)
    assert got.ok and got.files == ["a.txt", "b.txt"]
    bad = taildrop.receive_files("ts", str(tmp_path), runner=lambda c, cancel=None: (1, "not logged in"))
    assert not bad.ok and bad.message == "not logged in"
    assert taildrop.receive_files("ts", str(tmp_path), runner=lambda c, cancel=None: (None, "Cancelled")).message == "Cancelled"
