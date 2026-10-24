"""Grouping and ignoring findings, and a stopped run that keeps what it found (what the Health window is built on)."""
import os

from dossier.core import health
from dossier.core.progress import CancelToken
from dossier.core.vfs import LocalFileSystem

f = health.finding


def test_groups_are_worst_first_then_biggest():
    findings = [f("a1", "n", "junk-file", health.INFO, "m"), f("a2", "n", "junk-file", health.INFO, "m"), f("b", "n", "bad-crc", health.ERROR, "m"),
                f("c1", "n", "empty-file", health.WARNING, "m"), f("c2", "n", "empty-file", health.WARNING, "m"), f("c3", "n", "empty-file", health.WARNING, "m"),
                f("d", "n", "mojibake", health.WARNING, "m")]
    groups = health.group_by_rule(findings)
    assert [(g.rule, g.count) for g in groups] == [("bad-crc", 1), ("empty-file", 3), ("mojibake", 1), ("junk-file", 2)]
    mixed = health.group_by_rule([f("x", "n", "r", health.INFO, "m"), f("y", "n", "r", health.ERROR, "m")])
    assert mixed[0].severity == health.ERROR and mixed[0].count == 2


def test_a_group_knows_how_many_of_its_findings_can_be_fixed():
    fix = health.Fix("delete", "Delete")
    group = health.group_by_rule([f("a", "n", "r", health.INFO, "m", fix=fix), f("b", "n", "r", health.INFO, "m")])[0]
    assert (group.count, group.fixable) == (2, 1)


def test_an_ignored_rule_hides_findings_only_below_its_folder(tmp_path):
    inside = f(str(tmp_path / "photos" / "a.jpg"), "n", "junk-file", health.INFO, "m")
    outside = f(str(tmp_path / "music" / "b.mp3"), "n", "junk-file", health.INFO, "m")
    other_rule = f(str(tmp_path / "photos" / "c.jpg"), "n", "empty-file", health.WARNING, "m")
    sibling = f(str(tmp_path / "photos-old" / "d.jpg"), "n", "junk-file", health.INFO, "m")          # a name that only starts the same
    ignores = health.IgnoreList()
    assert ignores.visible([inside, outside]) == [inside, outside] and len(ignores) == 0
    ignores.add(str(tmp_path / "photos"), "junk-file")
    assert ignores.visible([inside, outside, other_rule, sibling]) == [outside, other_rule, sibling]
    ignores.clear()
    assert ignores.visible([inside]) == [inside]


def test_a_stopped_run_can_keep_what_it_found(tmp_path):
    (tmp_path / "empty.dat").write_bytes(b"")
    token = CancelToken()
    token.cancel()
    report = health.run_checks(LocalFileSystem(), [str(tmp_path)], cancel=token, partial_on_cancel=True)
    assert report.cancelled and report.findings == []
    assert os.path.exists(tmp_path / "empty.dat")
