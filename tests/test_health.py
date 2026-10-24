"""File health checks: a 'museum' of broken files in which every rule has a case, a clean tree that reports nothing, the tiers, cancel, and the fixes."""
import io
import os
import time
import unicodedata
import zipfile

import pytest

from dossier.core import health
from dossier.core.ops import execute
from dossier.core.progress import CancelToken, Cancelled
from dossier.core.vfs import LocalFileSystem

T0 = 1_700_000_000


def put(path, data=b"x", mtime=T0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def make_zip(path, entries=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in (entries or {"a.txt": b"hello world"}).items():
            z.writestr(name, data)
    return put(path, buf.getvalue())


@pytest.fixture
def clean(tmp_path):
    root = tmp_path / "clean"
    make_zip(root / "book.cbz")
    put(root / "film.mkv", b"video bytes")
    put(root / "film.srt", b"subtitles")
    put(root / "notes" / "readme.txt", b"hello")
    return root


@pytest.fixture
def museum(tmp_path):
    root = tmp_path / "museum"
    put(root / "empty.dat", b"")
    put(root / "Thumbs.db", b"junk")
    put(root / "~$report.docx", b"lock")
    put(root / "trail.txt ", b"x") if os.name != "nt" else None
    put(root / "aux.txt", b"x") if os.name != "nt" else None
    put(root / "Beach.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)
    put(root / "fake.jpg", b"PK\x03\x04" + b"0" * 20)
    put(root / "orphan.srt", b"x")
    put(root / ("cafe" + "́" + ".txt"), b"x")
    put(root / "Ã©té.txt".replace("é", "©"), b"x")
    put(root / "future.txt", b"x", mtime=time.time() + 10 * 86400)
    put(root / "twin" / "Same.txt", b"a") if os.name != "nt" else None
    put(root / "twin" / "same.txt", b"b")
    (root / "hollow").mkdir()
    (root / "junkonly").mkdir()
    put(root / "junkonly" / "desktop.ini", b"j")
    good = make_zip(root / "good.cbz")
    data = bytearray(good.read_bytes())
    data[data.index(b"hello world")] ^= 0xFF                      # flip a byte of the stored content: the CRC no longer matches
    put(root / "damaged.cbz", bytes(data))
    put(root / "truncated.zip", good.read_bytes()[:30])
    make_zip(root / "escape.zip", {"../evil.txt": b"x"})
    return root


def rules(report):
    return {(os.path.basename(f.path), f.rule) for f in report.findings}


def test_a_clean_tree_reports_nothing(clean):
    report = health.run_checks(LocalFileSystem(), [str(clean)], max_tier=health.T2)
    assert report.findings == []
    assert report.files == 4 and report.folders == 2


def test_the_museum_is_found(museum):
    found = rules(health.run_checks(LocalFileSystem(), [str(museum)], max_tier=health.T2))
    expected = {("empty.dat", "empty-file"), ("Thumbs.db", "junk-file"), ("~$report.docx", "junk-file"), ("Beach.JPG", "upper-case-extension"),
                ("fake.jpg", "wrong-extension"), ("orphan.srt", "orphan-sidecar"), ("future.txt", "future-date"), ("hollow", "empty-folder"),
                ("junkonly", "empty-folder"), ("damaged.cbz", "bad-crc"), ("truncated.zip", "bad-zip"), ("escape.zip", "path-escape")}
    assert expected <= found
    assert any(rule == "not-nfc" for _n, rule in found)
    assert any(rule == "mojibake" for _n, rule in found)


def test_tiers_gate_the_work(museum):
    fs = LocalFileSystem()
    shallow = rules(health.run_checks(fs, [str(museum)], max_tier=health.T0))
    assert ("fake.jpg", "wrong-extension") not in shallow and ("damaged.cbz", "bad-crc") not in shallow
    normal = rules(health.run_checks(fs, [str(museum)]))
    assert ("fake.jpg", "wrong-extension") in normal and ("damaged.cbz", "bad-crc") not in normal


def test_only_runs_the_named_checkers(museum):
    report = health.run_checks(LocalFileSystem(), [str(museum)], only=["junk"])
    assert {f.checker for f in report.findings} == {"junk"}


def test_sorted_worst_first(museum):
    report = health.run_checks(LocalFileSystem(), [str(museum)], max_tier=health.T2)
    severities = [health.SEVERITIES.index(f.severity) for f in report.findings]
    assert severities == sorted(severities)
    assert report.findings[0].severity == health.ERROR


def test_cancel_stops_the_run(clean):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        health.run_checks(LocalFileSystem(), [str(clean)], cancel=token)


def test_unreadable_folder_is_counted(tmp_path):
    report = health.run_checks(LocalFileSystem(), [str(tmp_path / "missing")])
    assert report.unreadable == 1 and report.findings == []


def test_ordinary_names_are_not_flagged(tmp_path):
    for name in ("Report 2024.pdf", "a.b.c.txt", "naïve café.mp3", "Ünïcode.TXT.bak", "con_tent.txt"):
        put(tmp_path / name, b"data")
    report = health.run_checks(LocalFileSystem(), [str(tmp_path)])
    assert report.findings == []


def test_zero_byte_placeholders_are_allowed(tmp_path):
    put(tmp_path / ".gitkeep", b"")
    assert health.run_checks(LocalFileSystem(), [str(tmp_path)]).findings == []


def test_rename_fix_is_a_plan_that_runs(tmp_path):
    put(tmp_path / "Beach.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)
    put(tmp_path / ("cafe" + "́" + ".txt"), b"x")
    fs = LocalFileSystem()
    report = health.run_checks(fs, [str(tmp_path)])
    plan = health.fix_plan(fs, report.findings)
    assert plan is not None and not plan.blocking
    result = execute(plan, fs)
    assert not result.failed
    names = set(os.listdir(tmp_path))
    assert "Beach.jpg" in names and unicodedata.normalize("NFC", "café.txt") in names
    assert health.run_checks(fs, [str(tmp_path)]).findings == []


def test_delete_fix_goes_to_the_bin(tmp_path):
    put(tmp_path / "Thumbs.db", b"j")
    fs = LocalFileSystem()
    plan = health.fix_plan(fs, health.run_checks(fs, [str(tmp_path)]).findings)
    binned = []
    execute(plan, fs, trasher=lambda p: (binned.append(p), os.remove(p)))
    assert [os.path.basename(p) for p in binned] == ["Thumbs.db"]
    assert tmp_path.is_dir()                                     # the folder that was checked is never reported as empty


def test_a_plan_does_not_mix_renames_and_deletes(tmp_path):
    put(tmp_path / "Thumbs.db", b"j")
    put(tmp_path / "Beach.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)
    fs = LocalFileSystem()
    with pytest.raises(ValueError):
        health.fix_plan(fs, health.run_checks(fs, [str(tmp_path)]).findings)


def test_every_checker_has_a_unique_id_and_valid_tier():
    found = health.checkers()
    assert len({c.id for c in found}) == len(found) >= 10
    assert all(c.tier in (health.T0, health.T1, health.T2) and c.scope in (health.FILE, health.FOLDER) for c in found)


def test_empty_and_damaged_files_get_a_quarantine_fix_that_moves_them_and_keeps_their_place(tmp_path):
    from dossier.core import quarantine
    put(tmp_path / "work" / "empty.dat", b"")
    bad = str(put(tmp_path / "work" / "bad.zip", b"PK\x03\x04" + b"0" * 30))
    s = quarantine.Settings(quarantine.FOLDER, str(tmp_path / "Q"))
    fs = LocalFileSystem()
    report = health.run_checks(fs, [str(tmp_path / "work")], max_tier=health.T2)
    isolate = [f for f in report.findings if f.fix and f.fix.kind == "quarantine"]
    assert {os.path.basename(f.path) for f in isolate} == {"empty.dat", "bad.zip"}
    plan = health.fix_plan(fs, isolate, s)
    assert plan.title == "Move to quarantine" and not plan.blocking
    assert not (tmp_path / "Q").exists()                                                     # planning made nothing
    assert not execute(plan, fs).failed
    assert not os.path.exists(bad) and os.path.isfile(quarantine.destination(bad, s))          # moved, never deleted
    assert os.path.isfile(quarantine.destination(str(tmp_path / "work" / "empty.dat"), s))


def test_a_plan_does_not_mix_quarantine_with_renames(tmp_path):
    put(tmp_path / "empty.dat", b"")
    put(tmp_path / "Beach.JPG", b"\xff\xd8\xff\xe0" + b"0" * 20)
    fs = LocalFileSystem()
    with pytest.raises(ValueError):
        health.fix_plan(fs, health.run_checks(fs, [str(tmp_path)]).findings)
